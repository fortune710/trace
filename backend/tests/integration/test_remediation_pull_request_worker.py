from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from auth.errors import ProviderUnavailable
from db.rls import principal_transaction
from notifications.models import Notification, NotificationEventType
from remediations.models import (
    RemediationPullRequestJob,
    RemediationPullRequestJobStatus,
)
from remediations.pull_request_worker import RemediationPullRequestWorker

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


class _UnavailablePublicationService:
    def publish_queued(self, **_kwargs: object) -> dict[str, object]:
        raise ProviderUnavailable()


class _SuccessfulPublicationService:
    def publish_queued(self, **_kwargs: object) -> dict[str, object]:
        return {}


def _create_job(integration_engine, owner_id, remediation_id) -> None:
    with principal_transaction(integration_engine, owner_id) as connection:
        connection.execute(
            sa.insert(RemediationPullRequestJob).values(
                owner_id=owner_id,
                remediation_id=remediation_id,
            )
        )


def test_remediation_pr_worker_uses_exponential_backoff_and_stops_after_three_failures(
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
    _create_job(integration_engine, owner.user_id, graph["remediation_id"])
    worker = RemediationPullRequestWorker(
        engine=internal_engine,
        service=_UnavailablePublicationService(),  # type: ignore[arg-type]
        retry_base_seconds=30,
        retry_max_seconds=300,
    )

    assert worker.run_once()
    with internal_engine.connect() as connection:
        first = (
            connection.execute(sa.select(RemediationPullRequestJob)).mappings().one()
        )
    assert first["status"] is RemediationPullRequestJobStatus.PENDING
    assert first["attempt_count"] == 1
    assert first["next_attempt_at"] is not None
    assert 25 <= (first["next_attempt_at"] - first["updated_at"]).total_seconds() <= 35

    for expected_attempts in (2, 3):
        with internal_engine.begin() as connection:
            connection.execute(
                sa.update(RemediationPullRequestJob).values(
                    next_attempt_at=datetime.now(UTC)
                )
            )
        assert worker.run_once()

        with internal_engine.connect() as connection:
            row = (
                connection.execute(sa.select(RemediationPullRequestJob))
                .mappings()
                .one()
            )
        assert row["attempt_count"] == expected_attempts
        if expected_attempts == 2:
            assert row["status"] is RemediationPullRequestJobStatus.PENDING
            assert row["next_attempt_at"] is not None
            assert (
                55 <= (row["next_attempt_at"] - row["updated_at"]).total_seconds() <= 65
            )
        else:
            assert row["status"] is RemediationPullRequestJobStatus.DEAD_LETTER
            assert row["next_attempt_at"] is None
    with principal_transaction(integration_engine, owner.user_id) as connection:
        notification = (
            connection.execute(
                sa.select(Notification.__table__).where(
                    Notification.owner_id == owner.user_id,
                    Notification.event_type
                    == NotificationEventType.PULL_REQUEST_CREATION_FAILED,
                )
            )
            .mappings()
            .one()
        )
    assert notification["dedupe_key"] == (
        f"remediation:{graph['remediation_id']}:pull-request-failed"
    )


def test_remediation_pr_worker_marks_a_published_retry_succeeded(
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
    _create_job(integration_engine, owner.user_id, graph["remediation_id"])
    worker = RemediationPullRequestWorker(
        engine=internal_engine,
        service=_SuccessfulPublicationService(),  # type: ignore[arg-type]
    )

    assert worker.run_once()
    with internal_engine.connect() as connection:
        row = connection.execute(sa.select(RemediationPullRequestJob)).mappings().one()
    assert row["status"] is RemediationPullRequestJobStatus.SUCCEEDED
    assert row["succeeded_at"] is not None
