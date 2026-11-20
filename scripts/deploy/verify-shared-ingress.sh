#!/usr/bin/env bash

set -euo pipefail

readonly CONNECT_TIMEOUT_SECONDS=5
readonly REQUEST_TIMEOUT_SECONDS=15
readonly API_HOSTS=(
  traceapi.fortunealebiosu.dev
)

check_https() {
  local host="$1"
  local status

  status="$(
    curl \
      --silent \
      --show-error \
      --connect-timeout "$CONNECT_TIMEOUT_SECONDS" \
      --max-time "$REQUEST_TIMEOUT_SECONDS" \
      --proto '=https' \
      --output /dev/null \
      --write-out '%{http_code}' \
      "https://${host}/"
  )"

  case "$status" in
    [1-5][0-9][0-9]) ;;
    *)
      echo "Expected HTTPS ingress at ${host} to return an HTTP status, received ${status}" >&2
      return 1
      ;;
  esac
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
      "http://${host}/"
  )"

  case "$status" in
    301 | 302 | 307 | 308) ;;
    *)
      echo "Expected HTTP redirect from ${host}, received status ${status}" >&2
      return 1
      ;;
  esac

}

for host in "${API_HOSTS[@]}"; do
  echo "Checking HTTPS routing for ${host}"
  check_https "$host"

  echo "Checking HTTP-to-HTTPS routing for ${host}"
  check_http_redirect "$host"
done
