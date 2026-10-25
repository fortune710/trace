#!/usr/bin/env python3
"""Render the Compose environment from explicitly supplied Actions secrets."""

from __future__ import annotations

import os
import sys
from pathlib import Path


REQUIRED = (
    "AUDIT_DATABASE",
    "AUDIT_IMMUDB_ADMIN_PASSWORD",
    "AUDIT_PASSWORD",
    "AUDIT_USERNAME",
    "AUTH_ACCESS_COOKIE_NAME",
    "AUTH_ALLOWED_ORIGINS",
    "AUTH_AUDIT_HASH_KEY",
    "AUTH_CSRF_COOKIE_NAME",
    "AUTH_CSRF_HMAC_KEY",
    "AUTH_EMAIL_FROM",
    "AUTH_FRONTEND_URL",
    "AUTH_JWT_AUDIENCE",
    "AUTH_JWT_ISSUER",
    "AUTH_JWT_KID",
    "AUTH_JWT_PRIVATE_KEY",
    "AUTH_RABBITMQ_URL",
    "AUTH_REFRESH_COOKIE_NAME",
    "AUTH_TOKEN_HASH_KEY",
    "DATABASE_URL",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "MAINTENANCE_DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "POSTGRES_PASSWORD",
    "RABBITMQ_PASSWORD",
    "RABBITMQ_USER",
    "REDIS_URL",
    "REVIEW_RABBITMQ_URL",
    "SMTP_HOST",
    "SMTP_PASSWORD",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "TRACE_APP_PASSWORD",
    "TRACE_CREDENTIAL_MAINTENANCE_PASSWORD",
    "TRACE_INTERNAL_PASSWORD",
)

OPTIONAL = (
    "AGENT_ANTHROPIC_API_KEY",
    "AGENT_GOOGLE_API_KEY",
    "AGENT_OPENAI_API_KEY",
    "AGENT_XAI_API_KEY",
    "AUDIT_DEAD_LETTER_RETENTION_DAYS",
    "AUDIT_HOST",
    "AUDIT_MAX_ATTEMPTS",
    "AUDIT_OUTBOX_RETENTION_DAYS",
    "AUDIT_PORT",
    "AUDIT_RETRY_BASE_SECONDS",
    "AUDIT_RETRY_MAX_SECONDS",
    "AUTH_CREDENTIAL_ENCRYPTION_KEY_VERSION",
    "AUTH_CREDENTIAL_ENCRYPTION_VERIFICATION_KEYS",
    "AUTH_DESKTOP_ALLOWED_ORIGINS",
    "AUTH_EMAIL_MAX_RETRIES",
    "AUTH_EMAIL_RETRY_DELAYS_SECONDS",
    "AUTH_GITHUB_CLIENT_ID",
    "AUTH_GITHUB_CLIENT_SECRET",
    "AUTH_GITHUB_REDIRECT_URI",
    "AUTH_GOOGLE_CLIENT_ID",
    "AUTH_GOOGLE_CLIENT_SECRET",
    "AUTH_GOOGLE_REDIRECT_URI",
    "AUTH_JWT_VERIFICATION_KEYS",
    "AUTH_VAULT_REQUEST_TIMEOUT_SECONDS",
    "AUTH_VAULT_TOKEN_RENEWAL_SECONDS",
    "BACKEND_HTTP_PORT",
    "LANGSMITH_ENDPOINT",
    "REVIEW_MAX_ATTEMPTS",
    "REVIEW_POLL_SECONDS",
    "REVIEW_PROCESSING_TIMEOUT_SECONDS",
    "REVIEW_RETRY_BASE_SECONDS",
    "REVIEW_RETRY_MAX_SECONDS",
)

FIXED = {
    "AUDIT_ENABLED": "true",
    "AUTH_COOKIE_SAME_SITE": "none",
    "AUTH_COOKIE_SECURE": "true",
    "AUTH_CREDENTIAL_ENCRYPTION_PROVIDER": "vault",
    "AUTH_ENVIRONMENT": "production",
    "AUTH_VAULT_ADDR": "http://vault:8200",
    "AUTH_VAULT_EMAIL_TRANSIT_KEY": "trace-email-delivery",
    "AUTH_VAULT_TRANSIT_KEY": "trace-provider-credentials",
    "AUTH_VAULT_TRANSIT_MOUNT": "transit",
    "AUTH_SMTP_USE_STARTTLS": "true",
    "LANGSMITH_TRACING": "true",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: render-production-env.py OUTPUT_PATH", file=sys.stderr)
        return 2

    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        print("Missing required Actions secrets: " + ", ".join(missing), file=sys.stderr)
        return 1

    values = dict(FIXED)
    values.update({name: os.environ[name] for name in REQUIRED})
    values.update(
        {name: os.environ[name] for name in OPTIONAL if os.environ.get(name)}
    )

    for name, value in values.items():
        if "\n" in value or "\r" in value or "\0" in value:
            print(f"{name} must be a single-line value.", file=sys.stderr)
            return 1

    output = Path(sys.argv[1])
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        for name in sorted(values):
            escaped_value = values[name].replace("'", "\\'")
            file.write(f"{name}='{escaped_value}'\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
