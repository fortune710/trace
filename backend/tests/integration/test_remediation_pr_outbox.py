from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
import sqlalchemy as sa

from db.rls import principal_transaction
from findings.models import Finding, FindingStatus
from remediations.dispatch import (
    RemediationPullRequestOutboxWorker,
    RemediationPullRequestQueueUnavailable,
)
from remediations.models import (
    RemediationPullRequestOutboxJob,
    RemediationPullRequestOutboxStatus,
)
from remediations.queueing import RemediationPullRequestMessageV1

pytestmark = pytest.mark.integration


@pytest.fixture
def internal_engine():
    url = os.environ.get("INTERNAL_DATABASE_URL")
    if not url:
        pytest.skip("The isolated internal database role is not configured")
    engine = sa.create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if (
                connection.execute(sa.text("SELECT current_user")).scalar_one()
                != "trace_internal"
            ):
                pytest.skip("The isolated internal database role is not configured")
    except sa.exc.SQLAlchemyError:
        pytest.skip("The isolated internal database role is not configured")
    yield engine
    engine.dispose()


class _RecordingPublisher:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.messages: list[RemediationPullRequestMessageV1] = []
        self.unavailable = unavailable

    def publish(self, message: RemediationPullRequestMessageV1) -> None:
        if self.unavailable:
            raise RemediationPullRequestQueueUnavailable()
        self.messages.append(message)


class _BlockingPublisher(_RecordingPublisher):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def publish(self, message: RemediationPullRequestMessageV1) -> None:
        self.messages.append(message)
        self.entered.set()
        assert self.release.wait(timeout=10)


def _insert_outbox(integration_engine, owner_id, remediation_id) -> None:  # type: ignore[no-untyped-def]
    with principal_transaction(integration_engine, owner_id) as connection:
        connection.execute(
            sa.insert(RemediationPullRequestOutboxJob).values(
                idempotency_id=uuid4(),
                owner_id=owner_id,
                remediation_id=remediation_id,
            )
        )


def _outbox(internal_engine, remediation_id):  # type: ignore[no-untyped-def]
    with internal_engine.connect() as connection:
        return (
            connection.execute(
                sa.select(RemediationPullRequestOutboxJob).where(
                    RemediationPullRequestOutboxJob.remediation_id == remediation_id
                )
            )
            .mappings()
            .one()
        )


def test_outbox_waits_for_acceptance_then_publishes_identifier_only_message(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    internal_engine,
    local_project_factory,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    _insert_outbox(integration_engine, owner.user_id, graph["remediation_id"])
    publisher = _RecordingPublisher()
    worker = RemediationPullRequestOutboxWorker(
        engine=internal_engine,
        publisher=publisher,  # type: ignore[arg-type]
    )

    assert not worker.run_once()
    waiting = _outbox(internal_engine, graph["remediation_id"])
    assert (
        waiting["status"] is RemediationPullRequestOutboxStatus.WAITING_FOR_ACCEPTANCE
    )

    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == graph["finding_id"])
            .values(status=FindingStatus.ACCEPTED)
        )

    assert worker.run_once()  # waiting_for_acceptance -> pending
    assert worker.run_once()  # pending -> publishing -> published
    published = _outbox(internal_engine, graph["remediation_id"])
    assert published["status"] is RemediationPullRequestOutboxStatus.PUBLISHED
    assert published["published_at"] is not None
    assert publisher.messages == [
        RemediationPullRequestMessageV1(
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
            idempotency_id=published["idempotency_id"],
        )
    ]


def test_outbox_cancels_ineligible_work_and_dead_letters_broker_failures(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    internal_engine,
    local_project_factory,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    cancelled = artifact_graph_factory(owner, project["id"], agent["id"])
    retrying = artifact_graph_factory(owner, project["id"], agent["id"])
    _insert_outbox(integration_engine, owner.user_id, cancelled["remediation_id"])
    _insert_outbox(integration_engine, owner.user_id, retrying["remediation_id"])
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == cancelled["finding_id"])
            .values(status=FindingStatus.DISMISSED)
        )
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == retrying["finding_id"])
            .values(status=FindingStatus.ACCEPTED)
        )

    worker = RemediationPullRequestOutboxWorker(
        engine=internal_engine,
        publisher=_RecordingPublisher(unavailable=True),  # type: ignore[arg-type]
    )
    assert worker.run_once()
    assert (
        _outbox(internal_engine, cancelled["remediation_id"])["status"]
        is RemediationPullRequestOutboxStatus.CANCELLED
    )
    assert worker.run_once()  # accepted waiting record becomes pending
    for expected_attempts in (1, 2, 3):
        assert worker.run_once()
        row = _outbox(internal_engine, retrying["remediation_id"])
        assert row["attempt_count"] == expected_attempts
        if expected_attempts < 3:
            assert row["status"] is RemediationPullRequestOutboxStatus.PENDING
            assert row["next_attempt_at"] is not None
            with internal_engine.begin() as connection:
                connection.execute(
                    sa.update(RemediationPullRequestOutboxJob)
                    .where(
                        RemediationPullRequestOutboxJob.idempotency_id
                        == row["idempotency_id"]
                    )
                    .values(next_attempt_at=datetime.now(UTC))
                )
        else:
            assert row["status"] is RemediationPullRequestOutboxStatus.DEAD_LETTER
            assert row["failure_code"] == "broker_unavailable"


def test_outbox_stale_claim_and_concurrent_workers_preserve_one_identifier(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    internal_engine,
    local_project_factory,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    _insert_outbox(integration_engine, owner.user_id, graph["remediation_id"])
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == graph["finding_id"])
            .values(status=FindingStatus.ACCEPTED)
        )
    publisher = _BlockingPublisher()
    first = RemediationPullRequestOutboxWorker(
        engine=internal_engine,
        publisher=publisher,  # type: ignore[arg-type]
    )
    second = RemediationPullRequestOutboxWorker(
        engine=internal_engine,
        publisher=publisher,  # type: ignore[arg-type]
    )

    assert first.run_once()  # waiting -> pending
    with ThreadPoolExecutor(max_workers=2) as executor:
        publishing = executor.submit(first.run_once)
        assert publisher.entered.wait(timeout=10)
        assert not second.run_once()
        publisher.release.set()
        assert publishing.result(timeout=10)
    row = _outbox(internal_engine, graph["remediation_id"])
    assert row["status"] is RemediationPullRequestOutboxStatus.PUBLISHED
    assert len(publisher.messages) == 1

    with internal_engine.begin() as connection:
        connection.execute(
            sa.update(RemediationPullRequestOutboxJob)
            .where(
                RemediationPullRequestOutboxJob.idempotency_id == row["idempotency_id"]
            )
            .values(
                status=RemediationPullRequestOutboxStatus.PUBLISHING,
                published_at=None,
                claimed_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
    recovery_publisher = _RecordingPublisher()
    recovered = RemediationPullRequestOutboxWorker(
        engine=internal_engine,
        publisher=recovery_publisher,  # type: ignore[arg-type]
        processing_timeout_seconds=1,
    )
    assert recovered.run_once()
    assert (
        _outbox(internal_engine, graph["remediation_id"])["status"]
        is RemediationPullRequestOutboxStatus.PUBLISHED
    )
    assert recovery_publisher.messages[0].idempotency_id == row["idempotency_id"]
