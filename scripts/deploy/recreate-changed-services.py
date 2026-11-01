#!/usr/bin/env python3
"""Rebuild and recreate Compose services whose dependencies or environment changed.

``docker compose up`` already recreates a container when its own resolved
configuration changes.  This script adds what that does not give a deploy:

* It records what each deploy ran with, so it can say *why* services were
  recreated: which environment variables were added, removed or changed, which
  dependency files changed, and whether the backend image was rebuilt.
* It inspects the running containers and recreates any that drifted from the
  image that was just built or from the environment that is configured now,
  even when no earlier record exists.
* With ``--service-file SERVICE=PATH`` it also recreates a service whose config
  files changed after its container started.  nginx copies ``https.conf`` into a
  temporary ``default.conf`` at startup, so ``nginx -s reload`` never picks up an
  edited file and its healthcheck reports the stale copy as unhealthy.
* It verifies afterwards that every service is running the current image and
  carries the configured environment, and fails the deploy if one does not.

Only variable names are ever printed.  Values are never logged.  The state file
holds salted hashes, is written with mode 0600, and lives in a 0700 directory.

Usage (production, run from the repository root on the host)::

    python3 scripts/deploy/recreate-changed-services.py \\
        --env-file .env.production -f compose.production.yaml \\
        --state-dir /var/lib/trace/deploy-state

Use ``--dry-run`` to print the plan without changing anything.  The same script
works for local development with ``--env-file .env -f compose.yaml``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_VERSION = 1
STATE_FILE_NAME = "snapshot.json"
DEFAULT_DEPENDENCY_FILES = (
    "backend/uv.lock",
    "backend/pyproject.toml",
    "backend/Dockerfile",
)
MISSING_FILE = "missing"

Runner = Callable[[Sequence[str]], str]


class DeployError(RuntimeError):
    """A step failed in a way that should stop the deploy."""


def log(message: str) -> None:
    print(f"[deploy] {message}", flush=True)


# --------------------------------------------------------------------------
# Environment file parsing and fingerprints
# --------------------------------------------------------------------------


def parse_env_file(text: str) -> dict[str, str]:
    """Parse a dotenv file as the renderer writes it and as developers edit it."""

    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            quote = value[0]
            value = value[1:-1].replace("\\" + quote, quote)
        if name:
            values[name] = value
    return values


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def fingerprint_env(values: dict[str, str], salt: str) -> dict[str, str]:
    return {name: _digest(salt, name, value) for name, value in values.items()}


def fingerprint_files(root: Path, paths: Sequence[str]) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for relative in paths:
        target = root / relative
        if target.is_file():
            fingerprints[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        else:
            fingerprints[relative] = MISSING_FILE
    return fingerprints


def fingerprint_services(services: dict[str, Any]) -> dict[str, str]:
    return {
        name: hashlib.sha256(
            json.dumps(definition, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        for name, definition in services.items()
    }


@dataclass(frozen=True)
class MapDiff:
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def describe(self) -> str:
        parts = []
        if self.added:
            parts.append("added " + ", ".join(self.added))
        if self.removed:
            parts.append("removed " + ", ".join(self.removed))
        if self.changed:
            parts.append("changed " + ", ".join(self.changed))
        return "; ".join(parts)


def diff_maps(old: dict[str, str], new: dict[str, str]) -> MapDiff:
    return MapDiff(
        added=tuple(sorted(set(new) - set(old))),
        removed=tuple(sorted(set(old) - set(new))),
        changed=tuple(sorted(name for name in set(old) & set(new) if old[name] != new[name])),
    )


# --------------------------------------------------------------------------
# Snapshot state
# --------------------------------------------------------------------------


@dataclass
class Snapshot:
    salt: str
    env: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    services: dict[str, str] = field(default_factory=dict)
    images: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": STATE_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "salt": self.salt,
                "env": self.env,
                "files": self.files,
                "services": self.services,
                "images": self.images,
            },
            indent=2,
            sort_keys=True,
        )


def load_snapshot(state_dir: Path) -> Snapshot | None:
    path = state_dir / STATE_FILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    if data.get("version") != STATE_VERSION or not isinstance(data.get("salt"), str):
        return None
    return Snapshot(
        salt=data["salt"],
        env=dict(data.get("env", {})),
        files=dict(data.get("files", {})),
        services=dict(data.get("services", {})),
        images=dict(data.get("images", {})),
    )


def save_snapshot(state_dir: Path, snapshot: Snapshot) -> None:
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    descriptor, temporary = tempfile.mkstemp(dir=state_dir, prefix=".snapshot-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(snapshot.to_json())
        os.chmod(temporary, 0o600)
        os.replace(temporary, state_dir / STATE_FILE_NAME)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ContainerState:
    service: str
    image_id: str
    environment: dict[str, str]
    # Epoch seconds when the container last started; None when unknown.
    started_at: float | None = None


def parse_started_at(value: str | None) -> float | None:
    """Parse Docker's RFC 3339 ``State.StartedAt`` (nanosecond precision) to epoch seconds."""

    if not value or value.startswith("0001-"):
        return None
    text = value.rstrip("Z")
    whole, _, fraction = text.partition(".")
    try:
        moment = datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    microseconds = int((fraction[:6] or "0").ljust(6, "0")) if fraction.isdigit() else 0
    return moment.timestamp() + microseconds / 1_000_000


