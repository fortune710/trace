from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pika
import pytest
import sqlalchemy as sa

from agents.models import Agent
from auth.errors import ResourceConflict
from auth.models import AuthUser, UserStatus
from auth.uuids import uuid7
from db.rls import principal_transaction
from db.types import ProjectSourceType
from projects.models import Project
from resources import services as resource_services
from resources.services import ReviewService
from reviews.dispatch import (
    REVIEW_DISPATCH_QUEUE,
    RabbitMQReviewPublisher,
    ReviewDispatchWorker,
    ReviewQueueUnavailable,
    declare_review_dispatch_topology,
)
from reviews.models import Review, ReviewAgent, ReviewDispatchJob, ReviewDispatchStatus
from reviews.queueing import ReviewDispatchMessageV1
from users.models import User


class RecordingPublisher:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.messages: list[ReviewDispatchMessageV1] = []
        self._unavailable = unavailable

    def publish(self, message: ReviewDispatchMessageV1) -> None:
        if self._unavailable:
            raise ReviewQueueUnavailable("broker unavailable")
        self.messages.append(message)


class BlockingPublisher(RecordingPublisher):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def publish(self, message: ReviewDispatchMessageV1) -> None:
        self.messages.append(message)
        self.entered.set()
        assert self.release.wait(timeout=5)


class FailAfterBrokerAcceptWorker(ReviewDispatchWorker):
    """Model a process failure after RabbitMQ confirms the publication."""

    def _mark_published(self, claim):  # type: ignore[no-untyped-def]
        raise RuntimeError("database update interrupted after broker confirmation")


class CancellingAfterClaimWorker(ReviewDispatchWorker):
    """Cancel a review after claim and before the worker checks its lifecycle."""

    def __init__(
        self, *, service: ReviewService, owner_id: UUID, **kwargs: object
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._service = service
        self._owner_id = owner_id
        self._cancelled = False

    def _review_is_queued(self, claim):  # type: ignore[no-untyped-def]
        if not self._cancelled:
            self._service.cancel(owner_id=self._owner_id, review_id=claim.review_id)
            self._cancelled = True
        return super()._review_is_queued(claim)


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    assert value and "postgres-test" in value
    return value


def _internal_database_url() -> str:
    value = os.environ.get("INTERNAL_DATABASE_URL")
    assert value and "postgres-test" in value
    return value


def _internal_engine() -> sa.Engine:
    engine = sa.create_engine(_internal_database_url())
    try:
        with engine.connect() as connection:
            role = connection.execute(sa.text("SELECT current_user")).scalar_one()
    except sa.exc.SQLAlchemyError:
        engine.dispose()
        if os.environ.get("CI"):
            pytest.fail("CI must configure the trace_internal database role")
        pytest.skip("The isolated internal database role is not configured")
    if role != "trace_internal":
        engine.dispose()
        if os.environ.get("CI"):
            pytest.fail("CI must use the trace_internal database role")
        pytest.skip("The isolated internal database role is not configured")
    return engine


def _review_rabbitmq_url() -> str:
    value = os.environ.get("REVIEW_RABBITMQ_URL")
    if value:
        return value
    if os.environ.get("CI"):
        pytest.fail("CI must configure REVIEW_RABBITMQ_URL for dispatch integration")
    pytest.skip("RabbitMQ review-dispatch integration is not configured")


def _rabbit_connection() -> pika.BlockingConnection:
    try:
        return pika.BlockingConnection(pika.URLParameters(_review_rabbitmq_url()))
    except pika.exceptions.AMQPError as error:
        if os.environ.get("CI"):
            pytest.fail(f"CI review-dispatch broker is unavailable: {error}")
        pytest.skip("RabbitMQ review-dispatch integration is unavailable")


def _create_owner_graph(
    engine: sa.Engine, owner_id: UUID, project_id: UUID, agent_id: UUID
) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(AuthUser).values(
                id=owner_id,
                email=f"review-dispatch-{owner_id}@example.test",
                status=UserStatus.ACTIVE,
            )
        )
        connection.execute(sa.insert(User).values(id=owner_id))
    with principal_transaction(engine, owner_id) as connection:
        connection.execute(
            sa.insert(Project).values(
                id=project_id,
                owner_id=owner_id,
                name="review dispatch project",
                source=ProjectSourceType.LOCAL,
                local_path_hash=b"review-dispatch-project",
                source_hash=b"s" * 32,
            )
        )
        connection.execute(
            sa.insert(Agent).values(
                id=agent_id,
                owner_id=owner_id,
                name="review dispatch agent",
                review_category="security",
                model_provider="openai",
                model_name="test",
            )
        )


