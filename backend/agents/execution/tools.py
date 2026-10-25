"""Source-neutral repository tools used by runtime review agents.

The model supplies the source kind on every call. Target identity, immutable
revision, and authenticated provider access remain in LangChain runtime context
so a model cannot redirect a tool call to a different repository or revision.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agents.execution.redaction import redact_text
from external_repositories.service import (
    GitHubRequestLogContext,
    ReviewGitHubSourceAccess,
)

ReviewSource = Literal["github", "gitlab", "local"]
_MAX_PATH_RESULTS = 500
_MAX_SEARCH_FILES = 50
_MAX_SEARCH_MATCHES = 100
logger = logging.getLogger("trace.agent_execution.tools")


class ListPathsInput(BaseModel):
    """Arguments the model may supply to ``list_paths``."""

    source: ReviewSource = Field(
        description="The review target's source kind. It must match the target source."
    )
    path_prefix: str | None = Field(
        default=None,
        description=(
            "Optional repository-relative directory to list. Use null for the "
            "repository root. Do not use '.', './', '..', an absolute path, or "
            "a path outside the repository."
        ),
    )
    max_results: int = Field(
        default=200,
        ge=1,
        le=_MAX_PATH_RESULTS,
        description="Maximum number of paths to return.",
    )


class ReadFileInput(BaseModel):
    """Arguments the model may supply to ``read_file``."""

    source: ReviewSource = Field(
        description="The review target's source kind. It must match the target source."
    )
    path: str = Field(
        description=(
            "A repository-relative UTF-8 text-file path returned by list_paths. "
            "Do not use '.', '..', an absolute path, or a path outside the repository."
        )
    )


class SearchCodeInput(BaseModel):
    """Arguments the model may supply to ``search_code``."""

    source: ReviewSource = Field(
        description="The review target's source kind. It must match the target source."
    )
    query: str = Field(
        min_length=1,
        description=(
            "Literal text to find, matched case-insensitively in bounded source files. "
            "Use a concise, specific query."
        ),
    )
    path_prefix: str | None = Field(
        default=None,
        description=(
            "Optional repository-relative directory to search. Use null for the "
            "repository root. Do not use '.', './', '..', an absolute path, or "
            "a path outside the repository."
        ),
    )


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Trusted review scope injected into tools, never exposed to the model."""

    owner_id: UUID
    source_kind: str
    source_identifier: str
    source_revision: str
    repository_access: ReviewGitHubSourceAccess
    review_id: UUID
    review_agent_id: UUID | None = None
    attempt_id: UUID | None = None

    def github_log_context(self) -> GitHubRequestLogContext:
        return GitHubRequestLogContext(
            review_id=self.review_id,
            review_agent_id=self.review_agent_id,
            attempt_id=self.attempt_id,
        )


def _validate_source(*, source: str, runtime: ToolRuntime) -> None:
    if source != _review_context(runtime).source_kind:
        raise ValueError("source_mismatch")


def _review_context(runtime: ToolRuntime) -> ToolExecutionContext:
    context = runtime.context
    if not isinstance(context, ToolExecutionContext):
        raise TypeError("tool_execution_context_missing")
    return context


def _log_tool_call(
    event: str,
    *,
    context: ToolExecutionContext,
    tool_name: str,
    arguments: dict[str, object],
    result: dict[str, object] | None = None,
    error: Exception | None = None,
) -> None:
    """Log invoked arguments but never source text or provider credentials."""

    fields: dict[str, object] = {
        "event": event,
        "tool_name": tool_name,
        "source_kind": context.source_kind,
        "source_identifier": context.source_identifier,
        "source_revision": context.source_revision,
        "review_id": context.review_id,
        "arguments": {
            key: redact_text(value) if isinstance(value, str) else value
            for key, value in arguments.items()
        },
    }
    if context.review_agent_id is not None:
        fields["review_agent_id"] = context.review_agent_id
    if context.attempt_id is not None:
        fields["attempt_id"] = context.attempt_id
    if result is not None:
        fields["result"] = result
    if error is not None:
        fields["error_class"] = type(error).__name__
    logger.info(json.dumps(fields, default=str, sort_keys=True))


