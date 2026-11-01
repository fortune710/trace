import contextlib
import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "recreate-changed-services.py"
SPEC = importlib.util.spec_from_file_location("recreate_changed_services", SCRIPT)
recreate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = recreate
SPEC.loader.exec_module(recreate)

SECRET = "super-secret-value-123"


def services_model(**overrides):
    model = {
        "backend": {
            "image": "trace-backend:production",
            "build": {"context": "./backend"},
            "environment": {"DATABASE_URL": "postgres://db", "API_KEY": SECRET},
        },
        "worker": {
            "image": "trace-backend:production",
            "build": {"context": "./backend"},
            "environment": {"MODE": "worker", "UNSET": None},
        },
        "redis": {"image": "redis:7", "environment": {}},
    }
    model.update(overrides)
    return model


def container(service, image_id, environment):
    return recreate.ContainerState(
        service=service, image_id=image_id, environment=environment
    )


class ParseEnvFileTests(unittest.TestCase):
    def test_reads_renderer_output_with_escaped_quotes(self):
        text = "NAME='it\\'s fine'\nOTHER='plain'\n"
        values = recreate.parse_env_file(text)
        self.assertEqual(values, {"NAME": "it's fine", "OTHER": "plain"})

    def test_reads_developer_style_files(self):
        text = '# comment\n\nexport A=1\nB="two"\nC=three=four\nnot a line\n'
        values = recreate.parse_env_file(text)
        self.assertEqual(values, {"A": "1", "B": "two", "C": "three=four"})


class DiffTests(unittest.TestCase):
    def test_reports_names_for_added_removed_and_changed(self):
        diff = recreate.diff_maps({"A": "1", "B": "2", "C": "3"}, {"A": "1", "B": "x", "D": "4"})
        self.assertEqual(diff.added, ("D",))
        self.assertEqual(diff.removed, ("C",))
        self.assertEqual(diff.changed, ("B",))
        self.assertEqual(diff.describe(), "added D; removed C; changed B")

    def test_identical_maps_are_falsy(self):
        self.assertFalse(recreate.diff_maps({"A": "1"}, {"A": "1"}))


class DriftTests(unittest.TestCase):
    def test_current_container_has_no_drift(self):
        services = services_model()
        containers = {
            "backend": [
                container(
                    "backend",
                    "sha256:new",
                    {"DATABASE_URL": "postgres://db", "API_KEY": SECRET, "PATH": "/bin"},
                )
            ]
        }
        drift = recreate.find_drift(services, containers, {"backend": "sha256:new"})
        self.assertEqual(drift, {})

    def test_detects_stale_image(self):
        services = services_model()
        containers = {
            "backend": [
                container(
                    "backend",
                    "sha256:old",
                    {"DATABASE_URL": "postgres://db", "API_KEY": SECRET},
                )
            ]
        }
        drift = recreate.find_drift(services, containers, {"backend": "sha256:new"})
        self.assertEqual(drift, {"backend": ["running a stale image"]})

    def test_detects_missing_and_outdated_environment_by_name_only(self):
        services = services_model()
        containers = {
            "backend": [container("backend", "sha256:new", {"DATABASE_URL": "other"})]
        }
        drift = recreate.find_drift(services, containers, {"backend": "sha256:new"})
        problems = " ".join(drift["backend"])
        self.assertIn("missing environment API_KEY", problems)
        self.assertIn("outdated environment DATABASE_URL", problems)
        self.assertNotIn(SECRET, problems)
        self.assertNotIn("postgres://db", problems)

    def test_pass_through_variables_are_ignored(self):
        services = services_model()
        containers = {"worker": [container("worker", "sha256:new", {"MODE": "worker"})]}
        drift = recreate.find_drift(services, containers, {"worker": "sha256:new"})
        self.assertEqual(drift, {})

    def test_compose_dollar_escaping_is_normalised(self):
        services = {"app": {"environment": {"PASSWORD": "pa$$word"}}}
        containers = {"app": [container("app", "x", {"PASSWORD": "pa$word"})]}
        self.assertEqual(recreate.find_drift(services, containers, {}), {})


