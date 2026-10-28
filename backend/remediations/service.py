"""Owner-scoped remediation pull-request publication."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from audit.outbox import AuditRecorder
from auth.errors import (
    ProviderRateLimited,
    ProviderUnavailable,
    ResourceConflict,
    UnsupportedSource,
)
from db.rls import principal_transaction
from db.types import RepositorySource
from external_repositories.service import RepositoryService
from findings.models import Finding, FindingStatus
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
                    .with_for_update()
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


__all__ = ["RemediationPullRequestService"]