@tool(args_schema=ListPathsInput)
def list_paths(
    source: ReviewSource,
    runtime: ToolRuntime,
    path_prefix: str | None = None,
    max_results: int = 200,
) -> dict[str, object]:
    """List repository-relative file paths in the immutable review target.

    Supply the target's source kind and optionally restrict results to a
    repository-relative directory prefix. Use this before reading files.
    """
    context = _review_context(runtime)
    _log_tool_call(
        "repository_tool_started",
        context=context,
        tool_name="list_paths",
        arguments={
            "source": source,
            "path_prefix": path_prefix,
            "max_results": max_results,
        },
    )
    _validate_source(source=source, runtime=runtime)
    bounded_max_results = min(max(max_results, 1), _MAX_PATH_RESULTS)
    if source == "github":
        try:
            paths, truncated = context.repository_access.list_paths(
                path_prefix=path_prefix,
                max_results=bounded_max_results,
                log_context=context.github_log_context(),
            )
        except Exception as error:
            _log_tool_call(
                "repository_tool_failed",
                context=context,
                tool_name="list_paths",
                arguments={
                    "source": source,
                    "path_prefix": path_prefix,
                    "max_results": max_results,
                },
                error=error,
            )
            raise
        _log_tool_call(
            "repository_tool_completed",
            context=context,
            tool_name="list_paths",
            arguments={
                "source": source,
                "path_prefix": path_prefix,
                "max_results": max_results,
            },
            result={"path_count": len(paths), "truncated": truncated},
        )
        return {"paths": paths, "truncated": truncated}
    if source == "local":
        pass
    raise ValueError("source_execution_unsupported")


@tool(args_schema=ReadFileInput)
def read_file(
    source: ReviewSource,
    path: str,
    runtime: ToolRuntime,
) -> dict[str, str]:
    """Read one repository-relative UTF-8 text file from the immutable target.

    Supply the target's source kind and a path returned by ``list_paths``.
    """
    context = _review_context(runtime)
    _log_tool_call(
        "repository_tool_started",
        context=context,
        tool_name="read_file",
        arguments={"source": source, "path": path},
    )
    _validate_source(source=source, runtime=runtime)
    if source == "github":
        try:
            content = context.repository_access.read_file(
                path=path,
                log_context=context.github_log_context(),
            )
        except Exception as error:
            _log_tool_call(
                "repository_tool_failed",
                context=context,
                tool_name="read_file",
                arguments={"source": source, "path": path},
                error=error,
            )
            raise
        _log_tool_call(
            "repository_tool_completed",
            context=context,
            tool_name="read_file",
            arguments={"source": source, "path": path},
            result={"content_bytes": len(content.encode("utf-8"))},
        )
        return {"path": path, "content": content}
    if source == "local":
        pass
    raise ValueError("source_execution_unsupported")


@tool(args_schema=SearchCodeInput)
def search_code(
    source: ReviewSource,
    query: str,
    runtime: ToolRuntime,
    path_prefix: str | None = None,
) -> dict[str, object]:
    """Find literal text matches in bounded immutable-source files.

    Supply the target's source kind and a concise literal query. For GitHub,
    search is derived from revision-pinned GitHub file APIs instead of the
    GitHub code-search endpoint, which cannot guarantee an immutable revision.
    """
    context = _review_context(runtime)
    _log_tool_call(
        "repository_tool_started",
        context=context,
        tool_name="search_code",
        arguments={
            "source": source,
            "query": query,
            "path_prefix": path_prefix,
        },
    )
    _validate_source(source=source, runtime=runtime)
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("search_query_required")
    if source == "github":
        try:
            paths, truncated = context.repository_access.list_paths(
                path_prefix=path_prefix,
                max_results=_MAX_SEARCH_FILES,
                log_context=context.github_log_context(),
            )
            matches: list[dict[str, object]] = []
            folded_query = normalized_query.casefold()
            for path in paths:
                contents = context.repository_access.read_file(
                    path=path,
                    log_context=context.github_log_context(),
                )
                for line_number, line in enumerate(contents.splitlines(), start=1):
                    if folded_query not in line.casefold():
                        continue
                    matches.append(
                        {"path": path, "line_number": line_number, "line": line}
                    )
                    if len(matches) == _MAX_SEARCH_MATCHES:
                        result = {
                            "matches": matches,
                            "truncated": True,
                            "files_truncated": truncated,
                        }
                        _log_tool_call(
                            "repository_tool_completed",
                            context=context,
                            tool_name="search_code",
                            arguments={
                                "source": source,
                                "query": query,
                                "path_prefix": path_prefix,
                            },
                            result={
                                "match_count": len(matches),
                                "truncated": True,
                                "files_truncated": truncated,
                            },
                        )
                        return result
        except Exception as error:
            _log_tool_call(
                "repository_tool_failed",
                context=context,
                tool_name="search_code",
                arguments={
                    "source": source,
                    "query": query,
                    "path_prefix": path_prefix,
                },
                error=error,
            )
            raise
        result = {
            "matches": matches,
            "truncated": False,
            "files_truncated": truncated,
        }
        _log_tool_call(
            "repository_tool_completed",
            context=context,
            tool_name="search_code",
            arguments={
                "source": source,
                "query": query,
                "path_prefix": path_prefix,
            },
            result={
                "match_count": len(matches),
                "truncated": False,
                "files_truncated": truncated,
            },
        )
        return result
    if source == "local":
        pass
    raise ValueError("source_execution_unsupported")


REPOSITORY_REVIEW_TOOLS = (list_paths, read_file, search_code)
