#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$SCRIPT_DIR"

if [[ "${AUTH_CREDENTIAL_ENCRYPTION_PROVIDER:-local}" == "vault" && -n "${AUTH_VAULT_TOKEN_FILE:-}" ]]; then
  case "$AUTH_VAULT_TOKEN_FILE" in
    /run/vault/*) ;;
    *)
      echo "AUTH_VAULT_TOKEN_FILE must be beneath /run/vault" >&2
      exit 1
      ;;
  esac
  [[ -r "$AUTH_VAULT_TOKEN_FILE" ]] || {
    echo "Vault runtime token is unavailable" >&2
    exit 1
  }
  IFS= read -r AUTH_VAULT_TOKEN <"$AUTH_VAULT_TOKEN_FILE"
  [[ -n "$AUTH_VAULT_TOKEN" ]] || {
    echo "Vault runtime token is unavailable" >&2
    exit 1
  }
  export AUTH_VAULT_TOKEN
fi

exec uv run --offline --no-sync --locked python -m workers.email
