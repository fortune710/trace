# Trace backend

Install the locked dependencies before starting the backend directly:

```bash
uv sync --locked
```

Then run:

```bash
./start.sh
```

The startup script runs only the already-locked dependency set. It does not download packages or update `uv.lock`. When Compose uses Vault Transit, it reads the restricted runtime token from its read-only `/run/vault` mount; direct runs must set `AUTH_VAULT_TOKEN` themselves.

## Authentication foundations

Authentication routes will use a 60-minute Ed25519 JWT access token, a seven-day rotating refresh token, and Argon2id password hashes. Provider credentials use Vault Transit by default; see [the Vault runbook](../docs/vault-transit.md). Generate the required local `AUTH_*` values and `VAULT_DEV_ROOT_TOKEN_ID` in the repository `.env` file before exercising Phase 4 routes. The backend validates the security configuration when authentication services are constructed; it never generates secrets during startup.

Email verification and recovery work is delivered by the separate `email-worker` Compose service. It connects to the internal RabbitMQ service with `AUTH_RABBITMQ_URL`; only encrypted database job records retain delivery payloads. Configure `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `AUTH_EMAIL_FROM`, and the SMTP settings in `.env`. The durable queue, retry, and dead-letter contract is documented in [Queueing Convention](../docs/queueing.md).

The shared Redis token-bucket limiter is registered in `auth.rate_limit.AUTH_RATE_LIMIT_POLICIES`. Authentication routes will apply its named policies through the same utility rather than defining per-route counters.

## Database migrations

Run migrations through Docker Compose from the repository root:

```bash
./scripts/migrate.sh
```

The command waits for PostgreSQL, then runs Alembic in the dedicated migration container. FastAPI startup never applies migrations automatically.

## Test database migrations

Run the isolated test-database migration from the repository root:

```bash
./scripts/migrate-test.sh
```

This starts only the `postgres-test` service in the Compose `test` profile and migrates `trace_test`. Integration tests must use `TEST_DATABASE_URL`, never the development `DATABASE_URL`.
