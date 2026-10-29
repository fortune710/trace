"""Durably retry failed remediation pull-request publications."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from audit.emit import enqueue_audit
from audit.outbox import AuditRecorder
from auth.errors import AuthError, ProviderRateLimited, ProviderUnavailable
from notifications.models import NotificationEventType
from notifications.service import create_notification
from remediations.models import (
    RemediationPullRequestJob,
    RemediationPullRequestJobStatus,
)
from remediations.service import RemediationPullRequestService


@dataclass(frozen=True, slots=True)
class _Claim:
    id: UUID
    owner_id: UUID
    remediation_id: UUID
    attempt_count: int


class RemediationPullRequestWorker:
    """Claims one private retry job at a time using PostgreSQL row locks."""

    def __init__(
        self,
        *,
        engine: Engine,
        service: RemediationPullRequestService,
        audit_recorder: AuditRecorder | None = None,
        max_attempts: int = 3,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 300,
        processing_timeout_seconds: int = 300,
    ) -> None:
        if (
            max_attempts != 3
            or retry_base_seconds < 1
            or retry_max_seconds < retry_base_seconds
            or processing_timeout_seconds < 1
        ):
            raise ValueError("Remediation pull-request worker configuration is invalid")
        self._engine = engine
        self._service = service
        self._audit_recorder = audit_recorder
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._processing_timeout_seconds = processing_timeout_seconds

    def run_once(self) -> bool:
        claim = self._claim()
        if claim is None:
            return False
        try:
            self._service.publish_queued(
                owner_id=claim.owner_id,
                remediation_id=claim.remediation_id,
                request_id=f"remediation-pr-worker:{claim.id}",
            )
        except (ProviderRateLimited, ProviderUnavailable):
            self._retry_or_dead_letter(claim)
        except AuthError:
            # A malformed remediation or a non-retryable provider response cannot
            # be repaired by repeated publication attempts. Do not record contents.
            self._dead_letter(claim, failure_code="publication_failed")
        else:
            self._mark_succeeded(claim)
        return True

    def _claim(self) -> _Claim | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=self._processing_timeout_seconds)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(RemediationPullRequestJob.__table__)
                    .where(
                        sa.or_(
                            sa.and_(
                                RemediationPullRequestJob.status
                                == RemediationPullRequestJobStatus.PENDING,
                                sa.or_(
                                    RemediationPullRequestJob.next_attempt_at.is_(None),
                                    RemediationPullRequestJob.next_attempt_at <= now,
                                ),
                            ),
                            sa.and_(
                                RemediationPullRequestJob.status
                                == RemediationPullRequestJobStatus.PROCESSING,
                                RemediationPullRequestJob.updated_at <= stale_before,
                            ),
                        )
                    )
                    .order_by(
                        RemediationPullRequestJob.created_at,
                        RemediationPullRequestJob.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            attempt_count = int(row["attempt_count"]) + 1
            connection.execute(
                sa.update(RemediationPullRequestJob)
                .where(
                    RemediationPullRequestJob.id == row["id"],
                    RemediationPullRequestJob.status.in_(
                        (
                            RemediationPullRequestJobStatus.PENDING,
                            RemediationPullRequestJobStatus.PROCESSING,
                        )
                    ),
                )
                .values(
                    status=RemediationPullRequestJobStatus.PROCESSING,
                    attempt_count=attempt_count,
                    claimed_at=now,
                    next_attempt_at=None,
                    updated_at=now,
                )
            )
        return _Claim(
            id=row["id"],
            owner_id=row["owner_id"],
            remediation_id=row["remediation_id"],
            attempt_count=attempt_count,
        )

    def _mark_succeeded(self, claim: _Claim) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(RemediationPullRequestJob)
                .where(
                    RemediationPullRequestJob.id == claim.id,
                    RemediationPullRequestJob.status
                    == RemediationPullRequestJobStatus.PROCESSING,
                )
                .values(
                    status=RemediationPullRequestJobStatus.SUCCEEDED,
                    succeeded_at=now,
                    failure_code=None,
                    updated_at=now,
                )
            )
        if result.rowcount == 1:
            self._audit("remediation.pull_request.retry_succeeded", claim, {})

    def _retry_or_dead_letter(self, claim: _Claim) -> None:
        if claim.attempt_count >= self._max_attempts:
            self._dead_letter(claim, failure_code="publication_exhausted")
            return
        delay = min(
            self._retry_max_seconds,
            self._retry_base_seconds * (2 ** (claim.attempt_count - 1)),
        )
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(RemediationPullRequestJob)
                .where(
                    RemediationPullRequestJob.id == claim.id,
                    RemediationPullRequestJob.status
                    == RemediationPullRequestJobStatus.PROCESSING,
                )
                .values(
                    status=RemediationPullRequestJobStatus.PENDING,
                    next_attempt_at=now + timedelta(seconds=delay),
                    failure_code="provider_unavailable",
                    updated_at=now,
                )
            )
        if result.rowcount == 1:
            self._audit(
                "remediation.pull_request.retry_scheduled",
                claim,
                {"delay_seconds": str(delay), "failure_code": "provider_unavailable"},
            )

    def _dead_letter(self, claim: _Claim, *, failure_code: str) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(RemediationPullRequestJob)
                .where(
                    RemediationPullRequestJob.id == claim.id,
                    RemediationPullRequestJob.status
                    == RemediationPullRequestJobStatus.PROCESSING,
                )
                .values(
                    status=RemediationPullRequestJobStatus.DEAD_LETTER,
                    next_attempt_at=None,
                    failure_code=failure_code,
                    updated_at=now,
                )
            )
            if result.rowcount == 1:
                create_notification(
                    connection,
                    owner_id=claim.owner_id,
                    event_type=NotificationEventType.PULL_REQUEST_CREATION_FAILED,
                    dedupe_key=(
                        f"remediation:{claim.remediation_id}:pull-request-failed"
                    ),
                    data={"remediation_id": str(claim.remediation_id)},
                )
        if result.rowcount == 1:
            self._audit(
                "remediation.pull_request.retry_dead_letter",
                claim,
                {"failure_code": failure_code},
            )

    def _audit(self, event_type: str, claim: _Claim, fields: dict[str, str]) -> None:
        enqueue_audit(
            self._audit_recorder,
            event_type=event_type,
            request_id=f"remediation-pr-worker:{claim.id}",
            owner_id=claim.owner_id,
            fields={
                "remediation_id": str(claim.remediation_id),
                "attempt_count": str(claim.attempt_count),
                **fields,
            },
        )

    def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)