class PlanTests(unittest.TestCase):
    def snapshot(self, **overrides):
        base = dict(
            salt="s",
            env={"A": "1"},
            files={"backend/uv.lock": "h1"},
            services={"backend": "c1", "worker": "c2", "redis": "c3"},
            images={"backend": "sha256:1", "worker": "sha256:1"},
        )
        base.update(overrides)
        return recreate.Snapshot(**base)

    def test_first_run_is_a_baseline_with_nothing_forced(self):
        plan = recreate.make_plan(None, self.snapshot(), services_model(), {})
        self.assertTrue(plan.baseline)
        self.assertEqual(plan.recreate, [])

    def test_unchanged_deploy_recreates_nothing(self):
        plan = recreate.make_plan(self.snapshot(), self.snapshot(), services_model(), {})
        self.assertEqual(plan.recreate, [])
        self.assertEqual(plan.reasons, [])

    def test_rebuilt_image_recreates_every_backend_service(self):
        current = self.snapshot(
            files={"backend/uv.lock": "h2"},
            images={"backend": "sha256:2", "worker": "sha256:2"},
        )
        plan = recreate.make_plan(self.snapshot(), current, services_model(), {})
        self.assertEqual(sorted(plan.recreate), ["backend", "worker"])
        self.assertIn("dependency files changed backend/uv.lock", plan.reasons)
        self.assertIn("backend image was rebuilt", plan.reasons)

    def test_new_environment_variable_is_reported_and_recreates_consumers(self):
        current = self.snapshot(
            env={"A": "1", "NEW_VAR": "h"},
            services={"backend": "c1", "worker": "changed", "redis": "c3"},
        )
        plan = recreate.make_plan(self.snapshot(), current, services_model(), {})
        self.assertEqual(plan.recreate, ["worker"])
        self.assertIn("environment variables added NEW_VAR", plan.reasons)

    def test_new_service_is_planned(self):
        current = self.snapshot(services={"backend": "c1", "worker": "c2", "redis": "c3", "fresh": "c4"})
        plan = recreate.make_plan(self.snapshot(), current, services_model(), {})
        self.assertEqual(plan.recreate, ["fresh"])

    def test_drift_is_planned_even_without_a_previous_record(self):
        plan = recreate.make_plan(
            None, self.snapshot(), services_model(), {"backend": ["running a stale image"]}
        )
        self.assertEqual(plan.recreate, ["backend"])


class SnapshotTests(unittest.TestCase):
    def test_round_trip_permissions_and_no_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            salt = "abc"
            snapshot = recreate.Snapshot(
                salt=salt,
                env=recreate.fingerprint_env({"API_KEY": SECRET}, salt),
                files={"backend/uv.lock": "h"},
                services={"backend": "c"},
                images={"backend": "sha256:1"},
            )
            recreate.save_snapshot(state_dir, snapshot)

            self.assertEqual(stat.S_IMODE(state_dir.stat().st_mode), 0o700)
            path = state_dir / recreate.STATE_FILE_NAME
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn(SECRET, path.read_text())
            loaded = recreate.load_snapshot(state_dir)
            self.assertEqual(loaded.env, snapshot.env)
            self.assertEqual(loaded.images, snapshot.images)

    def test_missing_or_corrupt_state_is_a_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            self.assertIsNone(recreate.load_snapshot(state_dir))
            (state_dir / recreate.STATE_FILE_NAME).write_text("{not json")
            self.assertIsNone(recreate.load_snapshot(state_dir))


class FakeCompose:
    """Stands in for Compose: records calls and models running containers."""

    def __init__(self, services, running, heal_on_up=True):
        self.services = services
        self.running = running
        self.heal_on_up = heal_on_up
        self.calls = []

    def config(self):
        return {"services": self.services}

    def build(self):
        self.calls.append(("build",))

    def up(self, services, *, force_recreate, wait_timeout):
        self.calls.append(("up", tuple(services), force_recreate))
        if self.heal_on_up and (force_recreate or not services):
            targets = services or list(self.running)
            for name in targets:
                self.running[name] = self.healthy(name)

    def healthy(self, name):
        environment = {
            key: value
            for key, value in recreate.configured_environment(self.services[name]).items()
        }
        return {"image": "sha256:new", "env": environment}

    def container_ids(self, service):
        return [service] if service in self.running else []

    def ps(self):
        return "NAME STATUS\n"


class DeployFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.state_dir = self.root / "state"
        self.env_file = self.root / ".env.production"
        self.env_file.write_text(f"API_KEY='{SECRET}'\nMODE='worker'\n")
        (self.root / "backend").mkdir()
        (self.root / "backend/uv.lock").write_text("lock")
        self.addCleanup(self.directory.cleanup)

    def run_deploy(self, compose, *, dry_run=False):
        def fake_run(command):
            if command[:3] == ["docker", "image", "inspect"]:
                return "sha256:new\n"
            if command[:2] == ["docker", "inspect"]:
                name = command[2]
                state = compose.running[name]
                env = [f"{key}={value}" for key, value in state["env"].items()]
                return json.dumps([{"Image": state["image"], "Config": {"Env": env}}])
            raise AssertionError(command)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = recreate.deploy(
                root=self.root,
                env_file=self.env_file,
                compose_files=[Path("compose.production.yaml")],
                state_dir=self.state_dir,
                dependency_files=["backend/uv.lock"],
                dry_run=dry_run,
                skip_build=False,
                wait_timeout=10,
                run=fake_run,
                compose=compose,
            )
        return code, output.getvalue()

    def healthy_running(self, compose):
        return {name: compose.healthy(name) for name in ("backend", "worker", "redis")}

    def test_clean_first_deploy_records_a_baseline(self):
        compose = FakeCompose(services_model(), {})
        compose.running = self.healthy_running(compose)
        code, output = self.run_deploy(compose)

        self.assertEqual(code, 0)
        self.assertTrue((self.state_dir / recreate.STATE_FILE_NAME).is_file())
        self.assertNotIn(("up", ("backend",), True), compose.calls)
        self.assertNotIn(SECRET, output)

    def test_stale_container_is_force_recreated_and_verified(self):
        compose = FakeCompose(services_model(), {})
        compose.running = self.healthy_running(compose)
        compose.running["backend"] = {"image": "sha256:old", "env": compose.running["backend"]["env"]}
        code, output = self.run_deploy(compose)

        self.assertEqual(code, 0)
        self.assertIn(("up", ("backend",), True), compose.calls)
        self.assertIn("backend: running a stale image", output)

    def test_verification_failure_fails_the_deploy_and_keeps_old_state(self):
        compose = FakeCompose(services_model(), {}, heal_on_up=False)
        compose.running = self.healthy_running(compose)
        compose.running["worker"] = {"image": "sha256:old", "env": {"MODE": "worker"}}
        code, output = self.run_deploy(compose)

        self.assertEqual(code, 1)
        self.assertIn("Verification failed: worker is running a stale image", output)
        self.assertFalse((self.state_dir / recreate.STATE_FILE_NAME).exists())

    def test_dry_run_changes_nothing(self):
        compose = FakeCompose(services_model(), {})
        compose.running = self.healthy_running(compose)
        compose.running["backend"] = {"image": "sha256:old", "env": compose.running["backend"]["env"]}
        code, output = self.run_deploy(compose, dry_run=True)

        self.assertEqual(code, 0)
        self.assertEqual(compose.calls, [])
        self.assertFalse(self.state_dir.exists())
        self.assertIn("Would force-recreate: backend", output)

    def test_changed_environment_names_the_variable_not_its_value(self):
        compose = FakeCompose(services_model(), {})
        compose.running = self.healthy_running(compose)
        self.assertEqual(self.run_deploy(compose)[0], 0)

        self.env_file.write_text(f"API_KEY='{SECRET}'\nMODE='worker'\nNEW_FEATURE_FLAG='on-value'\n")
        compose.calls.clear()
        code, output = self.run_deploy(compose)

        self.assertEqual(code, 0)
        self.assertIn("environment variables added NEW_FEATURE_FLAG", output)
        self.assertNotIn("on-value", output)
        self.assertNotIn(SECRET, output)


if __name__ == "__main__":
    unittest.main()
