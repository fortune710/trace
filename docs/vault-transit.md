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

## Single-VPS production Compose

`compose.production.yaml` runs the same official Vault image in standard server mode with persistent Raft storage. It has no published host port and is reachable only by the backend and Vault-using workers on the internal `secrets` network. The application accepts production HTTP only at the exact address `http://vault:8200`; any other HTTP Vault address remains invalid. This is a conscious single-host tradeoff, not an end-to-end encrypted connection: a compromised Docker host or container on that network could observe Vault traffic, including plaintext credentials and the workload token. HashiCorp recommends TLS for production. Do not expose port 8200 or connect untrusted containers to `secrets`.

The Vault data volume must survive upgrades and restarts. Never use `docker compose down -v` against this stack. Keep encrypted, tested backups of Vault's Raft data off the VPS; losing the Transit keys makes stored provider credentials unreadable. A single Vault node has no high availability and must be manually unsealed after a restart.

The first deployment workflow will create `.env.production` and start Vault, then stop with an operator-setup message while Vault is uninitialized or sealed. On the VPS, from `/root/trace`, initialize it exactly once:

```bash
docker compose --env-file .env.production -f compose.production.yaml exec vault vault operator init
docker compose --env-file .env.production -f compose.production.yaml exec vault vault operator unseal
```

Store the initialization output (unseal shares and initial root token) securely **outside** the VPS, GitHub Actions, and this repository; never paste it into CI logs or a chat. Supply the required unseal shares interactively until Vault is unsealed. On every later Vault restart, repeat only `vault operator unseal` with the existing shares. Never run `vault operator init` against an initialized volume.

For the one-time Transit setup, log in interactively with the initial root token, then run:

```bash
docker compose --env-file .env.production -f compose.production.yaml exec vault vault login -no-print
docker compose --env-file .env.production -f compose.production.yaml exec vault vault secrets enable -path=transit transit
docker compose --env-file .env.production -f compose.production.yaml exec vault vault write transit/keys/trace-provider-credentials type=aes256-gcm96 exportable=false allow_plaintext_backup=false
docker compose --env-file .env.production -f compose.production.yaml exec vault vault write transit/keys/trace-email-delivery type=aes256-gcm96 exportable=false allow_plaintext_backup=false
docker compose --env-file .env.production -f compose.production.yaml exec -T vault vault policy write trace-backend - < config/vault-backend-policy.hcl
```

Create a renewable, restricted application token in the operator-controlled file. The backend image runs as UID 10001, so the file must be readable by that UID without becoming world-readable:

```bash
umask 077
install -d -m 0700 production-secrets
docker compose --env-file .env.production -f compose.production.yaml exec -T vault vault token create -orphan -policy=trace-backend -period=24h -field=token > production-secrets/trace-backend-token
chown 10001:10001 production-secrets/trace-backend-token
chmod 0400 production-secrets/trace-backend-token
docker compose --env-file .env.production -f compose.production.yaml exec vault sh -c 'rm -f /home/vault/.vault-token'
```

The root token must never be mounted into the application. Rerun the failed deployment workflow after setup, and verify the backend can renew the restricted token. Before production use, configure Vault audit logging and test a Raft snapshot backup and restore. The token file and Vault data volume are not created by GitHub Actions.

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
