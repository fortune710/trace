"""Safe diagnostics: never carry source excerpts or raw subprocess output."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

Stage = Literal[
    "source", "edit", "generation", "structure", "apply", "round_trip", "storage"
]


class PatchDiagnostic(BaseModel):
    stage: Stage
    code: str
    message: str
    retryable: bool = True
    path: str | None = None
    edit_index: int | None = None
    hunk_number: int | None = None
    line_offset: int | None = None
    original_line: int | None = None
    new_line: int | None = None
    expected_count: int | None = None
    actual_count: int | None = None
    fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def schema_error_fields(error: object, limit: int = 8) -> list[str]:
    """Name each failing schema field and rule, never the submitted value."""
    # LangChain re-raises schema failures as a ValueError caused by the pydantic error.
    seen = 0
    while isinstance(error, BaseException) and seen < 5:
        if isinstance(error, ValidationError):
            break
        error = error.__cause__
        seen += 1
    if not isinstance(error, ValidationError):
        return []
    fields = []
    for item in error.errors(
        include_url=False, include_context=False, include_input=False
    )[:limit]:
        location = ".".join(str(part) for part in item["loc"])
        fields.append(
            re.sub(r"[^A-Za-z0-9_.: -]", "?", f"{location}: {item['type']}")[:100]
        )
    return fields


class PatchGenerationError(ValueError):
    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        stage: Stage = "edit",
        retryable: bool = True,
        **details,
    ):
        super().__init__(reason)
        self.reason = reason
        self.path = path
        self.detail = PatchDiagnostic(
            stage=stage,
            code=reason,
            message=reason.replace("_", " ").capitalize(),
            path=path,
            retryable=retryable,
            **details,
        )

    def diagnostic(self) -> dict[str, object]:
        from agents.execution.redaction import redact_text

        return {
            key: redact_text(value) if isinstance(value, str) else value
            for key, value in self.detail.model_dump(exclude_none=True).items()
        }
