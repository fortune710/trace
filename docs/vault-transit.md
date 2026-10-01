# Vault Transit

## Purpose

Vault Transit protects OAuth access and refresh tokens that Trace retains to call a provider later. The backend sends token plaintext and authenticated context to Vault over its private network. Vault returns ciphertext such as `vault:v1:...`; it retains the AES-256-GCM encryption key.

`private.credentials` records the ciphertext, the Vault key version, `encryption_provider=vault`, and `key_reference=transit/trace-provider-credentials`. It never stores the Vault token, Vault root token, or a Vault encryption key.

## Local Compose service

`compose.yaml` starts the pinned official Vault image in **development mode** on the internal `secrets` network. It has no host port. `vault-bootstrap` enables the Transit engine, creates the non-exportable `trace-provider-credentials` key, writes a policy limited to that key's `encrypt` and `decrypt` endpoints, and creates a restricted periodic backend token.

The backend receives that restricted token through a read-only runtime volume. It does not receive the development root token. The startup script reads only `/run/vault/trace-backend-token`, does not print it, and never includes it in a process argument. FastAPI renews the periodic token at the configured interval, and refuses to start if its initial renewal cannot complete.

Before starting the Compose stack, set a unique local value in `.env`:

```bash
VAULT_DEV_ROOT_TOKEN_ID=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

Then start the stack normally:

```bash
docker compose up --build --wait
```

Vault development mode is intentionally not persistent and must never be used on an internet-facing server. Restarting the Vault container invalidates ciphertext produced by that local instance. That is acceptable for local development because provider credentials must not be treated as durable there.

## Server deployment before HCP Vault

If Vault runs on a school-project server, deploy the same official image in standard server mode—not the Compose development-mode service. Require all of the following before using it with real provider credentials:

- TLS from FastAPI to Vault, with certificate verification.
- Persistent integrated Raft storage and encrypted backups.
- Vault initialization/unseal keys kept outside the server; preferably configure auto-unseal using an external KMS/HSM.
- A firewall or private network that allows only the FastAPI workload to reach port 8200.
- A non-root Vault policy restricted to `transit/encrypt/trace-provider-credentials` and `transit/decrypt/trace-provider-credentials`.
- Renewable workload authentication and audit logging; do not give FastAPI a root token.
- A tested backup, restore, and rotation procedure.

Set `AUTH_ENVIRONMENT=production`, `AUTH_CREDENTIAL_ENCRYPTION_PROVIDER=vault`, an HTTPS `AUTH_VAULT_ADDR`, and a restricted `AUTH_VAULT_TOKEN` (or the equivalent workload-issued token). Startup rejects a non-HTTPS Vault address in production.

## Moving to HCP Vault

The backend uses the Vault Transit HTTP API, so the application transition is configuration-led: provision the same Transit mount/key and policy in HCP Vault, then change the Vault address and workload authentication.

Existing ciphertext cannot be read by a new Transit key. Migrate it with a controlled dual-provider job: decrypt each credential using the old Vault, encrypt it with HCP Vault, update `encryption_provider`, `key_reference`, and `key_version`, verify reads, then revoke the old backend policy. Do not export a production Transit key merely to avoid this migration.
