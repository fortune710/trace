"""Source-neutral repository tools used by runtime review agents.

The model supplies the source kind on every call. Target identity, immutable
revision, and authenticated provider access remain in LangChain runtime context
so a model cannot redirect a tool call to a different repository or revision.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from langchain.tools import ToolRuntime
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from agents.execution.redaction import redact_text
from auth.errors import RepositoryNotFound
from external_repositories.service import (
    GitHubRequestLogContext,
    ReviewGitHubSourceAccess,
    ReviewSourceFileError,
    _is_safe_patch,
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


class ValidateDiffInput(BaseModel):
    """Arguments for validating an agent-generated remediation diff."""

    source: ReviewSource = Field(
        description="The review target's source kind. It must match the target source."
    )
    diff: str = Field(
        min_length=1,
        max_length=1_048_576,
        description=(
            "The complete Git unified diff to validate. Call this after composing "
            "a remediation diff and before returning the finding."
        ),
    )


_DIFF_HEADER = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$")
_OLD_FILE_HEADER = re.compile(r"^--- (?:a/[^\s]+|/dev/null)$")
_NEW_FILE_HEADER = re.compile(r"^\+\+\+ (?:b/[^\s]+|/dev/null)$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")


def _structure_error(diff: str) -> str | None:
    """Return a stable reason when a unified diff is structurally malformed."""

    file_count = 0
    saw_old_header = False
    saw_new_header = False
    saw_hunk = False
    expected_old: int | None = None
    expected_new: int | None = None
    actual_old = 0
    actual_new = 0

    def finish_hunk() -> str | None:
        if expected_old is None or expected_new is None:
            return None
        if actual_old != expected_old or actual_new != expected_new:
            return "hunk_line_count_mismatch"
        return None

    for line in diff.splitlines():
        if _DIFF_HEADER.fullmatch(line):
            error = finish_hunk()
            if error is not None:
                return error
            if file_count and (
                not saw_old_header or not saw_new_header or not saw_hunk
            ):
                return "incomplete_file_section"
            file_count += 1
            saw_old_header = False
            saw_new_header = False
            saw_hunk = False
            expected_old = None
            expected_new = None
            actual_old = 0
            actual_new = 0
            continue
        if file_count == 0:
            return "missing_diff_header"
        if expected_old is None and line.startswith("--- "):
            if saw_old_header or saw_new_header or not _OLD_FILE_HEADER.fullmatch(line):
                return "invalid_old_file_header"
            saw_old_header = True
            continue
        if expected_old is None and line.startswith("+++ "):
            if (
                not saw_old_header
                or saw_new_header
                or not _NEW_FILE_HEADER.fullmatch(line)
            ):
                return "invalid_new_file_header"
            saw_new_header = True
            continue
        match = _HUNK_HEADER.fullmatch(line)
        if match is not None:
            if not saw_old_header or not saw_new_header:
                return "hunk_before_file_headers"
            error = finish_hunk()
            if error is not None:
                return error
            expected_old = int(match.group(2) or "1")
            expected_new = int(match.group(4) or "1")
            actual_old = 0
            actual_new = 0
            saw_hunk = True
            continue
        if expected_old is not None:
            if line == "\\ No newline at end of file":
                continue
            if not line or line[0] not in {" ", "+", "-"}:
                return "invalid_hunk_line"
            if line[0] in {" ", "-"}:
                actual_old += 1
            if line[0] in {" ", "+"}:
                actual_new += 1
    error = finish_hunk()
    if error is not None:
        return error
    if file_count == 0:
        return "missing_diff_header"
    if not saw_old_header or not saw_new_header or not saw_hunk:
        return "incomplete_file_section"
    return None


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Trusted review scope injected into tools, never exposed to the model."""

    owner_id: UUID
    source_kind: str
    source_identifier: str
    source_revision: str
    repository_access: ReviewGitHubSourceAccess | None
    review_id: UUID
    review_agent_id: UUID | None = None
    attempt_id: UUID | None = None

    def github_log_context(self) -> GitHubRequestLogContext:
        return GitHubRequestLogContext(
            review_id=self.review_id,
            review_agent_id=self.review_agent_id,
            attempt_id=self.attempt_id,
        )

    def github_repository_access(self) -> ReviewGitHubSourceAccess:
        """Return the configured GitHub reader for a GitHub tool invocation."""
        if self.repository_access is None:
            raise ToolException("source_execution_unsupported")
        return self.repository_access


