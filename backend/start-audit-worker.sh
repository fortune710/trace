#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$SCRIPT_DIR"

exec uv run --offline --no-sync --locked python -m workers.audit
