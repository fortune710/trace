#!/bin/sh

# This runs only in the local Compose Vault development service. It accepts no
# caller-controlled shell fragments: mount and key names are validated before
# becoming Vault API paths, and all values are passed as quoted arguments.
set -eu
umask 077

: "${VAULT_ADDR:?VAULT_ADDR is required}"
: "${VAULT_TOKEN:?VAULT_TOKEN is required}"
: "${VAULT_TRANSIT_MOUNT:?VAULT_TRANSIT_MOUNT is required}"
: "${VAULT_TRANSIT_KEY:?VAULT_TRANSIT_KEY is required}"
: "${VAULT_BACKEND_TOKEN_FILE:?VAULT_BACKEND_TOKEN_FILE is required}"

validate_name() {
  case "$1" in
    '' | *[!A-Za-z0-9_-]*)
      echo "Vault bootstrap received an invalid Transit name" >&2
      exit 1
      ;;
  esac
}

validate_name "$VAULT_TRANSIT_MOUNT"
validate_name "$VAULT_TRANSIT_KEY"

if ! vault read "sys/mounts/$VAULT_TRANSIT_MOUNT" >/dev/null 2>&1; then
  vault secrets enable -path="$VAULT_TRANSIT_MOUNT" transit
fi

if ! vault read "$VAULT_TRANSIT_MOUNT/keys/$VAULT_TRANSIT_KEY" >/dev/null 2>&1; then
  vault write "$VAULT_TRANSIT_MOUNT/keys/$VAULT_TRANSIT_KEY" \
    type=aes256-gcm96 \
    exportable=false \
    allow_plaintext_backup=false
fi

vault policy write trace-backend - <<POLICY
path "$VAULT_TRANSIT_MOUNT/encrypt/$VAULT_TRANSIT_KEY" {
  capabilities = ["update"]
}

path "$VAULT_TRANSIT_MOUNT/decrypt/$VAULT_TRANSIT_KEY" {
  capabilities = ["update"]
}
POLICY

backend_token="$(vault token create -orphan -policy=trace-backend -period=24h -field=token)"
case "$backend_token" in
  '' | *[!A-Za-z0-9._-]*)
    echo "Vault bootstrap did not receive a valid backend token" >&2
    exit 1
    ;;
esac

mkdir -p /run/vault
# The volume contains only this non-secret filename. Its contents remain 0640 and
# readable only by the backend UID after the ownership handoff below.
chmod 0755 /run/vault
printf '%s\n' "$backend_token" >"$VAULT_BACKEND_TOKEN_FILE"
chmod 0640 "$VAULT_BACKEND_TOKEN_FILE"
chown 10001:10001 "$VAULT_BACKEND_TOKEN_FILE"
