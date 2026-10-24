"""Replace generated-secret markers in .env.production with unique values."""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/generate-production-env-secrets.py .env.production")

    environment_file = Path(sys.argv[1])
    contents = environment_file.read_text(encoding="utf-8")
    secret_names = (
        "POSTGRES_PASSWORD",
        "TRACE_APP_PASSWORD",
        "TRACE_INTERNAL_PASSWORD",
        "TRACE_CREDENTIAL_MAINTENANCE_PASSWORD",
        "RABBITMQ_PASSWORD",
        "AUTH_JWT_PRIVATE_KEY",
        "AUTH_TOKEN_HASH_KEY",
        "AUTH_CSRF_HMAC_KEY",
        "AUTH_AUDIT_HASH_KEY",
        "AUDIT_PASSWORD",
        "AUDIT_IMMUDB_ADMIN_PASSWORD",
    )
    generated = {name: secrets.token_urlsafe(32) for name in secret_names}
    replacements = {
        **{
            f"__GENERATE_{name}__": value
            for name, value in generated.items()
        },
        "__SAME_AS_POSTGRES_PASSWORD__": generated["POSTGRES_PASSWORD"],
        "__SAME_AS_TRACE_APP_PASSWORD__": generated["TRACE_APP_PASSWORD"],
        "__SAME_AS_TRACE_CREDENTIAL_MAINTENANCE_PASSWORD__": generated[
            "TRACE_CREDENTIAL_MAINTENANCE_PASSWORD"
        ],
        "__SAME_AS_RABBITMQ_PASSWORD__": generated["RABBITMQ_PASSWORD"],
    }
    unresolved = [marker for marker in replacements if marker not in contents]
    if unresolved:
        raise SystemExit(
            "refusing to modify an unexpected template; missing markers: "
            + ", ".join(unresolved)
        )

    for marker, value in replacements.items():
        contents = contents.replace(marker, value)
    environment_file.write_text(contents, encoding="utf-8")
    environment_file.chmod(0o600)

    remaining_markers = re.findall(r"__GENERATE_[A-Z0-9_]+__", contents)
    if remaining_markers:
        raise SystemExit("some generated-secret markers remain")

    print(f"Generated secrets in {environment_file} and set permissions to 0600.")


if __name__ == "__main__":
    main()