def _job(internal_engine: sa.Engine, review_id: UUID) -> sa.RowMapping:
    with internal_engine.connect() as connection:
        return (
            connection.execute(
                sa.select(ReviewDispatchJob.__table__).where(
                    ReviewDispatchJob.review_id == review_id
                )
            )
            .mappings()
            .one()
        )


def _set_job_due(internal_engine: sa.Engine, review_id: UUID) -> None:
    with internal_engine.begin() as connection:
        connection.execute(
            sa.update(ReviewDispatchJob)
            .where(ReviewDispatchJob.review_id == review_id)
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )


def _set_job_stale_processing(internal_engine: sa.Engine, review_id: UUID) -> None:
    with internal_engine.begin() as connection:
        connection.execute(
            sa.update(ReviewDispatchJob)
            .where(ReviewDispatchJob.review_id == review_id)
            .values(
                status=ReviewDispatchStatus.PROCESSING,
                attempt_count=1,
                updated_at=datetime.now(UTC) - timedelta(seconds=301),
            )
        )


def _outbox_counts(
    engine: sa.Engine,
    internal_engine: sa.Engine,
    owner_id: UUID,
) -> tuple[int, int, int]:
    with principal_transaction(engine, owner_id) as connection:
        review_count = connection.execute(
            sa.select(sa.func.count())
            .select_from(Review)
            .where(Review.owner_id == owner_id)
        ).scalar_one()
        assignment_count = connection.execute(
            sa.select(sa.func.count())
            .select_from(ReviewAgent)
            .where(ReviewAgent.owner_id == owner_id)
        ).scalar_one()
    with internal_engine.connect() as connection:
        job_count = connection.execute(
            sa.select(sa.func.count())
            .select_from(ReviewDispatchJob)
            .where(ReviewDispatchJob.owner_id == owner_id)
        ).scalar_one()
    return review_count, assignment_count, job_count


