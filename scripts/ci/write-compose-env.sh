#!/usr/bin/env bash

set -euo pipefail

target_file="${1:?Usage: write-compose-env.sh PATH}"
umask 077

cat >"$target_file" <<'EOF'
POSTGRES_PASSWORD=trace-ci-postgres-password
TRACE_APP_PASSWORD=trace-ci-app-password
MIGRATION_DATABASE_URL=postgresql://trace:trace-ci-postgres-password@postgres:5432/trace
DATABASE_URL=postgresql://trace_app:trace-ci-app-password@postgres:5432/trace
BACKEND_HTTP_PORT=18000
TEST_POSTGRES_PASSWORD=trace-ci-test-postgres-password
TEST_TRACE_APP_PASSWORD=trace-ci-test-app-password
TEST_MIGRATION_DATABASE_URL=postgresql://trace:trace-ci-test-postgres-password@postgres-test:5432/trace_test
TEST_DATABASE_URL=postgresql://trace_app:trace-ci-test-app-password@postgres-test:5432/trace_test
REDIS_URL=redis://redis:6379/0
SMTP_HOST=mailpit
SMTP_PORT=1025
MAILPIT_HTTP_PORT=18025
RABBITMQ_USER=trace
RABBITMQ_PASSWORD=trace-ci-rabbitmq-password
AUTH_RABBITMQ_URL=amqp://trace:trace-ci-rabbitmq-password@rabbitmq:5672/%2F
AUTH_JWT_PRIVATE_KEY=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY
AUTH_TOKEN_HASH_KEY=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY
AUTH_CSRF_HMAC_KEY=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY
AUTH_AUDIT_HASH_KEY=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY
AUTH_CREDENTIAL_ENCRYPTION_KEY=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY
VAULT_DEV_ROOT_TOKEN_ID=trace-ci-development-root-token
AUTH_ALLOWED_ORIGINS=[]
EOF
