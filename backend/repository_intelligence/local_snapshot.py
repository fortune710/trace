"""Validate the desktop manifest before accepting immutable local source."""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import PurePosixPath


def decode_snapshot_entries(
    entries: list[dict[str, object]], expected_digest: str
) -> dict[str, bytes]:
    if len(entries) > 3_000:
        raise ValueError("snapshot_too_large")
    files: dict[str, bytes] = {}
    records: list[tuple[str, bool, bytes | None]] = []
    total = 0
    seen: set[str] = set()
    directories: set[str] = set()
    for entry in entries:
        path = entry.get("path")
        directory = entry.get("directory")
        encoded = entry.get("content_base64")
        if (
            not isinstance(path, str)
            or not path
            or path == "."
            or len(path) > 1024
            or path.startswith("/")
            or "\\" in path
            or any(ord(character) < 32 for character in path)
            or str(PurePosixPath(path)) != path
            or ".." in PurePosixPath(path).parts
            or path in seen
            or not isinstance(directory, bool)
        ):
            raise ValueError("snapshot_path_invalid")
        seen.add(path)
        if directory:
            if encoded is not None:
                raise ValueError("snapshot_entry_invalid")
            records.append((path, True, None))
            directories.add(path)
        else:
            if not isinstance(encoded, str) or len(encoded) > 350_000:
                raise ValueError("snapshot_entry_invalid")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, UnicodeError, binascii.Error) as error:
                raise ValueError("snapshot_entry_invalid") from error
            total += len(data)
            if len(data) > 256_000 or total > 4_000_000:
                raise ValueError("snapshot_too_large")
            files[path] = data
            records.append((path, False, hashlib.sha256(data).digest()))
    for path in seen:
        parent = PurePosixPath(path).parent
        while str(parent) != ".":
            if str(parent) not in directories:
                raise ValueError("snapshot_directory_missing")
            parent = parent.parent
    digest = hashlib.sha256(b"trace-local-source-snapshot\0v1\0")
    for path, directory, content_digest in sorted(records):
        encoded_path = path.encode("utf-8")
        digest.update(b"D" if directory else b"F")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        if content_digest is not None:
            digest.update(content_digest)
    if digest.hexdigest() != expected_digest:
        raise ValueError("snapshot_digest_mismatch")
    return files
