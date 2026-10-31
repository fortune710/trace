"""Attempt-bound source handles and byte-preserving text lines."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4


def source_lines(content: str) -> list[str]:
    """Git lines end only at LF, not at Unicode text separators."""
    parts = content.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


class SourceReader(Protocol):
    def read_file(self, *, path: str, log_context: Any) -> str: ...

    def validate_diff(self, *, diff: str, log_context: Any) -> bool: ...

    def list_paths(
        self, *, path_prefix: str | None, max_results: int, log_context: Any
    ) -> tuple[list[str], bool, int]: ...


@dataclass(frozen=True)
class SourceRecord:
    path: str
    revision: str
    content: str
    sha256: str
    scope: tuple[str, ...]


@dataclass
class SourceRegistry:
    records: dict[str, SourceRecord] = field(default_factory=dict)
    reads: int = 0

    def register(
        self, *, path: str, revision: str, content: str, scope: tuple[str, ...]
    ) -> str:
        self.reads += 1
        reference = str(uuid4())
        self.records[reference] = SourceRecord(
            path,
            revision,
            content,
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
            scope,
        )
        return reference


def safe_patch_path(path: str) -> bool:
    return bool(
        path
        and not path.startswith("/")
        and "\\" not in path
        and not any(ord(char) < 32 or ord(char) == 127 for char in path)
        and not any(
            part in {"", ".", ".."} or part.casefold() == ".git"
            for part in path.split("/")
        )
        and not (len(path) > 1 and path[1] == ":")
    )


def patch_paths(diff: str) -> list[str]:
    """Decode the supported same-path Git header, including quoted filenames."""
    result = []
    for line in diff.split("\n"):
        if not line.startswith("diff --git "):
            continue
        header = line[len("diff --git ") :]
        if header.startswith('"'):
            # Git uses C quoting; supported paths have no control bytes or backslashes.
            tokens = re.findall(r'"(?:[^"\\]|\\.)*"|\S+', header)
            paths = [
                json.loads(token) if token.startswith('"') else token
                for token in tokens
            ]
            if len(paths) != 2:
                raise ValueError("unsupported_patch_path")
            old, new = paths
        else:
            match = re.fullmatch(r"a/(.+) b/\1", header)
            if match is None:
                raise ValueError("unsupported_patch_path")
            old, new = "a/" + match[1], "b/" + match[1]
        if (
            not old.startswith("a/")
            or not new.startswith("b/")
            or old[2:] != new[2:]
            or not safe_patch_path(old[2:])
            or old[2:] in result
        ):
            raise ValueError("unsupported_patch_path")
        result.append(old[2:])
    if not result:
        raise ValueError("missing_patch_path")
    return result


class CachedSourceReader:
    """One review's immutable file cache; references remain attempt-scoped."""

    def __init__(self, reader):
        self.reader = reader
        self.files = {}

    def read_file(self, *, path, log_context):
        if path not in self.files:
            self.files[path] = self.reader.read_file(path=path, log_context=log_context)
        return self.files[path]

    def list_paths(self, **kwargs):
        return self.reader.list_paths(**kwargs)

    def validate_diff(self, **kwargs):
        return self.reader.validate_diff(**kwargs)