@pytest.mark.integration
def test_submission_creates_one_outbox_job_and_worker_marks_confirmed_publish() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        review = ReviewService(engine).create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-success",
        )
        job = _job(internal_engine, review["id"])
        assert job["status"] is ReviewDispatchStatus.PENDING

        publisher = RecordingPublisher()
        worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=publisher,  # type: ignore[arg-type]
        )
        assert worker.run_once()

        updated = _job(internal_engine, review["id"])
        assert updated["status"] is ReviewDispatchStatus.PUBLISHED
        assert len(publisher.messages) == 1
        assert publisher.messages[0] == ReviewDispatchMessageV1(
            review_id=review["id"],
            review_agent_id=job["review_agent_id"],
            owner_id=owner_id,
            idempotency_id=job["idempotency_id"],
        )
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_idempotent_replay_keeps_original_assignments_and_outbox_jobs() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, first_agent_id, second_agent_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    try:
        _create_owner_graph(engine, owner_id, project_id, first_agent_id)
        with principal_transaction(engine, owner_id) as connection:
            connection.execute(
                sa.insert(Agent).values(
                    id=second_agent_id,
                    owner_id=owner_id,
                    name="review dispatch second agent",
                    review_category="security",
                    model_provider="openai",
                    model_name="test",
                )
            )
        service = ReviewService(engine)
        created = service.create(
            owner_id=owner_id,
            values={
                "project_id": project_id,
                "agent_ids": [first_agent_id, second_agent_id],
            },
            idempotency_key="dispatch-replay",
        )
        before = _outbox_counts(engine, internal_engine, owner_id)

        replayed = service.create(
            owner_id=owner_id,
            values={
                "project_id": project_id,
                "agent_ids": [second_agent_id, first_agent_id],
            },
            idempotency_key="dispatch-replay",
        )

        assert replayed["id"] == created["id"]
        assert _outbox_counts(engine, internal_engine, owner_id) == before == (1, 2, 2)
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_review_insert_failure_rolls_back_the_submission_graph(monkeypatch) -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        service = ReviewService(engine)
        baseline = service.create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-review-baseline",
        )
        monkeypatch.setattr(resource_services, "uuid7", lambda: baseline["id"])

        with pytest.raises(ResourceConflict) as error:
            service.create(
                owner_id=owner_id,
                values={"project_id": project_id, "agent_ids": [agent_id]},
                idempotency_key="dispatch-failing-review",
            )

        assert error.value.reason == "review_conflict"
        assert _outbox_counts(engine, internal_engine, owner_id) == (1, 1, 1)
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_assignment_insert_failure_rolls_back_the_submission_graph(monkeypatch) -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        service = ReviewService(engine)
        baseline = service.create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-assignment-baseline",
        )
        conflicting_assignment_id = _job(internal_engine, baseline["id"])[
            "review_agent_id"
        ]
        generated_ids = iter((uuid7(), uuid7(), conflicting_assignment_id))
        monkeypatch.setattr(resource_services, "uuid7", lambda: next(generated_ids))

        with pytest.raises(ResourceConflict) as error:
            service.create(
                owner_id=owner_id,
                values={"project_id": project_id, "agent_ids": [agent_id]},
                idempotency_key="dispatch-failing-assignment",
            )

        assert error.value.reason == "review_conflict"
        assert _outbox_counts(engine, internal_engine, owner_id) == (1, 1, 1)
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_outbox_insert_failure_rolls_back_review_and_assignments(monkeypatch) -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        service = ReviewService(engine)
        baseline = service.create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-baseline",
        )
        conflicting_job_id = _job(internal_engine, baseline["id"])["idempotency_id"]
        assert _outbox_counts(engine, internal_engine, owner_id) == (1, 1, 1)

        generated_ids = iter((uuid7(), uuid7(), uuid7(), conflicting_job_id))
        monkeypatch.setattr(resource_services, "uuid7", lambda: next(generated_ids))

        with pytest.raises(ResourceConflict) as error:
            service.create(
                owner_id=owner_id,
                values={"project_id": project_id, "agent_ids": [agent_id]},
                idempotency_key="dispatch-failing-outbox",
            )
        assert error.value.reason == "review_conflict"

        assert _outbox_counts(engine, internal_engine, owner_id) == (1, 1, 1)
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_concurrent_duplicate_submission_creates_one_complete_durable_graph() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        service = ReviewService(engine)

        def submit() -> dict[str, object]:
            return service.create(
                owner_id=owner_id,
                values={"project_id": project_id, "agent_ids": [agent_id]},
                idempotency_key="dispatch-concurrent-submission",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=10)
                for future in (executor.submit(submit), executor.submit(submit))
            ]

        assert len({result["id"] for result in results}) == 1
        assert _outbox_counts(engine, internal_engine, owner_id) == (1, 1, 1)
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_cancellation_terminally_cancels_unpublished_jobs() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        service = ReviewService(engine)
        review = service.create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-cancelled",
        )

        service.cancel(owner_id=owner_id, review_id=review["id"])

        job = _job(internal_engine, review["id"])
        assert job["status"] is ReviewDispatchStatus.DEAD_LETTER
        assert job["failure_code"] == "review_cancelled"
        worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=RecordingPublisher(),  # type: ignore[arg-type]
        )
        assert not worker.run_once()
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_broker_failures_retry_then_dead_letter_with_sanitized_code() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        review = ReviewService(engine).create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-retry",
        )
        worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=RecordingPublisher(unavailable=True),  # type: ignore[arg-type]
            max_attempts=1,
        )

        assert worker.run_once()

        job = _job(internal_engine, review["id"])
        assert job["status"] is ReviewDispatchStatus.DEAD_LETTER
        assert job["attempt_count"] == 1
        assert job["failure_code"] == "publish_exhausted"
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_broker_retry_reuses_the_same_outbox_idempotency_identifier() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        review = ReviewService(engine).create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-retry-success",
        )
        unavailable_worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=RecordingPublisher(unavailable=True),  # type: ignore[arg-type]
            max_attempts=2,
        )

        assert unavailable_worker.run_once()
        first_attempt = _job(internal_engine, review["id"])
        assert first_attempt["status"] is ReviewDispatchStatus.PENDING
        assert first_attempt["attempt_count"] == 1
        assert first_attempt["failure_code"] == "broker_unavailable"

        _set_job_due(internal_engine, review["id"])
        publisher = RecordingPublisher()
        recovered_worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=publisher,  # type: ignore[arg-type]
            max_attempts=2,
        )
        assert recovered_worker.run_once()

        completed = _job(internal_engine, review["id"])
        assert completed["status"] is ReviewDispatchStatus.PUBLISHED
        assert completed["attempt_count"] == 2
        assert publisher.messages[0].idempotency_id == first_attempt["idempotency_id"]
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_stale_processing_job_is_reclaimed_without_waiting() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        review = ReviewService(engine).create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-stale-claim",
        )
        _set_job_stale_processing(internal_engine, review["id"])

        publisher = RecordingPublisher()
        worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=publisher,  # type: ignore[arg-type]
        )
        assert worker.run_once()

        job = _job(internal_engine, review["id"])
        assert job["status"] is ReviewDispatchStatus.PUBLISHED
        assert job["attempt_count"] == 2
        assert len(publisher.messages) == 1
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_concurrent_workers_claim_a_dispatch_job_once() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        review = ReviewService(engine).create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-concurrent-claim",
        )
        publisher = BlockingPublisher()
        first_worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=publisher,  # type: ignore[arg-type]
        )
        second_worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=RecordingPublisher(),  # type: ignore[arg-type]
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(first_worker.run_once)
            assert publisher.entered.wait(timeout=5)
            second = executor.submit(second_worker.run_once)
            assert second.result(timeout=5) is False
            publisher.release.set()
            assert first.result(timeout=5) is True

        job = _job(internal_engine, review["id"])
        assert job["status"] is ReviewDispatchStatus.PUBLISHED
        assert job["attempt_count"] == 1
        assert len(publisher.messages) == 1
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_cancelled_review_after_claim_is_not_published() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        service = ReviewService(engine)
        review = service.create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-cancel-after-claim",
        )
        publisher = RecordingPublisher()
        worker = CancellingAfterClaimWorker(
            engine=internal_engine,
            publisher=publisher,  # type: ignore[arg-type]
            service=service,
            owner_id=owner_id,
        )

        assert worker.run_once()

        job = _job(internal_engine, review["id"])
        assert job["status"] is ReviewDispatchStatus.DEAD_LETTER
        assert job["failure_code"] == "review_cancelled"
        assert publisher.messages == []
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_recovery_after_broker_acceptance_republishes_same_message_identifier() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        review = ReviewService(engine).create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-ambiguous-confirm",
        )
        first_publisher = RecordingPublisher()
        interrupted_worker = FailAfterBrokerAcceptWorker(
            engine=internal_engine,
            publisher=first_publisher,  # type: ignore[arg-type]
        )

        with pytest.raises(RuntimeError, match="database update interrupted"):
            interrupted_worker.run_once()
        claimed = _job(internal_engine, review["id"])
        assert claimed["status"] is ReviewDispatchStatus.PROCESSING
        assert len(first_publisher.messages) == 1

        _set_job_stale_processing(internal_engine, review["id"])
        second_publisher = RecordingPublisher()
        recovered_worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=second_publisher,  # type: ignore[arg-type]
        )
        assert recovered_worker.run_once()

        assert (
            _job(internal_engine, review["id"])["status"]
            is ReviewDispatchStatus.PUBLISHED
        )
        assert (
            second_publisher.messages[0].idempotency_id
            == first_publisher.messages[0].idempotency_id
        )
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()