def _validate_source(*, source: str, runtime: ToolRuntime) -> None:
    if source != _review_context(runtime).source_kind:
        raise ToolException("source_mismatch")


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
    arguments: Mapping[str, object],
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
            paths, truncated = context.github_repository_access().list_paths(
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
    raise ToolException("source_execution_unsupported")


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
            content = context.github_repository_access().read_file(
                path=path,
                log_context=context.github_log_context(),
            )
        except ReviewSourceFileError as error:
            _log_tool_call(
                "repository_tool_failed",
                context=context,
                tool_name="read_file",
                arguments={"source": source, "path": path},
                error=error,
            )
            raise ToolException(error.code) from error
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
    raise ToolException("source_execution_unsupported")


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
            paths, truncated = context.github_repository_access().list_paths(
                path_prefix=path_prefix,
                max_results=_MAX_SEARCH_FILES,
                log_context=context.github_log_context(),
            )
            matches: list[dict[str, object]] = []
            skipped_files = 0
            folded_query = normalized_query.casefold()
            for path in paths:
                try:
                    contents = context.github_repository_access().read_file(
                        path=path,
                        log_context=context.github_log_context(),
                    )
                except (RepositoryNotFound, ReviewSourceFileError):
                    skipped_files += 1
                    continue
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
                            "skipped_files": skipped_files,
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
                                "skipped_files": skipped_files,
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
            "skipped_files": skipped_files,
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
                "skipped_files": skipped_files,
            },
        )
        return result
    if source == "local":
        pass
    raise ToolException("source_execution_unsupported")


def validate_diff_for_review(
    *,
    source: ReviewSource,
    diff: str,
    context: ToolExecutionContext,
) -> dict[str, object]:
    """Run structural, safety, and exact-revision Git validation for a diff."""

    if source != context.source_kind:
        raise ToolException("source_mismatch")
    structure_error = _structure_error(diff)
    if structure_error is not None:
        return {"valid": False, "level": "structure", "reason": structure_error}
    if not _is_safe_patch(diff):
        return {"valid": False, "level": "safety", "reason": "unsafe_patch"}
    if source != "github":
        raise ToolException("source_execution_unsupported")
    if not context.github_repository_access().validate_diff(
        diff=diff,
        log_context=context.github_log_context(),
    ):
        return {"valid": False, "level": "apply", "reason": "does_not_apply"}
    return {"valid": True, "levels": ["structure", "safety", "apply"]}


@tool(args_schema=ValidateDiffInput)
def validate_diff(
    source: ReviewSource,
    diff: str,
    runtime: ToolRuntime,
) -> dict[str, object]:
    """Validate a remediation diff before returning it as a review finding.

    This checks unified-diff structure, rejects unsafe patch forms, then runs
    ``git apply --check`` against the immutable review revision. A result with
    ``valid: false`` must be fixed and validated again before returning a finding.
    """

    context = _review_context(runtime)
    arguments = {"source": source, "diff_bytes": len(diff.encode("utf-8"))}
    _log_tool_call(
        "repository_tool_started",
        context=context,
        tool_name="validate_diff",
        arguments=arguments,
    )
    try:
        result = validate_diff_for_review(source=source, diff=diff, context=context)
    except Exception as error:
        _log_tool_call(
            "repository_tool_failed",
            context=context,
            tool_name="validate_diff",
            arguments=arguments,
            error=error,
        )
        raise
    _log_tool_call(
        "repository_tool_completed",
        context=context,
        tool_name="validate_diff",
        arguments=arguments,
        result=result,
    )
    return result


REPOSITORY_REVIEW_TOOLS = (list_paths, read_file, search_code, validate_diff)

for _repository_tool in REPOSITORY_REVIEW_TOOLS:
    _repository_tool.handle_tool_error = True
