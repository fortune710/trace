"""Durable outbox publication for automatic remediation pull requests."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from audit.emit import enqueue_audit
from audit.outbox import AuditRecorder
from findings.models import Finding, FindingStatus
from remediations.models import (
    Remediation,
    RemediationPullRequestOutboxJob,
    RemediationPullRequestOutboxStatus,
    RemediationStatus,
)
from remediations.queueing import RemediationPullRequestMessageV1
from reviews.dispatch import _open_connection, _persistent_properties

try:
    from pika.exceptions import AMQPConnectionError, AMQPError
except ImportError:  # pragma: no cover
    AMQPError = AMQPConnectionError = Exception


REMEDIATION_PR_EXCHANGE = "trace.remediation"
REMEDIATION_PR_QUEUE = "trace.remediation.pull_request.v1"
REMEDIATION_PR_ROUTING_KEY = "pull_request.v1"
REMEDIATION_PR_DLX = "trace.remediation.pull_request.dlx"
REMEDIATION_PR_DEAD_LETTER_QUEUE = "trace.remediation.pull_request.dead_letter.v1"


class RemediationPullRequestQueueUnavailable(RuntimeError):
    pass


class RemediationPullRequestChannel(Protocol):
    def exchange_declare(self, **kwargs: Any) -> Any: ...
    def queue_declare(self, **kwargs: Any) -> Any: ...
    def queue_bind(self, **kwargs: Any) -> Any: ...
    def confirm_delivery(self) -> Any: ...
    def basic_publish(self, **kwargs: Any) -> bool | None: ...


def declare_remediation_pull_request_topology(
    channel: RemediationPullRequestChannel,
) -> None:
    channel.exchange_declare(
        exchange=REMEDIATION_PR_EXCHANGE,
        exchange_type="direct",
        durable=True,
    )
    channel.exchange_declare(
        exchange=REMEDIATION_PR_DLX,
        exchange_type="fanout",
        durable=True,
    )
    channel.queue_declare(
        queue=REMEDIATION_PR_QUEUE,
        durable=True,
        arguments={"x-dead-letter-exchange": REMEDIATION_PR_DLX},
    )
    channel.queue_declare(queue=REMEDIATION_PR_DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(
        queue=REMEDIATION_PR_QUEUE,
        exchange=REMEDIATION_PR_EXCHANGE,
        routing_key=REMEDIATION_PR_ROUTING_KEY,
    )
    channel.queue_bind(
        queue=REMEDIATION_PR_DEAD_LETTER_QUEUE,
        exchange=REMEDIATION_PR_DLX,
        routing_key="",
    )


class RabbitMQRemediationPullRequestPublisher:
    def __init__(
        self, *, url: str, connection_factory: Callable[[str], Any] | None = None
    ) -> None:
        if not url or len(url) > 2_048:
            raise ValueError("RabbitMQ URL is invalid")
        self._url = url
        self._connection_factory = connection_factory or _open_connection

    def publish(self, message: RemediationPullRequestMessageV1) -> None:
        connection = None
        try:
            connection = self._connection_factory(self._url)
            channel = connection.channel()
            declare_remediation_pull_request_topology(channel)
            channel.confirm_delivery()
            delivered = channel.basic_publish(
                exchange=REMEDIATION_PR_EXCHANGE,
                routing_key=REMEDIATION_PR_ROUTING_KEY,
                body=message.encode(),
                properties=_persistent_properties(),
                mandatory=True,
            )
            if delivered is False:
                raise RemediationPullRequestQueueUnavailable()
        except (AMQPError, AMQPConnectionError, OSError) as error:
            raise RemediationPullRequestQueueUnavailable() from error
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (AMQPError, OSError):
                    pass


@dataclass(frozen=True, slots=True)
class _Claim:
    idempotency_id: UUID
    owner_id: UUID
    remediation_id: UUID
    attempt_count: int


class RemediationPullRequestOutboxWorker:
    def __init__(
        self,
        *,
        engine: Engine,
        publisher: RabbitMQRemediationPullRequestPublisher,
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
            raise ValueError("Remediation PR outbox worker configuration is invalid")
        self._engine = engine
        self._publisher = publisher
        self._audit_recorder = audit_recorder
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._processing_timeout_seconds = processing_timeout_seconds

    def run_once(self) -> bool:
        if self._reconcile_waiting():
            return True
        claim = self._claim()
        if claim is None:
            return False
        if not self._still_publishable(claim):
            self._cancel(claim)
            return True
        try:
            self._publisher.publish(
                RemediationPullRequestMessageV1(
                    owner_id=claim.owner_id,
                    remediation_id=claim.remediation_id,
                    idempotency_id=claim.idempotency_id,
                )
            )
        except RemediationPullRequestQueueUnavailable:
            self._retry_or_dead_letter(claim)
            return True
        self._mark_published(claim)
        return True

    def _reconcile_waiting(self) -> bool:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(
                        RemediationPullRequestOutboxJob.__table__,
                        Finding.status.label("finding_status"),
                        Remediation.status.label("remediation_status"),
                    )
                    .select_from(RemediationPullRequestOutboxJob)
                    .join(
                        Remediation,
                        sa.and_(
                            Remediation.owner_id
                            == RemediationPullRequestOutboxJob.owner_id,
                            Remediation.id
                            == RemediationPullRequestOutboxJob.remediation_id,
                        ),
                    )
                    .join(
                        Finding,
                        sa.and_(
                            Finding.owner_id == Remediation.owner_id,
                            Finding.id == Remediation.finding_id,
                        ),
                    )
                    .where(
                        RemediationPullRequestOutboxJob.status
                        == RemediationPullRequestOutboxStatus.WAITING_FOR_ACCEPTANCE,
                        sa.or_(
                            Finding.status != FindingStatus.OPEN,
                            Remediation.status != RemediationStatus.PROPOSED,
                        ),
                    )
                    .order_by(RemediationPullRequestOutboxJob.created_at)
                    .with_for_update(
                        of=RemediationPullRequestOutboxJob,
                        skip_locked=True,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return False
            now = datetime.now(UTC)
            if (
                row["finding_status"] is FindingStatus.ACCEPTED
                and row["remediation_status"] is RemediationStatus.PROPOSED
            ):
                status = RemediationPullRequestOutboxStatus.PENDING
                failure_code = None
            else:
                status = RemediationPullRequestOutboxStatus.CANCELLED
                failure_code = "work_ineligible"
            connection.execute(
                sa.update(RemediationPullRequestOutboxJob)
                .where(
                    RemediationPullRequestOutboxJob.idempotency_id
                    == row["idempotency_id"]
                )
                .values(
                    status=status,
                    failure_code=failure_code,
                    updated_at=now,
                )
            )
        return True

    def _claim(self) -> _Claim | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=self._processing_timeout_seconds)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(RemediationPullRequestOutboxJob.__table__)
                    .where(
                        sa.or_(
                            sa.and_(
                                RemediationPullRequestOutboxJob.status
                                == RemediationPullRequestOutboxStatus.PENDING,
                                sa.or_(
                                    RemediationPullRequestOutboxJob.next_attempt_at.is_(
                                        None
                                    ),
                                    RemediationPullRequestOutboxJob.next_attempt_at
                                    <= now,
                                ),
                            ),
                            sa.and_(
                                RemediationPullRequestOutboxJob.status
                                == RemediationPullRequestOutboxStatus.PUBLISHING,
                                # The claim timestamp is the lease. Other operational
                                # updates must not accidentally extend a crashed
                                # publisher's exclusive ownership of this work.
                                RemediationPullRequestOutboxJob.claimed_at
                                <= stale_before,
                            ),
                        )
                    )
                    .order_by(
                        RemediationPullRequestOutboxJob.created_at,
                        RemediationPullRequestOutboxJob.idempotency_id,
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
                sa.update(RemediationPullRequestOutboxJob)
                .where(
                    RemediationPullRequestOutboxJob.idempotency_id
                    == row["idempotency_id"]
                )
                .values(
                    status=RemediationPullRequestOutboxStatus.PUBLISHING,
                    attempt_count=attempt_count,
                    claimed_at=now,
                    next_attempt_at=None,
                    updated_at=now,
                )
            )
        return _Claim(
            idempotency_id=row["idempotency_id"],
            owner_id=row["owner_id"],
            remediation_id=row["remediation_id"],
            attempt_count=attempt_count,
        )

    def _still_publishable(self, claim: _Claim) -> bool:
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    sa.select(Remediation.id)
                    .join(
                        Finding,
                        sa.and_(
                            Finding.owner_id == Remediation.owner_id,
                            Finding.id == Remediation.finding_id,
                        ),
                    )
                    .where(
                        Remediation.id == claim.remediation_id,
                        Remediation.owner_id == claim.owner_id,
                        Remediation.status == RemediationStatus.PROPOSED,
                        Finding.status == FindingStatus.ACCEPTED,
                    )
                ).scalar_one_or_none()
                is not None
            )

    def _mark_published(self, claim: _Claim) -> None:
        self._update_claim(
            claim,
            status=RemediationPullRequestOutboxStatus.PUBLISHED,
            published_at=datetime.now(UTC),
            failure_code=None,
        )
        self._audit("remediation.pull_request.outbox_published", claim, {})

    def _retry_or_dead_letter(self, claim: _Claim) -> None:
        if claim.attempt_count >= self._max_attempts:
            self._update_claim(
                claim,
                status=RemediationPullRequestOutboxStatus.DEAD_LETTER,
                failure_code="broker_unavailable",
            )
            self._audit(
                "remediation.pull_request.outbox_dead_letter",
                claim,
                {"failure_code": "broker_unavailable"},
            )
            return
        delay = min(
            self._retry_max_seconds,
            self._retry_base_seconds * (2 ** (claim.attempt_count - 1)),
        )
        self._update_claim(
            claim,
            status=RemediationPullRequestOutboxStatus.PENDING,
            next_attempt_at=datetime.now(UTC) + timedelta(seconds=delay),
            failure_code="broker_unavailable",
        )
        self._audit(
            "remediation.pull_request.outbox_retry_scheduled",
            claim,
            {"delay_seconds": str(delay)},
        )

    def _cancel(self, claim: _Claim) -> None:
        self._update_claim(
            claim,
            status=RemediationPullRequestOutboxStatus.CANCELLED,
            failure_code="work_ineligible",
        )
        self._audit("remediation.pull_request.outbox_cancelled", claim, {})

    def _update_claim(
        self,
        claim: _Claim,
        *,
        status: RemediationPullRequestOutboxStatus,
        next_attempt_at: datetime | None = None,
        published_at: datetime | None = None,
        failure_code: str | None,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(RemediationPullRequestOutboxJob)
                .where(
                    RemediationPullRequestOutboxJob.idempotency_id
                    == claim.idempotency_id,
                    RemediationPullRequestOutboxJob.status
                    == RemediationPullRequestOutboxStatus.PUBLISHING,
                )
                .values(
                    status=status,
                    next_attempt_at=next_attempt_at,
                    published_at=published_at,
                    failure_code=failure_code,
                    updated_at=datetime.now(UTC),
                )
            )

    def _audit(self, event_type: str, claim: _Claim, fields: dict[str, str]) -> None:
        enqueue_audit(
            self._audit_recorder,
            event_type=event_type,
            request_id=f"remediation-pr-outbox:{claim.idempotency_id}",
            owner_id=claim.owner_id,
            fields={"remediation_id": str(claim.remediation_id), **fields},
        )

    def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)
