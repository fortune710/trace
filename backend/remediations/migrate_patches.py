"""Explicit, non-AI validation/encryption of historical remediation patches.

Dry run: python -m remediations.migrate_patches --owner UUID
Write verified artifacts: add --apply. No review or model request is initiated.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa

from agents.execution.diagnostics import PatchGenerationError
from agents.execution.patches import build_patch, run_git
from agents.execution.source import patch_paths
from auth.config import AuthSettings
from auth.credential_service import CredentialService
from auth.credentials import credential_cipher_from_settings
from db.rls import principal_transaction
from db.session import get_engine
from external_repositories.service import (
    GitHubRequestLogContext,
    RepositoryService,
    ReviewSourceFileError,
    _is_safe_patch,
)
from findings.models import Finding
from remediations.models import Remediation, RemediationStatus
from remediations.patch_store import PatchStore
from repository_intelligence.local_source import LocalReviewSourceAccess
from reviews.models import Review


def validate_legacy_patch(diff, reader, snapshot, log_context=None):
    if len(diff.encode()) > 1_048_576 or not _is_safe_patch(diff):
        raise PatchGenerationError(
            "legacy_patch_unsupported", stage="structure", retryable=False
        )
    originals = {}
    for path in patch_paths(diff):
        try:
            originals[path] = reader.read_file(path=path, log_context=log_context)
        except ReviewSourceFileError as error:
            if error.code != "path_not_found":
                raise
            originals[path] = None
    with tempfile.TemporaryDirectory(prefix="trace-legacy-patch-") as directory:
        root = Path(directory)
        run_git(root, "init", "-q")
        (root / ".git/info/attributes").write_text(
            "* -text -filter -ident -working-tree-encoding\n"
        )
        for path, content in originals.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if content is not None:
                target.write_bytes(content.encode())
        run_git(
            root, "apply", "--check", "--whitespace=nowarn", "-", data=diff.encode()
        )
        run_git(root, "apply", "--whitespace=nowarn", "-", data=diff.encode())
        updated = {
            path: (root / path).read_bytes().decode("utf-8") for path in originals
        }
    # The legacy text only proves which bytes the change produces. Store the patch
    # Git serializes from those verified before/after bytes, so the artifact, its
    # hash, and its per-file hashes describe exactly the same change.
    return build_patch(original=originals, updated=updated, snapshot=snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", type=UUID, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("limit must be between 1 and 1000")
    engine = get_engine()
    settings = AuthSettings()
    cipher = credential_cipher_from_settings(settings, validate_authentication=False)
    store = PatchStore(engine, cipher)
    repositories = RepositoryService(
        engine=engine,
        credential_service=CredentialService(engine=engine, cipher=cipher),
        settings=settings,
    )
    with principal_transaction(engine, args.owner) as connection:
        rows = (
            connection.execute(
                sa.select(
                    Remediation.id,
                    Remediation.proposed_diff,
                    Review.id.label("review_id"),
                    Review.source_kind,
                    Review.source_identifier,
                    Review.source_revision,
                )
                .join(
                    Finding,
                    sa.and_(
                        Finding.owner_id == Remediation.owner_id,
                        Finding.id == Remediation.finding_id,
                    ),
                )
                .join(
                    Review,
                    sa.and_(
                        Review.owner_id == Finding.owner_id,
                        Review.id == Finding.review_id,
                    ),
                )
                .where(
                    Remediation.owner_id == args.owner,
                    Remediation.generation_status == "legacy_unverified",
                    Remediation.status == RemediationStatus.PROPOSED,
                )
                .order_by(Remediation.id)
                .limit(args.limit)
            )
            .mappings()
            .all()
        )
    for row in rows:
        reader = None
        try:
            kind = row["source_kind"].value
            snapshot = {
                "source_kind": kind,
                "source_identifier": row["source_identifier"],
                "revision": row["source_revision"],
            }
            if kind == "local":
                reader = LocalReviewSourceAccess.open(
                    engine=engine,
                    owner_id=args.owner,
                    review_id=row["review_id"],
                    revision=row["source_revision"],
                    cipher=cipher,
                )
            elif kind == "github":
                reader = repositories.open_review_github_source_access(
                    owner_id=args.owner,
                    repository_identifier=row["source_identifier"],
                    revision=row["source_revision"],
                )
            else:
                raise PatchGenerationError(
                    "source_execution_unsupported", stage="source", retryable=False
                )
            patch = validate_legacy_patch(
                row["proposed_diff"],
                reader,
                snapshot,
                GitHubRequestLogContext(review_id=row["review_id"]),
            )
            if args.apply:
                store.save(owner_id=args.owner, remediation_id=row["id"], patch=patch)
            print(
                json.dumps(
                    {
                        "remediation_id": str(row["id"]),
                        "outcome": "ready",
                        "applied": args.apply,
                    }
                )
            )
        except Exception as error:  # noqa: BLE001 - safe maintenance reporting, never print source exceptions.
            diagnostic = (
                error.diagnostic()
                if isinstance(error, PatchGenerationError)
                else {
                    "code": "legacy_patch_validation_unavailable",
                    "message": "Historical patch validation failed.",
                }
            )
            if args.apply:
                store.fail(
                    owner_id=args.owner, remediation_id=row["id"], diagnostic=diagnostic
                )
            print(
                json.dumps(
                    {
                        "remediation_id": str(row["id"]),
                        "outcome": "unavailable",
                        "diagnostic": diagnostic,
                        "applied": args.apply,
                    }
                )
            )
        finally:
            if hasattr(reader, "close"):
                reader.close()


if __name__ == "__main__":
    main()