@pytest.mark.integration
def test_worker_publishes_persistent_identifier_only_message_to_rabbitmq() -> None:
    engine = sa.create_engine(_database_url())
    internal_engine = _internal_engine()
    broker = _rabbit_connection()
    owner_id, project_id, agent_id = uuid4(), uuid4(), uuid4()
    try:
        channel = broker.channel()
        declare_review_dispatch_topology(channel)
        channel.queue_purge(queue=REVIEW_DISPATCH_QUEUE)
        _create_owner_graph(engine, owner_id, project_id, agent_id)
        review = ReviewService(engine).create(
            owner_id=owner_id,
            values={"project_id": project_id, "agent_ids": [agent_id]},
            idempotency_key="dispatch-rabbitmq-confirm",
        )
        job = _job(internal_engine, review["id"])
        worker = ReviewDispatchWorker(
            engine=internal_engine,
            publisher=RabbitMQReviewPublisher(url=_review_rabbitmq_url()),
        )

        assert worker.run_once()
        delivery, properties, body = channel.basic_get(
            queue=REVIEW_DISPATCH_QUEUE,
            auto_ack=True,
        )
        assert delivery is not None
        assert properties.delivery_mode == 2
        assert properties.content_type == "application/json"
        assert ReviewDispatchMessageV1.decode(body) == ReviewDispatchMessageV1(
            review_id=review["id"],
            review_agent_id=job["review_agent_id"],
            owner_id=owner_id,
            idempotency_id=job["idempotency_id"],
        )
        assert (
            _job(internal_engine, review["id"])["status"]
            is ReviewDispatchStatus.PUBLISHED
        )
    finally:
        if broker.is_open:
            cleanup_channel = broker.channel()
            declare_review_dispatch_topology(cleanup_channel)
            cleanup_channel.queue_purge(queue=REVIEW_DISPATCH_QUEUE)
            broker.close()
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
        internal_engine.dispose()
