"""Source-neutral repository tools used by runtime review agents.

The model supplies the source kind on every call. Target identity, immutable
revision, and authenticated provider access remain in LangChain runtime context
so a model cannot redirect a tool call to a different repository or revision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from external_repositories.service import RepositoryService

ReviewSource = Literal["github", "gitlab", "local"]
_MAX_PATH_RESULTS = 500
_MAX_SEARCH_FILES = 50
_MAX_SEARCH_MATCHES = 100


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Trusted review scope injected into tools, never exposed to the model."""

    owner_id: UUID
    source_kind: str
    source_identifier: str
    source_revision: str
    repository_service: RepositoryService


def _validate_source(*, source: str, runtime: ToolRuntime) -> None:
    if source != _review_context(runtime).source_kind:
        raise ValueError("source_mismatch")


def _review_context(runtime: ToolRuntime) -> ToolExecutionContext:
    context = runtime.context
    if not isinstance(context, ToolExecutionContext):
        raise TypeError("tool_execution_context_missing")
    return context


@tool
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
    _validate_source(source=source, runtime=runtime)
    bounded_max_results = min(max(max_results, 1), _MAX_PATH_RESULTS)
    if source == "github":
        context = _review_context(runtime)
        paths, truncated = context.repository_service.list_paths(
            owner_id=context.owner_id,
            repository_identifier=context.source_identifier,
            revision=context.source_revision,
            path_prefix=path_prefix,
            max_results=bounded_max_results,
        )
        return {"paths": paths, "truncated": truncated}
    if source == "local":
        pass
    raise ValueError("source_execution_unsupported")


@tool
def read_file(
    source: ReviewSource,
    path: str,
    runtime: ToolRuntime,
) -> dict[str, str]:
    """Read one repository-relative UTF-8 text file from the immutable target.

    Supply the target's source kind and a path returned by ``list_paths``.
    """
    _validate_source(source=source, runtime=runtime)
    if source == "github":
        context = _review_context(runtime)
        return {
            "path": path,
            "content": context.repository_service.read_file(
                owner_id=context.owner_id,
                repository_identifier=context.source_identifier,
                revision=context.source_revision,
                path=path,
            ),
        }
    if source == "local":
        pass
    raise ValueError("source_execution_unsupported")


@tool
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
    _validate_source(source=source, runtime=runtime)
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("search_query_required")
    if source == "github":
        context = _review_context(runtime)
        paths, truncated = context.repository_service.list_paths(
            owner_id=context.owner_id,
            repository_identifier=context.source_identifier,
            revision=context.source_revision,
            path_prefix=path_prefix,
            max_results=_MAX_SEARCH_FILES,
        )
        matches: list[dict[str, object]] = []
        folded_query = normalized_query.casefold()
        for path in paths:
            contents = context.repository_service.read_file(
                owner_id=context.owner_id,
                repository_identifier=context.source_identifier,
                revision=context.source_revision,
                path=path,
            )
            for line_number, line in enumerate(contents.splitlines(), start=1):
                if folded_query not in line.casefold():
                    continue
                matches.append({"path": path, "line_number": line_number, "line": line})
                if len(matches) == _MAX_SEARCH_MATCHES:
                    return {
                        "matches": matches,
                        "truncated": True,
                        "files_truncated": truncated,
                    }
        return {
            "matches": matches,
            "truncated": False,
            "files_truncated": truncated,
        }
    if source == "local":
        pass
    raise ValueError("source_execution_unsupported")


REPOSITORY_REVIEW_TOOLS = (list_paths, read_file, search_code)
