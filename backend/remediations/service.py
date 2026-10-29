"""Owner-scoped remediation pull-request publication."""

from __future__ import annotations

import re
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from artifacts.models import LocalFileBackup
from audit.outbox import AuditRecorder
from auth.errors import (
    AuthError,
    ProviderRateLimited,
    ProviderUnavailable,
    ResourceConflict,
    UnsupportedSource,
)
from db.rls import principal_transaction
from db.types import RepositorySource
from external_repositories.service import RepositoryService
from findings.models import Finding, FindingStatus
from notifications.models import NotificationEventType
from notifications.service import create_notification
from projects.models import Project
from remediations.models import (
    Remediation,
    RemediationPullRequestJob,
    RemediationStatus,
)
from resources.services import _raise_access, _remediation_response
from reviews.models import Review, ReviewStatus


class RemediationPullRequestService:
    def __init__(
        self,
        engine: Engine,
        repository_service: RepositoryService,
        audit_recorder: AuditRecorder | None = None,
    ) -> None:
        self._engine = engine
        self._repository_service = repository_service
        self._audit_recorder = audit_recorder

    def create(
        self, *, owner_id: UUID, remediation_id: UUID, request_id: str
    ) -> tuple[dict[str, object], bool]:
        try:
            return (
                self._publish(
                    owner_id=owner_id,
                    remediation_id=remediation_id,
                    request_id=request_id,
                ),
                False,
            )
        except (ProviderRateLimited, ProviderUnavailable):
            return (
                self.enqueue_retry(
                    owner_id=owner_id,
                    remediation_id=remediation_id,
                    request_id=request_id,
                ),
                True,
            )
        except AuthError as error:
            if error.event in {"provider", "request"}:
                self._record_creation_failure(
                    owner_id=owner_id,
                    remediation_id=remediation_id,
                )
            raise

    def publish_queued(
        self, *, owner_id: UUID, remediation_id: UUID, request_id: str
    ) -> dict[str, object]:
        """Publish one durable retry without recursively enqueueing another job."""
        return self._publish(
            owner_id=owner_id,
            remediation_id=remediation_id,
            request_id=request_id,
        )

    def _publish(
        self, *, owner_id: UUID, remediation_id: UUID, request_id: str
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"
                ),
                {"key": str(remediation_id)},
            )
            context = (
                connection.execute(
                    sa.select(
                        Remediation.__table__,
                        Finding.status.label("finding_status"),
                        Finding.title.label("finding_title"),
                        Review.status.label("review_status"),
                        Review.id.label("review_id"),
                        Review.source_revision,
                        Project.source.label("project_source"),
                        Project.external_repository_id,
                        Project.branch_name,
                    )
                    .select_from(Remediation)
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
                    .join(
                        Project,
                        sa.and_(
                            Project.owner_id == Remediation.owner_id,
                            Project.id == Remediation.project_id,
                        ),
                    )
                    .where(
                        Remediation.id == remediation_id,
                        Remediation.owner_id == owner_id,
                    )
                    .with_for_update(of=Remediation.__table__)
                )
                .mappings()
                .one_or_none()
            )
            if context is None:
                _raise_access(connection, "remediation", remediation_id)
            assert context is not None
            existing = context["pull_request"]
            if isinstance(existing, dict):
                return _remediation_response(context)
            if context["status"] is not RemediationStatus.PROPOSED:
                raise ResourceConflict("remediation_state_conflict")
            if context["finding_status"] is not FindingStatus.ACCEPTED:
                raise ResourceConflict("finding_not_accepted")
            if context["review_status"] is not ReviewStatus.COMPLETED:
                raise ResourceConflict("review_not_completed")
            if context["project_source"] is not RepositorySource.GITHUB:
                raise UnsupportedSource()
            repository_id = context["external_repository_id"]
            branch_name = context["branch_name"]
            if not isinstance(repository_id, str) or not isinstance(branch_name, str):
                raise ResourceConflict("project_repository_invalid")
            published = self._repository_service.publish_remediation_pull_request(
                owner_id=owner_id,
                repository_identifier=repository_id,
                source_revision=str(context["source_revision"]),
                base_branch=branch_name,
                remediation_id=remediation_id,
                diff=str(context["proposed_diff"]),
                finding_title=str(context["finding_title"]),
            )
            pull_request: dict[str, object] = {
                "url": published.url,
                "number": published.number,
                "is_merged": published.is_merged,
            }
            connection.execute(
                sa.update(Remediation)
                .where(
                    Remediation.id == remediation_id, Remediation.owner_id == owner_id
                )
                .values(
                    pull_request=pull_request,
                    status=RemediationStatus.APPLIED,
                    approved_at=sa.func.current_timestamp(),
                    mutation_version=Remediation.mutation_version + 1,
                    updated_at=sa.func.current_timestamp(),
                )
            )
            create_notification(
                connection,
                owner_id=owner_id,
                event_type=NotificationEventType.PULL_REQUEST_CREATED,
                dedupe_key=f"remediation:{remediation_id}:pull-request-created",
                action_path=published.url,
                data={
                    "remediation_id": str(remediation_id),
                    "pull_request_number": published.number,
                },
            )
            if self._audit_recorder is not None:
                self._audit_recorder.create_event(
                    event_type="remediation.pull_request.created",
                    request_id=request_id,
                    owner_id=owner_id,
                    fields={
                        "remediation_id": str(remediation_id),
                        "number": str(published.number),
                    },
                    connection=connection,
                )
            row = (
                connection.execute(
                    sa.select(Remediation.__table__).where(
                        Remediation.id == remediation_id,
                        Remediation.owner_id == owner_id,
                    )
                )
                .mappings()
                .one()
            )
        return _remediation_response(row)

    def _record_creation_failure(self, *, owner_id: UUID, remediation_id: UUID) -> None:
        """Persist one safe notification for a non-retryable request failure."""

        with principal_transaction(self._engine, owner_id) as connection:
            context = (
                connection.execute(
                    sa.select(
                        Remediation.finding_id,
                        Finding.review_id,
                    )
                    .join(
                        Finding,
                        sa.and_(
                            Finding.owner_id == Remediation.owner_id,
                            Finding.id == Remediation.finding_id,
                        ),
                    )
                    .where(
                        Remediation.owner_id == owner_id,
                        Remediation.id == remediation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if context is None:
                return
            create_notification(
                connection,
                owner_id=owner_id,
                event_type=NotificationEventType.PULL_REQUEST_CREATION_FAILED,
                dedupe_key=f"remediation:{remediation_id}:pull-request-failed",
                action_path=(
                    f"/reviews/{context['review_id']}/findings/{context['finding_id']}"
                ),
                data={"remediation_id": str(remediation_id)},
            )

    def enqueue_retry(
        self, *, owner_id: UUID, remediation_id: UUID, request_id: str
    ) -> dict[str, object]:
        """Durably retain a retry request without exposing provider failure details."""
        with principal_transaction(self._engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.select(Remediation.__table__).where(
                        Remediation.id == remediation_id,
                        Remediation.owner_id == owner_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                _raise_access(connection, "remediation", remediation_id)
            assert row is not None
            if isinstance(row["pull_request"], dict) or (
                row["status"] is not RemediationStatus.PROPOSED
            ):
                return _remediation_response(row)
            result = connection.execute(
                pg_insert(RemediationPullRequestJob)
                .values(owner_id=owner_id, remediation_id=remediation_id)
                .on_conflict_do_nothing(
                    constraint="remediation_pull_request_jobs_owner_remediation_key"
                )
            )
            if result.rowcount == 1 and self._audit_recorder is not None:
                self._audit_recorder.create_event(
                    event_type="remediation.pull_request.retry_queued",
                    request_id=request_id,
                    owner_id=owner_id,
                    fields={"remediation_id": str(remediation_id)},
                    connection=connection,
                )
        return _remediation_response(row)


class LocalRemediationApplyService:
    """Record an already-completed, desktop-local remediation apply operation.

    The desktop owns filesystem access and only reports path-relative metadata.
    This service never receives an absolute path or file contents.
    """

    def __init__(
        self, engine: Engine, audit_recorder: AuditRecorder | None = None
    ) -> None:
        self._engine = engine
        self._audit_recorder = audit_recorder

    def complete(
        self,
        *,
        owner_id: UUID,
        remediation_id: UUID,
        files: list[dict[str, str]],
        request_id: str,
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"
                ),
                {"key": str(remediation_id)},
            )
            context = (
                connection.execute(
                    sa.select(
                        Remediation.__table__,
                        Finding.status.label("finding_status"),
                        Review.status.label("review_status"),
                        Project.source.label("project_source"),
                    )
                    .select_from(Remediation)
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
                    .join(
                        Project,
                        sa.and_(
                            Project.owner_id == Remediation.owner_id,
                            Project.id == Remediation.project_id,
                        ),
                    )
                    .where(
                        Remediation.id == remediation_id,
                        Remediation.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if context is None:
                _raise_access(connection, "remediation", remediation_id)
            assert context is not None
            existing = (
                connection.execute(
                    sa.select(LocalFileBackup).where(
                        LocalFileBackup.owner_id == owner_id,
                        LocalFileBackup.remediation_id == remediation_id,
                    )
                )
                .scalars()
                .all()
            )
            if existing:
                return _remediation_response(context)
            if context["project_source"] is not RepositorySource.LOCAL:
                raise UnsupportedSource()
            if context["status"] is not RemediationStatus.PROPOSED:
                raise ResourceConflict("remediation_state_conflict")
            if context["finding_status"] is not FindingStatus.ACCEPTED:
                raise ResourceConflict("finding_not_accepted")
            if context["review_status"] is not ReviewStatus.COMPLETED:
                raise ResourceConflict("review_not_completed")
            expected_paths = _remediation_diff_paths(str(context["proposed_diff"]))
            supplied_paths = {file["file_path"] for file in files}
            if (
                supplied_paths != expected_paths
                or len(files) != len(supplied_paths)
                or any(
                    file["backup_reference"]
                    != f"local-remediation-backups/{remediation_id}/{file['file_path']}"
                    for file in files
                )
            ):
                raise ResourceConflict("remediation_file_mismatch")
            connection.execute(
                sa.insert(LocalFileBackup),
                [
                    {
                        "owner_id": owner_id,
                        "remediation_id": remediation_id,
                        "file_path": file["file_path"],
                        "backup_path": file["backup_reference"],
                        "source_hash": bytes.fromhex(file["source_hash"]),
                        "applied_hash": bytes.fromhex(file["applied_hash"]),
                    }
                    for file in files
                ],
            )
            connection.execute(
                sa.update(Remediation)
                .where(
                    Remediation.id == remediation_id,
                    Remediation.owner_id == owner_id,
                    Remediation.status == RemediationStatus.PROPOSED,
                )
                .values(
                    status=RemediationStatus.APPLIED,
                    approved_at=sa.func.current_timestamp(),
                    mutation_version=Remediation.mutation_version + 1,
                    updated_at=sa.func.current_timestamp(),
                )
            )
            if self._audit_recorder is not None:
                self._audit_recorder.create_event(
                    event_type="remediation.local_file.applied",
                    request_id=request_id,
                    owner_id=owner_id,
                    fields={
                        "remediation_id": str(remediation_id),
                        "file_count": str(len(files)),
                    },
                    connection=connection,
                )
            row = (
                connection.execute(
                    sa.select(Remediation.__table__).where(
                        Remediation.id == remediation_id,
                        Remediation.owner_id == owner_id,
                    )
                )
                .mappings()
                .one()
            )
        return _remediation_response(row)


def _remediation_diff_paths(diff: str) -> set[str]:
    paths: set[str] = set()
    for line in diff.splitlines():
        match = re.fullmatch(r"diff --git a/([^\s]+) b/([^\s]+)", line)
        if match is None:
            continue
        old_path, new_path = match.groups()
        if (
            old_path != new_path
            or not old_path
            or old_path.startswith("/")
            or "\\" in old_path
            or any(segment in {"", ".", ".."} for segment in old_path.split("/"))
        ):
            raise ResourceConflict("remediation_file_mismatch")
        if old_path in paths:
            raise ResourceConflict("remediation_file_mismatch")
        paths.add(old_path)
    if not paths:
        raise ResourceConflict("remediation_file_mismatch")
    return paths


__all__ = ["LocalRemediationApplyService", "RemediationPullRequestService"]
