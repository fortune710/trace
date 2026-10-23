from __future__ import annotations

import hashlib
import hmac
import logging
import re
from collections.abc import Mapping

_EVENT_COMPONENT = re.compile(r"^[a-z0-9_]{1,64}$")
_SAFE_CONTEXT_KEYS = frozenset(
    {
        "exception_class",
        "policy",
        "provider",
    }
)


class AuditHasher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Audit hash key must contain exactly 32 bytes")
        self._key = key

    def hash(self, value: str) -> str:
        return hmac.new(self._key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def log_auth_event(
    *,
    event: str,
    outcome: str,
    reason: str,
    request_id: str,
    route: str,
    status_code: int,
    context: Mapping[str, str] | None = None,
    audit_hasher: AuditHasher | None = None,
    identity: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Emit a bounded structured record without caller-provided secret values."""
    components = (event, outcome, reason)
    if not all(_EVENT_COMPONENT.fullmatch(component) for component in components):
        raise ValueError("Authentication audit event contains an invalid component")

    safe_context = {
        key: value[:128]
        for key, value in (context or {}).items()
        if key in _SAFE_CONTEXT_KEYS and isinstance(value, str)
    }
    hashed_context = {
        name: audit_hasher.hash(value)
        for name, value in {
            "identity_hash": identity,
            "ip_hash": ip_address,
            "user_agent_hash": user_agent,
        }.items()
        if audit_hasher is not None and isinstance(value, str) and value
    }
    logging.getLogger("trace.auth").info(
        "auth_event",
        extra={
            "auth": {
                "event": event,
                "outcome": outcome,
                "reason": reason,
                "request_id": request_id,
                "route": route,
                "status_code": status_code,
                **safe_context,
                **hashed_context,
            }
        },
    )
