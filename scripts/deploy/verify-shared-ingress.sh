#!/usr/bin/env bash

set -euo pipefail

readonly CONNECT_TIMEOUT_SECONDS=5
readonly REQUEST_TIMEOUT_SECONDS=15
readonly API_HOSTS=(
  traceapi.fortunealebiosu.dev
  keepsafeapi.fortunealebiosu.dev
)

check_https() {
  local host="$1"

  curl \
    --fail \
    --silent \
    --show-error \
    --connect-timeout "$CONNECT_TIMEOUT_SECONDS" \
    --max-time "$REQUEST_TIMEOUT_SECONDS" \
    --proto '=https' \
    --output /dev/null \
    "https://${host}/health"
}

check_http_redirect() {
  local host="$1"
  local status

  status="$(
    curl \
      --silent \
      --show-error \
      --connect-timeout "$CONNECT_TIMEOUT_SECONDS" \
      --max-time "$REQUEST_TIMEOUT_SECONDS" \
      --proto '=http,https' \
      --output /dev/null \
      --write-out '%{http_code}' \
      "http://${host}/health"
  )"

  case "$status" in
    301 | 302 | 307 | 308) ;;
    *)
      echo "Expected HTTP redirect from ${host}, received status ${status}" >&2
      return 1
      ;;
  esac

  curl \
    --fail \
    --silent \
    --show-error \
    --location \
    --connect-timeout "$CONNECT_TIMEOUT_SECONDS" \
    --max-time "$REQUEST_TIMEOUT_SECONDS" \
    --proto '=http,https' \
    --proto-redir '=https' \
    --output /dev/null \
    "http://${host}/health"
}

for host in "${API_HOSTS[@]}"; do
  echo "Checking HTTPS routing for ${host}"
  check_https "$host"

  echo "Checking HTTP-to-HTTPS routing for ${host}"
  check_http_redirect "$host"
done
