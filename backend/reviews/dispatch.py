"""Durable RabbitMQ publication for identifier-only review dispatch messages."""

from __future__ import annotations

import logging
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
from reviews.models import Review, ReviewDispatchJob, ReviewDispatchStatus, ReviewStatus
from reviews.queueing import ReviewDispatchMessageV1

try:  # Keep contract tests importable when optional runtime dependencies are absent.
    import pika
    from pika.exceptions import AMQPConnectionError, AMQPError
except ImportError:  # pragma: no cover - only an incomplete runtime reaches this path
    pika = None
    AMQPError = AMQPConnectionError = Exception


logger = logging.getLogger("trace.review_dispatch")

REVIEW_DISPATCH_EXCHANGE = "trace.review"
REVIEW_DISPATCH_QUEUE = "trace.review.dispatch.v1"
REVIEW_DISPATCH_ROUTING_KEY = "dispatch.v1"


class ReviewQueueUnavailable(RuntimeError):
    """RabbitMQ did not durably accept a review dispatch message."""


class ReviewDispatchChannel(Protocol):
    def exchange_declare(self, **kwargs: Any) -> Any: ...

    def queue_declare(self, **kwargs: Any) -> Any: ...

    def queue_bind(self, **kwargs: Any) -> Any: ...

    def confirm_delivery(self) -> Any: ...

    def basic_publish(self, **kwargs: Any) -> bool | None: ...


def declare_review_dispatch_topology(channel: ReviewDispatchChannel) -> None:
    """Declare the versioned, durable queue before publishing work."""

    channel.exchange_declare(
        exchange=REVIEW_DISPATCH_EXCHANGE,
        exchange_type="direct",
        durable=True,
    )
    channel.queue_declare(queue=REVIEW_DISPATCH_QUEUE, durable=True)
    channel.queue_bind(
        queue=REVIEW_DISPATCH_QUEUE,
        exchange=REVIEW_DISPATCH_EXCHANGE,
        routing_key=REVIEW_DISPATCH_ROUTING_KEY,
    )


