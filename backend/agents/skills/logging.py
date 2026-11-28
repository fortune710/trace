"""Structured logging helpers for skills.sh catalog and agent skill routes.

Log lines are single JSON objects (same shape as review execution logs) so
operators can filter on high-cardinality fields without scraping free text.
Secrets, OIDC/proxy credentials, cookies, CSRF tokens, and skill bodies are
never accepted as fields.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from uuid import UUID

logger = logging.getLogger("trace.skills")

_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "authorization",
        "body",
        "cookie",
        "cookies",
        "credential",
        "csrf",
        "csrf_token",
        "files",
        "oidc_token",
        "password",
        "proxy_secret",
        "secret",
        "skill_md",
        "token",
        "vercel_oidc_token",
    }
)
# Safe diagnostics that contain sensitive substrings but never hold secret values.
_SAFE_DIAGNOSTIC_KEYS = frozenset(
    {
        "oidc_configured",
        "proxy_secret_configured",
        "proxy_url_configured",
        "skill_md_chars",
    }
)
_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|authorization|cookie|credential|csrf|password|secret|token|skill_md)",
    re.IGNORECASE,
)
_SECRET_LIKE = re.compile(
    r"\b(?:sk|gh[opsru]|xai)-[A-Za-z0-9_-]{16,}\b"
    r"|\bAIza[\w-]{20,}\b"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+\b"
    r"|\bBearer\s+\S+",
    re.IGNORECASE,
)

_context: contextvars.ContextVar[dict[str, object] | None] = contextvars.ContextVar(
    "skills_log_context",
    default=None,
)


def _current_context() -> dict[str, object]:
    return dict(_context.get() or {})


def bind_skills_log_context(
    **fields: object,
) -> contextvars.Token[dict[str, object] | None]:
    """Merge request-scoped fields into the current skills log context."""

    merged = {**_current_context(), **_sanitize_fields(fields)}
    return _context.set(merged)


def reset_skills_log_context(
    token: contextvars.Token[dict[str, object] | None],
) -> None:
    _context.reset(token)


@contextmanager
def skills_log_context(**fields: object) -> Iterator[None]:
    token = bind_skills_log_context(**fields)
    try:
        yield
    finally:
        reset_skills_log_context(token)


def skills_log(
    event: str,
    *,
    level: int = logging.INFO,
    exc_info: bool = False,
    fields: Mapping[str, object] | None = None,
    **extra: object,
) -> None:
    """Emit one JSON log object. Callers must only pass approved metadata."""

    payload: dict[str, object] = {
        "event": event,
        **_current_context(),
        **_sanitize_fields(fields or {}),
        **_sanitize_fields(extra),
    }
    logger.log(
        level,
        json.dumps(payload, default=_json_default, sort_keys=True),
        exc_info=exc_info,
    )


def skills_transport_mode(
    *,
    proxy_url: str | None,
    proxy_secret_configured: bool,
    oidc_configured: bool,
) -> str:
    """Return the transport the client will attempt (never includes secrets)."""

    if proxy_url:
        if proxy_secret_configured:
            return "proxy"
        return "proxy_misconfigured"
    if oidc_configured:
        return "direct_oidc"
    return "unconfigured"


def classify_db_error(error: BaseException) -> dict[str, object]:
    """Extract safe SQLAlchemy / DBAPI class metadata without statement text."""

    fields: dict[str, object] = {
        "db_error_class": type(error).__name__,
    }
    orig = getattr(error, "orig", None)
    if orig is not None:
        fields["db_orig_class"] = type(orig).__name__
        sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
        if sqlstate:
            fields["db_sqlstate"] = str(sqlstate)
    return fields


@contextmanager
def timed_step(
    event: str,
    step: str,
    *,
    level: int = logging.INFO,
    error_level: int = logging.ERROR,
    **fields: object,
) -> Iterator[dict[str, object]]:
    """Time a step and emit one finalized log record after outcome/duration settle.

    Callers may mutate the yielded dict with extra safe fields. Do not call
    ``skills_log`` inside the block for the same step — this context manager
    emits after ``outcome`` and ``duration_ms`` are set, including on failure.
    """

    started = time.perf_counter()
    outcome: dict[str, object] = {"step": step, **_sanitize_fields(fields)}
    try:
        yield outcome
        outcome.setdefault("outcome", "success")
    except Exception as error:
        outcome.setdefault("outcome", "error")
        outcome.setdefault("error_type", type(error).__name__)
        outcome.setdefault("error_code", getattr(error, "code", type(error).__name__))
        raise
    finally:
        outcome["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        log_level = error_level if outcome.get("outcome") == "error" else level
        skills_log(event, level=log_level, fields=outcome)


def _sanitize_fields(fields: Mapping[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if not isinstance(key, str):
            continue
        lowered = key.lower()
        if lowered in _FORBIDDEN_FIELD_NAMES:
            continue
        if lowered not in _SAFE_DIAGNOSTIC_KEYS and _SENSITIVE_KEY.search(key):
            continue
        cleaned[key] = _sanitize_value(value)
    return cleaned


def _sanitize_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        if len(value) > 512:
            value = value[:512] + "…"
        return _SECRET_LIKE.sub("[REDACTED]", value)
    if isinstance(value, Mapping):
        return _sanitize_fields({str(key): item for key, item in value.items()})
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in list(value)[:32]]
    return str(value)


def _json_default(value: object) -> str:
    return str(value)


__all__ = [
    "bind_skills_log_context",
    "classify_db_error",
    "reset_skills_log_context",
    "skills_log",
    "skills_log_context",
    "skills_transport_mode",
    "timed_step",
]