def newest_mtime(root: Path, paths: Sequence[str]) -> float | None:
    """Return the newest modification time among files, or files under directories."""

    newest: float | None = None
    for relative in paths:
        target = root / relative
        if target.is_dir():
            candidates = [item for item in target.rglob("*") if item.is_file()]
        elif target.is_file():
            candidates = [target]
        else:
            candidates = []
        for item in candidates:
            modified = item.stat().st_mtime
            if newest is None or modified > newest:
                newest = modified
    return newest


@dataclass
class Plan:
    baseline: bool
    reasons: list[str] = field(default_factory=list)
    recreate: list[str] = field(default_factory=list)

    def add(self, service: str, reason: str) -> None:
        if service not in self.recreate:
            self.recreate.append(service)
        if reason not in self.reasons:
            self.reasons.append(reason)


def configured_environment(definition: dict[str, Any]) -> dict[str, str]:
    """Return the variables Compose will set, skipping pass-through (null) ones."""

    environment = definition.get("environment") or {}
    if isinstance(environment, list):
        pairs = [item.partition("=") for item in environment]
        environment = {name: value for name, sep, value in pairs if sep}
    # ``docker compose config`` escapes a literal dollar sign as ``$$``.
    return {
        str(name): str(value).replace("$$", "$")
        for name, value in environment.items()
        if value is not None
    }


def build_services(services: dict[str, Any]) -> list[str]:
    return sorted(name for name, definition in services.items() if "build" in definition)


def find_drift(
    services: dict[str, Any],
    containers: dict[str, list[ContainerState]],
    image_ids: dict[str, str],
    config_mtimes: dict[str, float] | None = None,
) -> dict[str, list[str]]:
    """Map each service to why its running containers differ from what is configured.

    ``config_mtimes`` maps a service to the newest modification time of the config
    files it copies or reads at startup (for example nginx's ``default.conf`` copy).
    A container that started before that time runs a stale copy.
    """

    config_mtimes = config_mtimes or {}
    drift: dict[str, list[str]] = {}
    for name, definition in services.items():
        wanted = configured_environment(definition)
        wanted_image = image_ids.get(name)
        config_changed_at = config_mtimes.get(name)
        for container in containers.get(name, []):
            problems: list[str] = []
            if wanted_image and container.image_id != wanted_image:
                problems.append("running a stale image")
            if (
                config_changed_at is not None
                and container.started_at is not None
                and container.started_at < config_changed_at
            ):
                problems.append("running stale config files (changed after it started)")
            missing = sorted(key for key in wanted if key not in container.environment)
            if missing:
                problems.append("missing environment " + ", ".join(missing))
            differing = sorted(
                key
                for key in wanted
                if key in container.environment and container.environment[key] != wanted[key]
            )
            if differing:
                problems.append("outdated environment " + ", ".join(differing))
            for problem in problems:
                reasons = drift.setdefault(name, [])
                if problem not in reasons:
                    reasons.append(problem)
    return drift


