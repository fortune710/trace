"""Generate native Git patches from trusted, revision-bound structured edits."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.execution.diagnostics import PatchGenerationError
from agents.execution.source import safe_patch_path, source_lines
from agents.execution.tools import ToolExecutionContext
from external_repositories.service import ReviewSourceFileError


class EditBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("replacement", "content", check_fields=False)
    @classmethod
    def valid_utf8(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("replacement must be valid UTF-8") from None
        return value


class ReplaceEdit(EditBase):
    operation: Literal["replace"] = "replace"
    source_ref: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    replacement: str = Field(max_length=1_048_576)


class InsertEdit(EditBase):
    operation: Literal["insert"] = "insert"
    source_ref: str
    before_line: int = Field(ge=1)
    replacement: str = Field(max_length=1_048_576)


class CreateEdit(EditBase):
    operation: Literal["create"] = "create"
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=1_048_576)


PatchIntent = Annotated[
    ReplaceEdit | InsertEdit | CreateEdit, Field(discriminator="operation")
]


class PatchIntentBatch(BaseModel):
    edits: list[PatchIntent] = Field(min_length=1, max_length=20)


class PatchFile(BaseModel):
    path: str
    operation: Literal["replace", "create"]
    original_sha256: str | None
    result_sha256: str


class GeneratedPatch(BaseModel):
    diff: str
    sha256: str
    source_snapshot: dict[str, str]
    files: list[PatchFile]
    warnings: list[str] = Field(default_factory=list)


def git_environment() -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    return {
        **env,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }


def run_git(
    root: Path, *args: str, data: bytes | None = None, accepted: tuple[int, ...] = (0,)
) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.quotePath=false",
                "-c",
                "core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol",
                *args,
            ],
            cwd=root,
            env=git_environment(),
            input=data,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PatchGenerationError(
            "git_unavailable", stage="generation", retryable=False
        ) from exc
    if result.returncode not in accepted:
        # stderr can contain literal source lines; never propagate it.
        line = re.search(rb"(?:at line|on line) (\d+)", result.stderr[:8192])
        raise PatchGenerationError(
            "git_patch_rejected",
            stage="apply",
            line_offset=int(line.group(1)) if line else None,
        )
    return result


def build_patch(
    *,
    original: dict[str, str | None],
    updated: dict[str, str],
    snapshot: dict[str, str],
) -> GeneratedPatch:
    """Native serialization plus a byte-exact round trip, with no network access."""
    for path, checked_content in [*original.items(), *updated.items()]:
        if checked_content is not None and "\0" in checked_content:
            raise PatchGenerationError("binary_patch_unsupported", path=path)
        if any(
            parent in updated
            for parent in [str(value) for value in Path(path).parents]
            if parent != "."
        ):
            raise PatchGenerationError("conflicting_file_paths", path=path)
    with tempfile.TemporaryDirectory(prefix="trace-patch-") as directory:
        root = Path(directory)
        run_git(root, "init", "-q")
        (root / ".git/info/attributes").write_text(
            "* -text -filter -ident -working-tree-encoding\n"
        )
        for path, content in original.items():
            if not safe_patch_path(path):
                raise PatchGenerationError("unsafe_path", path=path)
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if content is not None:
                target.write_bytes(content.encode("utf-8"))
                run_git(root, "add", "--force", "--", path)
        for path, content in updated.items():
            (root / path).write_bytes(content.encode("utf-8"))
            if original[path] is None:
                run_git(root, "add", "--force", "--intent-to-add", "--", path)
        diff_bytes = run_git(
            root,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--no-color",
            "--full-index",
            "--unified=3",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            "--",
            *sorted(updated),
        ).stdout
        if not diff_bytes:
            raise PatchGenerationError("no_change")
        if len(diff_bytes) > 1_048_576:
            raise PatchGenerationError("diff_too_large")
        whitespace = run_git(root, "diff", "--check", accepted=(0, 2)).returncode
        for path, content in original.items():
            target = root / path
            if content is None:
                target.unlink()
            else:
                target.write_bytes(content.encode("utf-8"))
        run_git(root, "apply", "--check", "--whitespace=nowarn", "-", data=diff_bytes)
        run_git(root, "apply", "--whitespace=nowarn", "-", data=diff_bytes)
        for path, content in updated.items():
            if (root / path).read_bytes() != content.encode("utf-8"):
                raise PatchGenerationError(
                    "result_bytes_mismatch",
                    path=path,
                    stage="round_trip",
                    retryable=False,
                )
        return GeneratedPatch(
            diff=diff_bytes.decode("utf-8"),
            sha256=hashlib.sha256(diff_bytes).hexdigest(),
            source_snapshot=snapshot,
            files=[
                PatchFile(
                    path=path,
                    operation="create" if original[path] is None else "replace",
                    original_sha256=hashlib.sha256(
                        (original[path] or "").encode()
                    ).hexdigest()
                    if original[path] is not None
                    else None,
                    result_sha256=hashlib.sha256(content.encode()).hexdigest(),
                )
                for path, content in sorted(updated.items())
                if original[path] is None or original[path] != content
            ],
            warnings=["added_whitespace_errors"] if whitespace else [],
        )


def generate_patch(
    *, intents: PatchIntentBatch, context: ToolExecutionContext
) -> GeneratedPatch:
    grouped: dict[str, list[tuple[int, ReplaceEdit | InsertEdit | CreateEdit]]] = (
        defaultdict(list)
    )
    originals: dict[str, str | None] = {}
    for index, edit in enumerate(intents.edits):
        if isinstance(edit, CreateEdit):
            path = edit.path
            if not safe_patch_path(path):
                raise PatchGenerationError("unsafe_path", path=path, edit_index=index)
            try:
                context.source_reader().read_file(
                    path=path, log_context=context.github_log_context()
                )
            except ReviewSourceFileError as exc:
                if exc.code != "path_not_found":
                    raise PatchGenerationError(
                        "source_lookup_failed",
                        path=path,
                        stage="source",
                        retryable=False,
                    ) from exc
            else:
                raise PatchGenerationError("file_already_exists", path=path)
            originals[path] = None
            grouped[path].append((index, edit))
        else:
            record = context.source_registry.records.get(edit.source_ref)
            if (
                record is None
                or record.revision != context.source_revision
                or record.scope != context.source_scope()
            ):
                raise PatchGenerationError(
                    "invalid_source_reference", edit_index=index, stage="source"
                )
            if hashlib.sha256(record.content.encode()).hexdigest() != record.sha256:
                raise PatchGenerationError(
                    "source_integrity_failed", stage="source", retryable=False
                )
            path = record.path
            if not safe_patch_path(path):
                raise PatchGenerationError("unsafe_path", path=path)
            if path in originals and originals[path] != record.content:
                raise PatchGenerationError("conflicting_source", path=path)
            originals[path] = record.content
            grouped[path].append((index, edit))
    updated = {}
    for path, edits in grouped.items():
        if any(isinstance(edit, CreateEdit) for _, edit in edits):
            if len(edits) != 1:
                raise PatchGenerationError("conflicting_edits", path=path)
            create = edits[0][1]
            assert isinstance(create, CreateEdit)
            updated[path] = create.content
            continue
        original = originals[path]
        assert original is not None
        lines = source_lines(original)
        ranges = []
        for index, edit in edits:
            assert not isinstance(edit, CreateEdit)
            start = (
                edit.start_line - 1
                if isinstance(edit, ReplaceEdit)
                else edit.before_line - 1
            )
            end = edit.end_line if isinstance(edit, ReplaceEdit) else start
            if (
                start > len(lines)
                or end > len(lines)
                or (isinstance(edit, ReplaceEdit) and end <= start)
            ):
                raise PatchGenerationError(
                    "invalid_line_range",
                    path=path,
                    edit_index=index,
                    expected_count=len(lines),
                    original_line=start + 1,
                )
            ranges.append((start, end, edit.replacement, index))
        previous = len(lines) + 1
        for start, end, replacement, index in sorted(ranges, reverse=True):
            if end > previous or start == previous:
                raise PatchGenerationError(
                    "overlapping_edits", path=path, edit_index=index
                )
            lines[start:end] = [replacement]
            previous = start
        updated[path] = "".join(lines)
    return build_patch(
        original=originals,
        updated=updated,
        snapshot={
            "source_kind": context.source_kind,
            "source_identifier": context.source_identifier,
            "revision": context.source_revision,
        },
    )


def generate_validated_diff(
    *, intents: PatchIntentBatch, context: ToolExecutionContext
) -> str:
    return generate_patch(intents=intents, context=context).diff
