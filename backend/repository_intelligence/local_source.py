"""Revision-bound local source reader for uploaded encrypted snapshots."""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from auth.credentials import (
    CredentialCipher,
    EncryptedCredential,
    VaultTransitCredentialCipher,
)
from db.rls import principal_transaction
from external_repositories.service import (
    ReviewSourceFileError,
    _is_excluded_review_path,
    _is_safe_patch,
)
from repository_intelligence.models import local_source


def _safe_path(path: str) -> bool:
    return (
        bool(path)
        and path != "."
        and not path.startswith("/")
        and "\\" not in path
        and "\0" not in path
        and str(PurePosixPath(path)) == path
        and ".." not in PurePosixPath(path).parts
    )


class LocalReviewSourceAccess:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    @classmethod
    def open(
        cls,
        *,
        engine: Engine,
        owner_id: UUID,
        review_id: UUID,
        revision: str,
        cipher: CredentialCipher | VaultTransitCredentialCipher,
    ) -> LocalReviewSourceAccess:
        with principal_transaction(engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.select(local_source).where(
                        local_source.c.owner_id == owner_id,
                        local_source.c.review_id == review_id,
                        local_source.c.source_revision == revision,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ValueError("local_source_snapshot_unavailable")
        decoded = cipher.decrypt_json(
            EncryptedCredential(
                ciphertext=row["ciphertext"],
                nonce=row["nonce"],
                key_version=row["key_version"],
                encryption_provider=row["encryption_provider"],
                key_reference=row["key_reference"],
            ),
            credential_id=review_id,
            owner_id=owner_id,
            provider="local",
            credential_kind="review_snapshot",
        )
        files = decoded.get("files")
        if not isinstance(files, dict):
            raise TypeError("local_source_snapshot_invalid")
        return cls(
            {
                path: base64.b64decode(data, validate=True)
                for path, data in files.items()
            }
        )

    def list_paths(
        self, *, path_prefix: str | None, max_results: int, log_context: object
    ) -> tuple[list[str], bool, int]:
        del log_context
        if path_prefix is not None and not _safe_path(path_prefix):
            raise ReviewSourceFileError("path_invalid")
        paths = [
            path
            for path in sorted(self.files)
            if not _is_excluded_review_path(path)
            if path_prefix is None or path.startswith(path_prefix.rstrip("/") + "/")
        ]
        return (
            paths[:max_results],
            len(paths) > max_results,
            sum(_is_excluded_review_path(path) for path in self.files),
        )

    def read_file(self, *, path: str, log_context: object) -> str:
        del log_context
        if not _safe_path(path) or path not in self.files:
            raise ReviewSourceFileError("path_not_found")
        if _is_excluded_review_path(path):
            raise ReviewSourceFileError("path_excluded")
        try:
            return self.files[path].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReviewSourceFileError("file_not_utf8") from error

    def validate_diff(self, *, diff: str, log_context: object) -> bool:
        del log_context
        if not _is_safe_patch(diff):
            return False
        with tempfile.TemporaryDirectory(prefix="trace-local-diff-") as directory:
            root = Path(directory)
            for path, data in self.files.items():
                if not _safe_path(path):
                    return False
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            result = subprocess.run(
                ["git", "apply", "--check", "--whitespace=nowarn", "-"],
                cwd=root,
                input=diff.encode(),
                capture_output=True,
                timeout=10,
                check=False,
            )
            return result.returncode == 0
