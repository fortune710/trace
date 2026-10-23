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

For rotation within the same Transit key, use the Transit `rewrap` operation. Vault receives the ciphertext and authenticated context, returns ciphertext under the active key version, and the application updates only the encrypted metadata. The application does not decrypt the credential during this operation. Rewrap jobs must be owner/context-bound, idempotent, retryable, and verify that the new ciphertext can be decrypted before marking the record complete.

## Credential re-encryption runbook

The migration creates a separate `trace_credential_maintenance` database role and durable run tables. It is the only runtime role allowed to enumerate and update credential ciphertext for rotation; the API remains connected as `trace_app`. Supply its URL as `MAINTENANCE_DATABASE_URL` and keep `TRACE_CREDENTIAL_MAINTENANCE_PASSWORD` available to the migration container, but never expose either value to the API response surface.

Run a rotation from the dedicated Compose maintenance profile, or from an equivalent one-off production job:

```bash
docker compose --profile maintenance run --rm credential-maintenance \
  --batch-size 100 --max-attempts 5
```

The maintenance container receives only the encryption configuration, Vault runtime token, and `MAINTENANCE_DATABASE_URL`; it does not receive the API database URL or the general authentication signing secrets.

The command discovers the configured active key version. `--target-key-version` may be used as an explicit assertion, but it must equal the active version. For local AES-GCM keys, each credential is decrypted and re-encrypted in process using the active key and the retired verification keys. For Vault Transit, each credential uses Transit `rewrap`; plaintext is not returned to the application. The job stores only credential IDs, ciphertext metadata, bounded counters, and the generic error code `credential_rewrap_failed`.

Each credential is checkpointed in `private.credential_reencryption_items`, while `private.credential_reencryption_runs` stores progress and the last ordered credential ID. A failed or interrupted run can be resumed without starting over:

```bash
docker compose --profile maintenance run --rm credential-maintenance \
  --run-id <run-id> --max-attempts 5
```

Retries use bounded backoff and `FOR UPDATE SKIP LOCKED`, so multiple maintenance processes do not rewrap the same item concurrently. The job emits only run IDs, statuses, counts, and generic failure metrics. It never logs credential payloads, access tokens, ciphertext, Vault tokens, or exception text.

Provider reads also perform best-effort conditional read repair when the stored key version is older than the configured active version. The provider call continues using the old ciphertext while that retired key remains valid; the batch job remains the authoritative completion and retirement check. Retire an old local key or Vault version only after the run is complete, failures have been resolved, and the end-to-end decrypt test has passed.
