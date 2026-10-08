from __future__ import annotations

import hashlib
import hmac
import secrets
from uuid import UUID


def issue_csrf_token(*, session_id: UUID, key: bytes) -> str:
    nonce = secrets.token_urlsafe(32)
    signature = hmac.new(
        key, f"trace-csrf:v1:{session_id}:{nonce}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{nonce}.{signature}"


def validate_csrf_token(
    *, cookie_token: str | None, header_token: str | None, session_id: UUID, key: bytes
) -> bool:
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        return False

    nonce, separator, signature = cookie_token.partition(".")
    if not separator or not nonce or len(signature) != 64:
        return False
    expected_signature = hmac.new(
        key,
        f"trace-csrf:v1:{session_id}:{nonce}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)
