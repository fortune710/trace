#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd -- "$ROOT_DIR"

docker compose --profile test up -d --wait postgres-test
docker compose --profile test run --rm --build --no-deps migrate-test