class RabbitMQReviewPublisher:
    """Publish a reviewed assignment only after a broker confirmation."""

    def __init__(
        self,
        *,
        url: str,
        connection_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not url or len(url) > 2_048:
            raise ValueError("RabbitMQ URL is invalid")
        self._url = url
        self._connection_factory = connection_factory or _open_connection

    def publish(self, message: ReviewDispatchMessageV1) -> None:
        connection = None
        try:
            connection = self._connection_factory(self._url)
            channel = connection.channel()
            declare_review_dispatch_topology(channel)
            channel.confirm_delivery()
            delivered = channel.basic_publish(
                exchange=REVIEW_DISPATCH_EXCHANGE,
                routing_key=REVIEW_DISPATCH_ROUTING_KEY,
                body=message.encode(),
                properties=_persistent_properties(),
                mandatory=True,
            )
            if delivered is False:
                raise ReviewQueueUnavailable("RabbitMQ did not confirm delivery")
        except (AMQPError, AMQPConnectionError, OSError) as error:
            raise ReviewQueueUnavailable("RabbitMQ is unavailable") from error
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (AMQPError, OSError):
                    pass


def _open_connection(url: str) -> Any:
    if pika is None:
        raise ReviewQueueUnavailable("RabbitMQ client is not installed")
    parameters = pika.URLParameters(url)
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 5
    parameters.connection_attempts = 1
    parameters.retry_delay = 0
    return pika.BlockingConnection(parameters)


def _persistent_properties() -> Any:
    if pika is None:
        return {"delivery_mode": 2, "content_type": "application/json"}
    return pika.BasicProperties(delivery_mode=2, content_type="application/json")


@dataclass(frozen=True, slots=True)
class _Claim:
    idempotency_id: UUID
    owner_id: UUID
    review_id: UUID
    review_agent_id: UUID
    attempt_count: int


class ReviewDispatchWorker:
    """Claim and publish durable review work with at-least-once delivery."""

    def __init__(
        self,
        *,
        engine: Engine,
        publisher: RabbitMQReviewPublisher,
        audit_recorder: AuditRecorder | None = None,
        max_attempts: int = 8,
        retry_base_seconds: int = 5,
        retry_max_seconds: int = 900,
        processing_timeout_seconds: int = 300,
    ) -> None:
        if (
            max_attempts < 1
            or retry_base_seconds < 1
            or retry_max_seconds < retry_base_seconds
            or processing_timeout_seconds < 1
        ):
            raise ValueError("Review dispatch worker configuration is invalid")
        self._engine = engine
        self._publisher = publisher
        self._audit_recorder = audit_recorder
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._processing_timeout_seconds = processing_timeout_seconds

    def _claim(self) -> _Claim | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=self._processing_timeout_seconds)
        with self._engine.begin() as connection:
            job = (
                connection.execute(
                    sa.select(ReviewDispatchJob.__table__)
                    .where(
                        sa.or_(
                            sa.and_(
                                ReviewDispatchJob.status
                                == ReviewDispatchStatus.PENDING,
                                sa.or_(
                                    ReviewDispatchJob.next_attempt_at.is_(None),
                                    ReviewDispatchJob.next_attempt_at <= now,
                                ),
                            ),
                            sa.and_(
                                ReviewDispatchJob.status
                                == ReviewDispatchStatus.PROCESSING,
                                ReviewDispatchJob.updated_at <= stale_before,
                            ),
                        )
                    )
                    .order_by(
                        ReviewDispatchJob.created_at,
                        ReviewDispatchJob.idempotency_id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                return None
            attempt_count = job["attempt_count"] + 1
            connection.execute(
                sa.update(ReviewDispatchJob)
                .where(
                    ReviewDispatchJob.idempotency_id == job["idempotency_id"],
                    ReviewDispatchJob.status.in_(
                        (ReviewDispatchStatus.PENDING, ReviewDispatchStatus.PROCESSING)
                    ),
                )
                .values(
                    status=ReviewDispatchStatus.PROCESSING,
                    attempt_count=attempt_count,
                    claimed_at=now,
                    next_attempt_at=None,
                    updated_at=now,
                )
            )
            return _Claim(
                idempotency_id=job["idempotency_id"],
                owner_id=job["owner_id"],
                review_id=job["review_id"],
                review_agent_id=job["review_agent_id"],
                attempt_count=attempt_count,
            )

    def run_once(self) -> bool:
        claim = self._claim()
        if claim is None:
            return False
        if not self._review_is_queued(claim):
            self._cancel_claim(claim)
            return True
        message = ReviewDispatchMessageV1(
            review_id=claim.review_id,
            review_agent_id=claim.review_agent_id,
            owner_id=claim.owner_id,
            idempotency_id=claim.idempotency_id,
        )
        try:
            self._publisher.publish(message)
        except ReviewQueueUnavailable:
            self._retry_or_dead_letter(claim)
            return True
        self._mark_published(claim)
        return True

    def _review_is_queued(self, claim: _Claim) -> bool:
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    sa.select(Review.id).where(
                        Review.id == claim.review_id,
                        Review.owner_id == claim.owner_id,
                        Review.status == ReviewStatus.QUEUED,
                    )
                ).scalar_one_or_none()
                is not None
            )

    def _mark_published(self, claim: _Claim) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(ReviewDispatchJob)
                .where(
                    ReviewDispatchJob.idempotency_id == claim.idempotency_id,
                    ReviewDispatchJob.status == ReviewDispatchStatus.PROCESSING,
                )
                .values(
                    status=ReviewDispatchStatus.PUBLISHED,
                    published_at=now,
                    failure_code=None,
                    updated_at=now,
                )
            )
        if result.rowcount == 1:
            self._audit("review.dispatch.published", claim, {})

    def _retry_or_dead_letter(self, claim: _Claim) -> None:
        now = datetime.now(UTC)
        if claim.attempt_count >= self._max_attempts:
            self._terminal(
                claim,
                failure_code="publish_exhausted",
                event_type="review.dispatch.dead_letter",
            )
            return
        delay = min(
            self._retry_max_seconds,
            self._retry_base_seconds * (2 ** max(claim.attempt_count - 1, 0)),
        )
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(ReviewDispatchJob)
                .where(
                    ReviewDispatchJob.idempotency_id == claim.idempotency_id,
                    ReviewDispatchJob.status == ReviewDispatchStatus.PROCESSING,
                )
                .values(
                    status=ReviewDispatchStatus.PENDING,
                    next_attempt_at=now + timedelta(seconds=delay),
                    failure_code="broker_unavailable",
                    updated_at=now,
                )
            )
        if result.rowcount == 1:
            self._audit(
                "review.dispatch.retry_scheduled",
                claim,
                {"delay_seconds": str(delay), "failure_code": "broker_unavailable"},
            )

    def _cancel_claim(self, claim: _Claim) -> None:
        self._terminal(
            claim,
            failure_code="review_cancelled",
            event_type="review.dispatch.cancelled",
        )

    def _terminal(self, claim: _Claim, *, failure_code: str, event_type: str) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(ReviewDispatchJob)
                .where(
                    ReviewDispatchJob.idempotency_id == claim.idempotency_id,
                    ReviewDispatchJob.status == ReviewDispatchStatus.PROCESSING,
                )
                .values(
                    status=ReviewDispatchStatus.DEAD_LETTER,
                    failure_code=failure_code,
                    next_attempt_at=None,
                    updated_at=now,
                )
            )
        if result.rowcount == 1:
            self._audit(event_type, claim, {"failure_code": failure_code})

    def _audit(self, event_type: str, claim: _Claim, fields: dict[str, str]) -> None:
        enqueue_audit(
            self._audit_recorder,
            event_type=event_type,
            request_id=f"review-dispatch:{claim.idempotency_id}",
            owner_id=claim.owner_id,
            fields={
                "review_id": str(claim.review_id),
                "review_agent_id": str(claim.review_agent_id),
                "attempt_count": str(claim.attempt_count),
                **fields,
            },
        )

    def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)
