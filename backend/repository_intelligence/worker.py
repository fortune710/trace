"""Unpaid, revision-pinned GitHub intelligence worker."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from auth.config import AuthSettings
from auth.credential_service import CredentialService
from auth.credentials import credential_cipher_from_settings
from db.rls import principal_transaction
from db.session import get_engine
from external_repositories.service import (
    GitHubRequestLogContext,
    RepositoryService,
    ReviewSourceFileError,
)
from repository_intelligence import models
from repository_intelligence.service import persist_analysis

logger = logging.getLogger("trace.repository_intelligence")


class IntelligenceWorker:
    def __init__(self, engine: Engine, repository_service: RepositoryService) -> None:
        self.engine = engine
        self.repository_service = repository_service

    def run_once(self) -> bool:
        with self.engine.begin() as connection:
            item = (
                connection.execute(
                    sa.select(models.snapshot)
                    .where(
                        models.snapshot.c.source_kind == "github",
                        models.snapshot.c.attempt_count < 3,
                        sa.or_(
                            models.snapshot.c.status == "pending",
                            sa.and_(
                                models.snapshot.c.status == "running",
                                models.snapshot.c.claimed_at
                                < datetime.now(UTC) - timedelta(minutes=10),
                            ),
                        ),
                    )
                    .order_by(models.snapshot.c.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if item is None:
                return False
            snapshot_id: UUID = item["id"]
            owner_id: UUID = item["owner_id"]
            source_identifier: str = item["source_identifier"]
            revision: str = item["source_revision"]
            connection.execute(
                sa.update(models.snapshot)
                .where(models.snapshot.c.id == snapshot_id)
                .values(
                    status="running",
                    claimed_at=datetime.now(UTC),
                    attempt_count=item["attempt_count"] + 1,
                )
            )
        try:
            files: dict[str, bytes] = {}
            skipped_files = 0
            with self.repository_service.open_review_github_source_access(
                owner_id=owner_id,
                repository_identifier=source_identifier,
                revision=revision,
            ) as reader:
                context = GitHubRequestLogContext(review_id=snapshot_id)
                paths, truncated, _skipped = reader.list_paths(
                    path_prefix=None,
                    max_results=500,
                    log_context=context,
                )
                for path in paths:
                    try:
                        files[path] = reader.read_file(
                            path=path, log_context=context
                        ).encode("utf-8")
                    except ReviewSourceFileError:
                        skipped_files += 1
                        continue
            with principal_transaction(self.engine, owner_id) as connection:
                persist_analysis(
                    connection,
                    owner_id=owner_id,
                    snapshot_id=snapshot_id,
                    source_kind="github",
                    source_identifier=source_identifier,
                    revision=revision,
                    files=files,
                    source_truncated=truncated,
                    source_skipped_files=skipped_files,
                )
        except Exception:
            logger.exception(
                "intelligence_analysis_failed", extra={"snapshot_id": str(snapshot_id)}
            )
            with principal_transaction(self.engine, owner_id) as connection:
                connection.execute(
                    sa.update(models.snapshot)
                    .where(models.snapshot.c.id == snapshot_id)
                    .values(
                        status="pending" if item["attempt_count"] < 2 else "failed",
                        claimed_at=None,
                    )
                )
        return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    engine = get_engine()
    settings = AuthSettings()
    credentials = CredentialService(
        engine=engine,
        cipher=credential_cipher_from_settings(settings, validate_authentication=False),
    )
    worker = IntelligenceWorker(
        engine,
        RepositoryService(
            engine=engine, credential_service=credentials, settings=settings
        ),
    )
    while True:
        if not worker.run_once():
            time.sleep(2)


if __name__ == "__main__":
    main()
