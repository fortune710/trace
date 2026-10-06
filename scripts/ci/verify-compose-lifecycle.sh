#!/usr/bin/env bash

set -euo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
env_file="${1:?Usage: verify-compose-lifecycle.sh ENV_FILE}"
project_name="${COMPOSE_PROJECT_NAME:-trace-lifecycle}"
compose=(docker compose --project-name "$project_name" --env-file "$env_file" -f "$root_dir/compose.yaml" -f "$root_dir/compose.e2e.yaml" --profile e2e)

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" up --build --wait backend
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:18000/health/ready >/dev/null

"${compose[@]}" stop redis
for _ in {1..20}; do
  if [[ "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18000/health/ready)" == "503" ]]; then
    break
  fi
  sleep 1
done
[[ "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18000/health/ready)" == "503" ]]

"${compose[@]}" start redis
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:18000/health/ready >/dev/null
"${compose[@]}" restart backend
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:18000/health/ready >/dev/null
