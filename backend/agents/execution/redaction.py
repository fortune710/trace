"""Minimal fail-closed source and finding secret redaction."""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|gh[opsru]|xai)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[\w-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+\b"),
)


def redact_text(value: str) -> str:
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED_SECRET]", value)
    return value
