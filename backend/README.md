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

The shared Redis token-bucket limiter is registered in `auth.rate_limit.AUTH_RATE_LIMIT_POLICIES`. Authentication routes will apply its named policies through the same utility rather than defining per-route counters.

## Database migrations

Run migrations through Docker Compose from the repository root:

```bash
./scripts/migrate.sh
```

The command waits for PostgreSQL, then runs Alembic in the dedicated migration container. FastAPI startup never applies migrations automatically.
