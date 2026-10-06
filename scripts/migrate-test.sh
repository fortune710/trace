#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd -- "$ROOT_DIR"

COMPOSE_ARGS=()
if [[ -n "${COMPOSE_ENV_FILE:-}" ]]; then
  COMPOSE_ARGS+=(--env-file "$COMPOSE_ENV_FILE")
fi

docker compose "${COMPOSE_ARGS[@]}" --profile test up -d --wait postgres-test
docker compose "${COMPOSE_ARGS[@]}" --profile test run --rm --build --no-deps migrate-test
