#!/usr/bin/env bash

set -euo pipefail

target_file="${1:?Usage: write-compose-env.sh PATH}"
umask 077

base64url_key() {
  python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"))'
}

jwt_private_key="$(base64url_key)"
token_hash_key="$(base64url_key)"
csrf_hmac_key="$(base64url_key)"
audit_hash_key="$(base64url_key)"
credential_encryption_key="$(base64url_key)"

pick_free_port() {
  python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

if [[ "${COMPOSE_DYNAMIC_PORTS:-false}" == "true" ]]; then
  backend_http_port="$(pick_free_port)"
  mailpit_http_port="$(pick_free_port)"
  oauth_stub_http_port="$(pick_free_port)"
else
  backend_http_port="${BACKEND_HTTP_PORT:-18000}"
  mailpit_http_port="${MAILPIT_HTTP_PORT:-18025}"
  oauth_stub_http_port="${OAUTH_STUB_HTTP_PORT:-19000}"
fi

cat >"$target_file" <<EOF
POSTGRES_PASSWORD=trace-ci-postgres-password
TRACE_APP_PASSWORD=trace-ci-app-password
TRACE_INTERNAL_PASSWORD=trace-ci-internal-password
TRACE_CREDENTIAL_MAINTENANCE_PASSWORD=trace-ci-credential-maintenance-password
MIGRATION_DATABASE_URL=postgresql://trace:trace-ci-postgres-password@postgres:5432/trace
DATABASE_URL=postgresql://trace_app:trace-ci-app-password@postgres:5432/trace
INTERNAL_DATABASE_URL=postgresql://trace_internal:trace-ci-internal-password@postgres:5432/trace
MAINTENANCE_DATABASE_URL=postgresql://trace_credential_maintenance:trace-ci-credential-maintenance-password@postgres:5432/trace
BACKEND_HTTP_PORT=$backend_http_port
TEST_POSTGRES_PASSWORD=trace-ci-test-postgres-password
TEST_TRACE_APP_PASSWORD=trace-ci-test-app-password
TEST_TRACE_INTERNAL_PASSWORD=trace-ci-test-internal-password
TEST_TRACE_CREDENTIAL_MAINTENANCE_PASSWORD=trace-ci-test-credential-maintenance-password
TEST_MIGRATION_DATABASE_URL=postgresql://trace:trace-ci-test-postgres-password@postgres-test:5432/trace_test
TEST_DATABASE_URL=postgresql://trace_app:trace-ci-test-app-password@postgres-test:5432/trace_test
TEST_INTERNAL_DATABASE_URL=postgresql://trace_internal:trace-ci-test-internal-password@postgres-test:5432/trace_test
TEST_MAINTENANCE_DATABASE_URL=postgresql://trace_credential_maintenance:trace-ci-test-credential-maintenance-password@postgres-test:5432/trace_test
REDIS_URL=redis://redis:6379/0
SMTP_HOST=mailpit
SMTP_PORT=1025
MAILPIT_HTTP_PORT=$mailpit_http_port
OAUTH_STUB_HTTP_PORT=$oauth_stub_http_port
RABBITMQ_USER=trace
RABBITMQ_PASSWORD=trace-ci-rabbitmq-password
AUTH_RABBITMQ_URL=amqp://trace:trace-ci-rabbitmq-password@rabbitmq:5672/%2F
AUDIT_ENABLED=true
AUDIT_HOST=immudb
AUDIT_PORT=3322
AUDIT_DATABASE=trace_audit
AUDIT_USERNAME=trace_audit
AUDIT_PASSWORD=TraceAudit1!
AUDIT_IMMUDB_ADMIN_PASSWORD=TraceImmuAdmin1!
AUDIT_ROOT_STATE_DIR=/var/lib/trace-audit
AUDIT_MAX_ATTEMPTS=3
AUDIT_RETRY_BASE_SECONDS=1
AUDIT_RETRY_MAX_SECONDS=10
AUTH_JWT_PRIVATE_KEY=$jwt_private_key
AUTH_TOKEN_HASH_KEY=$token_hash_key
AUTH_CSRF_HMAC_KEY=$csrf_hmac_key
AUTH_AUDIT_HASH_KEY=$audit_hash_key
AUTH_CREDENTIAL_ENCRYPTION_KEY=$credential_encryption_key
VAULT_DEV_ROOT_TOKEN_ID=trace-ci-development-root-token
AUTH_ALLOWED_ORIGINS=[]
EOF
