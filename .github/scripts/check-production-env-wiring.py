#!/usr/bin/env python3
"""Check that every production environment variable is wired end to end.

A variable used by ``compose.production.yaml`` only reaches a container if it is:

1. listed in ``render-production-env.py`` (REQUIRED, OPTIONAL or FIXED), and
2. passed from a same-named GitHub Actions secret in the "Prepare production
   environment" step of both ``production-deploy.yml`` and
   ``production-migrations.yml``.

Missing any link fails silently at deploy time: Compose substitutes an empty
default and the service starts without the setting.  This check turns that into
a merge-check failure.  It reads files as text and never executes them.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / ".github/scripts/render-production-env.py"
COMPOSE = ROOT / "compose.production.yaml"
WORKFLOWS = (
    ROOT / ".github/workflows/production-deploy.yml",
    ROOT / ".github/workflows/production-migrations.yml",
)

# Variables Compose reads that are intentionally not supplied through the
# production env file.  Add a name here only with a comment saying where it
# comes from instead.
EXTERNAL_VARIABLES: dict[str, str] = {
    "REMEDIATION_PR_RABBITMQ_URL": "defaults to AUTH_RABBITMQ_URL in compose.production.yaml",
    "REMEDIATION_PR_MAX_ATTEMPTS": "uses the compose default; not configurable from Actions",
    "REMEDIATION_PR_POLL_SECONDS": "uses the compose default; not configurable from Actions",
    "REMEDIATION_PR_PROCESSING_TIMEOUT_SECONDS": "uses the compose default; not configurable from Actions",
    "REMEDIATION_PR_RETRY_BASE_SECONDS": "uses the compose default; not configurable from Actions",
    "REMEDIATION_PR_RETRY_MAX_SECONDS": "uses the compose default; not configurable from Actions",
    "VAULT_RUNTIME_TOKEN_FILE": "host path set by the operator; defaults to ./production-secrets/trace-backend-token",
}

COMPOSE_REFERENCE = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)")
SECRET_MAPPING = re.compile(
    r"^\s+([A-Za-z_][A-Za-z0-9_]*):\s*\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}\s*$",
    re.MULTILINE,
)


def read_renderer(path: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (REQUIRED, OPTIONAL, FIXED) names by parsing the file's AST."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"REQUIRED", "OPTIONAL", "FIXED"}:
            continue
        if isinstance(node.value, ast.Dict):
            keys = node.value.keys
        elif isinstance(node.value, (ast.Tuple, ast.List)):
            keys = node.value.elts
        else:
            continue
        found[target.id] = {
            key.value
            for key in keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    missing = {"REQUIRED", "OPTIONAL", "FIXED"} - set(found)
    if missing:
        raise SystemExit(f"{path.name}: could not read {', '.join(sorted(missing))}.")
    return found["REQUIRED"], found["OPTIONAL"], found["FIXED"]


def compose_variables(path: Path) -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        names.update(COMPOSE_REFERENCE.findall(line))
    return names


def workflow_secret_mappings(path: Path) -> dict[str, str]:
    return dict(SECRET_MAPPING.findall(path.read_text(encoding="utf-8")))


def check(
    *,
    renderer: Path = RENDERER,
    compose: Path = COMPOSE,
    workflows: tuple[Path, ...] = WORKFLOWS,
    external: dict[str, str] | None = None,
) -> list[str]:
    external = EXTERNAL_VARIABLES if external is None else external
    required, optional, fixed = read_renderer(renderer)
    supplied = required | optional | fixed
    secret_backed = required | optional
    problems: list[str] = []

    for name in sorted(compose_variables(compose) - supplied - set(external)):
        problems.append(
            f"{compose.name} uses ${{{name}}} but {renderer.name} does not render it. "
            f"Add it to REQUIRED or OPTIONAL (or FIXED if the value is constant)."
        )

    for name in sorted(required & optional):
        problems.append(f"{renderer.name} lists {name} in both REQUIRED and OPTIONAL.")

    for workflow in workflows:
        mappings = workflow_secret_mappings(workflow)
        for name in sorted(secret_backed - set(mappings)):
            problems.append(
                f"{workflow.name} does not pass {name} to the renderer. "
                f"Add `{name}: ${{{{ secrets.{name} }}}}` to its env block."
            )
        for name, secret in sorted(mappings.items()):
            if name in secret_backed and secret != name:
                problems.append(
                    f"{workflow.name} maps {name} to secrets.{secret}; "
                    f"use secrets.{name} so every workflow reads the same secret."
                )
        for name in sorted(set(mappings) & fixed):
            problems.append(
                f"{workflow.name} passes {name}, but {renderer.name} sets it as a fixed value."
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("Production environment wiring is incomplete:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("Production environment wiring is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
