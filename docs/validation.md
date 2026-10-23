# Validation and CI

Phase 5 validation runs only when a pull request targeting `main` is opened. It does not run on pushes, merges, reopened pull requests, schedules, or deployment events.

## Local checks

Run backend quality checks from the repository root:

```bash
cd backend
uv sync --all-groups --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Run frontend checks:

```bash
cd frontend
bun install --frozen-lockfile
bun run lint
bun run test
bun run build
```

## Isolated database migration check

The `test` Compose profile uses `postgres-test` and `TEST_DATABASE_URL`; it never shares the development database or volume.

```bash
./scripts/migrate-test.sh
docker compose --profile test run --rm --build backend-tests
docker compose --profile test down --volumes --remove-orphans
```

## End-to-end authentication check

The E2E overlay starts disposable PostgreSQL, Redis, RabbitMQ, Mailpit, the backend, email worker, and a local OAuth stub. GitHub and Google are never contacted.

```bash
scripts/ci/write-compose-env.sh .ci.env
docker compose --project-name trace-e2e --env-file .ci.env -f compose.yaml -f compose.e2e.yaml --profile e2e up --build --wait backend email-worker
E2E_AUTH_STACK=1 bun --cwd frontend run test:e2e
docker compose --project-name trace-e2e --env-file .ci.env -f compose.yaml -f compose.e2e.yaml --profile e2e down --volumes --remove-orphans
rm -f .ci.env
```

The generated `.ci.env` has deterministic, non-production values and is ignored by Git. Do not use it outside local validation or CI.

## Lifecycle and security checks

The lifecycle script verifies clean startup, readiness failure during a Redis outage, Redis recovery, and a backend restart:

```bash
scripts/ci/write-compose-env.sh .ci.env
scripts/ci/verify-compose-lifecycle.sh .ci.env
rm -f .ci.env
```

The CI security job runs dependency audits, Gitleaks, Trivy filesystem/config scanning, and a Trivy scan of the built backend image. A high- or critical-severity finding fails the validation workflow.
