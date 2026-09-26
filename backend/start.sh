#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$SCRIPT_DIR"

# Dependencies must be installed explicitly with `uv sync --locked`; startup never
# downloads packages or changes the lockfile.
exec uv run --offline --no-sync --locked uvicorn main:app --reload --host 0.0.0.0 --port 8000
