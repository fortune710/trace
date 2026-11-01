import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github/scripts/check-production-env-wiring.py"
SPEC = importlib.util.spec_from_file_location("check_production_env_wiring", SCRIPT)
wiring = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wiring
SPEC.loader.exec_module(wiring)

RENDERER = """
REQUIRED = ("DATABASE_URL",)
OPTIONAL = ("TAVILY_API_KEY",)
FIXED = {"AUTH_ENVIRONMENT": "production"}
"""

COMPOSE = """
services:
  backend:
    environment:
      DATABASE_URL: ${DATABASE_URL:?Set DATABASE_URL}
      TAVILY_API_KEY: ${TAVILY_API_KEY:-}
      # ${IGNORED_IN_COMMENT}
      LITERAL: $${NOT_A_VARIABLE}
"""

WORKFLOW = """
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}
"""


class WiringCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path

    def run_check(self, *, renderer=RENDERER, compose=COMPOSE, workflows=(WORKFLOW, WORKFLOW), external=None):
        return wiring.check(
            renderer=self.write("render.py", renderer),
            compose=self.write("compose.yaml", compose),
            workflows=tuple(
                self.write(f"workflow-{index}.yml", text) for index, text in enumerate(workflows)
            ),
            external=external if external is not None else {},
        )

    def test_consistent_setup_passes(self):
        self.assertEqual(self.run_check(), [])

    def test_compose_variable_missing_from_renderer_is_reported(self):
        compose = COMPOSE + "      NEW: ${BRAND_NEW_SETTING:-x}\n"
        problems = self.run_check(compose=compose)
        self.assertEqual(len(problems), 1)
        self.assertIn("BRAND_NEW_SETTING", problems[0])
        self.assertIn("render.py", problems[0])

    def test_escaped_dollar_and_comments_are_not_variables(self):
        self.assertEqual(wiring.compose_variables(self.write("c.yaml", COMPOSE)), {"DATABASE_URL", "TAVILY_API_KEY"})

    def test_workflow_missing_a_secret_is_reported(self):
        trimmed = WORKFLOW.replace("          TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}\n", "")
        problems = self.run_check(workflows=(WORKFLOW, trimmed))
        self.assertEqual(len(problems), 1)
        self.assertIn("workflow-1.yml", problems[0])
        self.assertIn("TAVILY_API_KEY", problems[0])

    def test_secret_mapped_to_a_different_name_is_reported(self):
        renamed = WORKFLOW.replace("secrets.TAVILY_API_KEY", "secrets.OTHER_KEY")
        problems = self.run_check(workflows=(renamed, WORKFLOW))
        self.assertEqual(len(problems), 1)
        self.assertIn("secrets.OTHER_KEY", problems[0])

    def test_fixed_value_passed_from_a_secret_is_reported(self):
        extra = WORKFLOW + "          AUTH_ENVIRONMENT: ${{ secrets.AUTH_ENVIRONMENT }}\n"
        problems = self.run_check(workflows=(extra, WORKFLOW))
        self.assertEqual(len(problems), 1)
        self.assertIn("fixed value", problems[0])

    def test_documented_external_variable_is_allowed(self):
        compose = COMPOSE + "      EXTRA: ${HOST_ONLY_SETTING:-x}\n"
        problems = self.run_check(compose=compose, external={"HOST_ONLY_SETTING": "set on the host"})
        self.assertEqual(problems, [])

    def test_variable_listed_as_required_and_optional_is_reported(self):
        renderer = RENDERER.replace('OPTIONAL = ("TAVILY_API_KEY",)', 'OPTIONAL = ("TAVILY_API_KEY", "DATABASE_URL")')
        problems = self.run_check(renderer=renderer)
        self.assertEqual(len(problems), 1)
        self.assertIn("both REQUIRED and OPTIONAL", problems[0])


class RepositoryWiringTests(unittest.TestCase):
    def test_repository_files_are_fully_wired(self):
        self.assertEqual(wiring.check(), [])


if __name__ == "__main__":
    unittest.main()