def make_plan(
    previous: Snapshot | None,
    current: Snapshot,
    services: dict[str, Any],
    drift: dict[str, list[str]],
) -> Plan:
    plan = Plan(baseline=previous is None)

    if previous is not None:
        env_diff = diff_maps(previous.env, current.env)
        if env_diff:
            plan.reasons.append("environment variables " + env_diff.describe())
        file_diff = diff_maps(previous.files, current.files)
        if file_diff:
            plan.reasons.append("dependency files " + file_diff.describe())

        for name in sorted(diff_maps(previous.services, current.services).added):
            plan.add(name, f"new service {name}")
        for name in sorted(diff_maps(previous.services, current.services).changed):
            plan.add(name, f"configuration of {name} changed")

        for service in build_services(services):
            old_image = previous.images.get(service)
            new_image = current.images.get(service)
            if old_image and new_image and old_image != new_image:
                plan.add(service, "backend image was rebuilt")

    for service, problems in sorted(drift.items()):
        for problem in problems:
            plan.add(service, f"{service}: {problem}")

    return plan


# --------------------------------------------------------------------------
# Docker access
# --------------------------------------------------------------------------


def run_command(command: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            list(command),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        stderr = (error.stderr or "").strip()
        raise DeployError(
            f"{' '.join(command[:4])} ... failed with exit code {error.returncode}: "
            f"{stderr[-800:]}"
        ) from error
    return result.stdout


def run_streaming(command: Sequence[str]) -> None:
    """Run a long command, streaming its output to the deploy log."""

    result = subprocess.run(list(command))
    if result.returncode != 0:
        raise DeployError(f"{' '.join(command[:4])} ... failed with exit code {result.returncode}")


class Compose:
    def __init__(
        self,
        env_file: Path,
        compose_files: Sequence[Path],
        *,
        run: Runner = run_command,
        stream: Callable[[Sequence[str]], None] = run_streaming,
    ) -> None:
        self._base = ["docker", "compose", "--env-file", str(env_file)]
        for compose_file in compose_files:
            self._base += ["-f", str(compose_file)]
        self._run = run
        self._stream = stream

    def config(self) -> dict[str, Any]:
        output = self._run([*self._base, "config", "--format", "json"])
        try:
            return json.loads(output)
        except ValueError as error:
            raise DeployError("docker compose config did not return JSON") from error

    def build(self) -> None:
        self._stream([*self._base, "build"])

    def up(self, services: Sequence[str], *, force_recreate: bool, wait_timeout: int) -> None:
        command = [*self._base, "up", "-d", "--wait", "--wait-timeout", str(wait_timeout)]
        if force_recreate:
            command += ["--no-deps", "--force-recreate"]
        command += list(services)
        self._stream(command)

    def container_ids(self, service: str) -> list[str]:
        output = self._run([*self._base, "ps", "-q", service])
        return [line.strip() for line in output.splitlines() if line.strip()]

    def ps(self) -> str:
        return self._run([*self._base, "ps", "-a"])


def image_id(run: Runner, image: str) -> str | None:
    try:
        return run(["docker", "image", "inspect", image, "--format", "{{.Id}}"]).strip() or None
    except DeployError:
        return None


def inspect_containers(
    compose: Compose, run: Runner, services: dict[str, Any]
) -> dict[str, list[ContainerState]]:
    containers: dict[str, list[ContainerState]] = {}
    for service in services:
        for container_id in compose.container_ids(service):
            raw = run(["docker", "inspect", container_id])
            details = json.loads(raw)[0]
            environment = {}
            for item in details.get("Config", {}).get("Env") or []:
                name, _, value = item.partition("=")
                environment[name] = value
            containers.setdefault(service, []).append(
                ContainerState(
                    service=service,
                    image_id=details.get("Image", ""),
                    environment=environment,
                    started_at=parse_started_at(details.get("State", {}).get("StartedAt")),
                )
            )
    return containers


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def resolve_images(run: Runner, services: dict[str, Any]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for name, definition in services.items():
        image = definition.get("image")
        if not image:
            continue
        found = image_id(run, image)
        if found:
            resolved[name] = found
    return resolved


def watched_config_mtimes(
    root: Path, service_files: dict[str, list[str]], services: dict[str, Any]
) -> dict[str, float]:
    mtimes: dict[str, float] = {}
    for service, paths in service_files.items():
        if service not in services:
            raise DeployError(f"--service-file names unknown service {service!r}.")
        newest = newest_mtime(root, paths)
        if newest is not None:
            mtimes[service] = newest
    return mtimes


def parse_service_files(entries: Sequence[str]) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for entry in entries:
        service, separator, path = entry.partition("=")
        if not separator or not service or not path:
            raise DeployError(f"--service-file expects SERVICE=PATH, got {entry!r}.")
        parsed.setdefault(service, []).append(path)
    return parsed


def deploy(
    *,
    root: Path,
    env_file: Path,
    compose_files: Sequence[Path],
    state_dir: Path,
    dependency_files: Sequence[str],
    dry_run: bool,
    skip_build: bool,
    wait_timeout: int,
    service_files: dict[str, list[str]] | None = None,
    run: Runner = run_command,
    compose: Compose | None = None,
) -> int:
    compose = compose or Compose(env_file, compose_files, run=run)

    # Fails here, before anything is touched, if a required variable is unset.
    services: dict[str, Any] = compose.config().get("services", {})
    if not services:
        raise DeployError("The Compose model has no services.")
    log(f"Compose model is valid: {len(services)} services.")

    if not skip_build and not dry_run:
        log("Building images (cached layers are reused).")
        compose.build()

    previous = load_snapshot(state_dir)
    salt = previous.salt if previous else secrets.token_hex(16)
    env_values = parse_env_file(env_file.read_text(encoding="utf-8"))
    image_ids = resolve_images(run, services)
    current = Snapshot(
        salt=salt,
        env=fingerprint_env(env_values, salt),
        files=fingerprint_files(root, dependency_files),
        services=fingerprint_services(services),
        images=image_ids,
    )

    config_mtimes = watched_config_mtimes(root, service_files or {}, services)
    drift = find_drift(
        services, inspect_containers(compose, run, services), image_ids, config_mtimes
    )
    plan = make_plan(previous, current, services, drift)

    if previous is None:
        log("No earlier deploy record: recording a baseline after this run.")
    for reason in plan.reasons:
        log(f"Change detected: {reason}.")
    if not plan.reasons and previous is not None:
        log("No dependency, environment or configuration changes since the last deploy.")

    if dry_run:
        if plan.recreate:
            log("Would force-recreate: " + ", ".join(plan.recreate))
        log("Dry run: nothing was changed.")
        return 0

    if plan.recreate:
        log("Force-recreating: " + ", ".join(plan.recreate))
        compose.up(plan.recreate, force_recreate=True, wait_timeout=wait_timeout)

    log("Bringing up the full stack.")
    compose.up([], force_recreate=False, wait_timeout=wait_timeout)

    # Re-resolve images in case the build produced new IDs after the plan was made.
    image_ids = resolve_images(run, services)
    remaining = find_drift(
        services, inspect_containers(compose, run, services), image_ids, config_mtimes
    )
    if remaining:
        for service, problems in sorted(remaining.items()):
            for problem in problems:
                log(f"Verification failed: {service} is {problem}.")
        log("Compose state:")
        print(compose.ps(), flush=True)
        return 1

    current.images = image_ids
    save_snapshot(state_dir, current)
    log("Verified: every service runs the current image and configured environment.")
    return 0


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument(
        "-f",
        "--compose-file",
        action="append",
        required=True,
        type=Path,
        dest="compose_files",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(os.environ.get("TRACE_DEPLOY_STATE_DIR", "/var/lib/trace/deploy-state")),
    )
    parser.add_argument(
        "--dependency-file",
        action="append",
        dest="dependency_files",
        help="Repeatable. Defaults to the backend lockfile, pyproject and Dockerfile.",
    )
    parser.add_argument(
        "--service-file",
        action="append",
        default=[],
        metavar="SERVICE=PATH",
        help=(
            "Repeatable. A file or directory a service copies or reads at startup, "
            "for example nginx=config/nginx. The service is recreated when these "
            "files changed after its container started."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--wait-timeout", type=int, default=300)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    if not arguments.env_file.is_file():
        print(f"Environment file not found: {arguments.env_file}", file=sys.stderr)
        return 2
    try:
        return deploy(
            root=Path.cwd(),
            env_file=arguments.env_file,
            compose_files=arguments.compose_files,
            state_dir=arguments.state_dir,
            dependency_files=arguments.dependency_files or DEFAULT_DEPENDENCY_FILES,
            dry_run=arguments.dry_run,
            skip_build=arguments.skip_build,
            wait_timeout=arguments.wait_timeout,
            service_files=parse_service_files(arguments.service_file),
        )
    except DeployError as error:
        print(f"[deploy] ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
