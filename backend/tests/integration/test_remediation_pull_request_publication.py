from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import UUID

import pytest
import sqlalchemy as sa

from agents.execution.patches import build_patch
from auth.credentials import CredentialCipher
from auth.errors import RepositoryInvalidRequest
from db.rls import principal_transaction
from db.types import RepositorySource
from external_repositories.service import PublishedPullRequest, RepositoryService
from findings.models import Finding, FindingStatus
from notifications.models import Notification, NotificationEventType
from projects.models import Project
from remediations.models import Remediation, RemediationStatus
from remediations.patch_store import PatchStore
from remediations.service import RemediationPullRequestService

pytestmark = pytest.mark.integration


def _store(engine):
    return PatchStore(engine, CredentialCipher(key=b"c" * 32, key_version="local-v1"))


def _valid_patch():
    return build_patch(
        original={"file": "before\n"},
        updated={"file": "after\n"},
        snapshot={
            "source_kind": "github",
            "source_identifier": "12345",
            "revision": "a" * 40,
        },
    )


def _make_github_project_with_accepted_finding(
    *,
    account,
    project_id: UUID,
    finding_id: UUID,
    integration_engine,
    credential_factory,
    external_repository_factory,
    prepare_patch=True,
) -> None:
    credential = credential_factory(account)
    repository_connection_id = external_repository_factory(account, credential["id"])
    with principal_transaction(integration_engine, account.user_id) as connection:
        connection.execute(
            sa.update(Project)
            .where(Project.id == project_id)
            .values(
                source=RepositorySource.GITHUB,
                external_repository_id="12345",
                external_repository_connection_id=repository_connection_id,
                repository_owner="trace-test",
                repository_name="remediations",
                branch_name="main",
                local_path_hash=None,
            )
        )
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == finding_id)
            .values(status=FindingStatus.ACCEPTED)
        )

    if prepare_patch:
        with principal_transaction(integration_engine, account.user_id) as connection:
            remediation_id = connection.execute(
                sa.select(Remediation.id).where(Remediation.finding_id == finding_id)
            ).scalar_one()
        _store(integration_engine).save(
            owner_id=account.user_id,
            remediation_id=remediation_id,
            patch=_valid_patch(),
        )


def test_accepted_remediation_creates_one_pull_request_and_persists_metadata(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    credential_factory,
    external_repository_factory,
    integration_engine,
    local_project_factory,
    monkeypatch,
    recording_audit_recorder,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(
        owner,
        project["id"],
        agent["id"],
        source_kind=RepositorySource.GITHUB,
        source_identifier="12345",
    )
    _make_github_project_with_accepted_finding(
        account=owner,
        project_id=project["id"],
        finding_id=graph["finding_id"],
        integration_engine=integration_engine,
        credential_factory=credential_factory,
        external_repository_factory=external_repository_factory,
    )
    published_calls: list[dict[str, object]] = []

    def publish(_service, **kwargs: object) -> PublishedPullRequest:
        published_calls.append(kwargs)
        return PublishedPullRequest(
            url="https://github.example.test/trace-test/remediations/pull/42",
            number=42,
            is_merged=False,
        )

    monkeypatch.setattr(RepositoryService, "publish_remediation_pull_request", publish)

    response = owner.client.post(
        f"/api/v1/remediations/{graph['remediation_id']}/pull-request",
        headers=owner.headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    assert response.json()["pull_request"] == {
        "url": "https://github.example.test/trace-test/remediations/pull/42",
        "number": 42,
        "is_merged": False,
    }
    assert published_calls == [
        {
            "owner_id": owner.user_id,
            "repository_identifier": "12345",
            "source_revision": "a" * 40,
            "base_branch": "main",
            "remediation_id": graph["remediation_id"],
            "diff": _valid_patch().diff,
            "finding_title": "Integration finding",
        }
    ]
    with principal_transaction(integration_engine, owner.user_id) as connection:
        persisted = (
            connection.execute(
                sa.select(Remediation).where(Remediation.id == graph["remediation_id"])
            )
            .mappings()
            .one()
        )
    assert persisted["status"] is RemediationStatus.APPLIED
    assert persisted["approved_at"] is not None
    assert persisted["pull_request"] == response.json()["pull_request"]
    with principal_transaction(integration_engine, owner.user_id) as connection:
        notification = (
            connection.execute(
                sa.select(Notification.__table__).where(
                    Notification.owner_id == owner.user_id,
                    Notification.event_type
                    == NotificationEventType.PULL_REQUEST_CREATED,
                )
            )
            .mappings()
            .one()
        )
    assert notification["dedupe_key"] == (
        f"remediation:{graph['remediation_id']}:pull-request-created"
    )
    assert notification["action_path"] == (
        "https://github.example.test/trace-test/remediations/pull/42"
    )
    assert notification["data"] == {
        "remediation_id": str(graph["remediation_id"]),
        "pull_request_number": 42,
    }
    event = next(
        event
        for event in recording_audit_recorder.events
        if event["event_type"] == "remediation.pull_request.created"
    )
    assert "diff --git" not in str(event)
    assert "Resolve the integration finding" not in str(event)


def test_pull_request_endpoint_requires_csrf_and_owner_access_before_publication(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    local_project_factory,
    monkeypatch,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(
        owner,
        project["id"],
        agent["id"],
        source_kind=RepositorySource.GITHUB,
        source_identifier="12345",
    )
    published = False

    def publish(_service, **_kwargs: object) -> PublishedPullRequest:
        nonlocal published
        published = True
        raise AssertionError("publication must not start")

    monkeypatch.setattr(RepositoryService, "publish_remediation_pull_request", publish)
    path = f"/api/v1/remediations/{graph['remediation_id']}/pull-request"

    missing_csrf = owner.client.post(path)
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_validation_failed"

    foreign = other.client.post(path, headers=other.headers())
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "authorization_denied"
    assert not published


def test_pull_request_endpoint_rejects_findings_that_are_not_accepted(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    local_project_factory,
    monkeypatch,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(
        owner,
        project["id"],
        agent["id"],
        source_kind=RepositorySource.GITHUB,
        source_identifier="12345",
    )

    def publish(_service, **_kwargs: object) -> PublishedPullRequest:
        raise AssertionError("an open finding must not reach the provider")

    monkeypatch.setattr(RepositoryService, "publish_remediation_pull_request", publish)

    response = owner.client.post(
        f"/api/v1/remediations/{graph['remediation_id']}/pull-request",
        headers=owner.headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "resource_conflict"


def test_malformed_stored_diff_is_safely_rejected_without_persisting_a_pr(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    credential_factory,
    external_repository_factory,
    integration_engine,
    local_project_factory,
    monkeypatch,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(
        owner,
        project["id"],
        agent["id"],
        source_kind=RepositorySource.GITHUB,
        source_identifier="12345",
    )
    _make_github_project_with_accepted_finding(
        account=owner,
        project_id=project["id"],
        finding_id=graph["finding_id"],
        integration_engine=integration_engine,
        credential_factory=credential_factory,
        external_repository_factory=external_repository_factory,
        prepare_patch=False,
    )
    unsafe_diff = "diff --git a/../../secret b/../../secret"
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Remediation)
            .where(Remediation.id == graph["remediation_id"])
            .values(proposed_diff=unsafe_diff)
        )

    def reject_unsafe_diff(_service, **kwargs: object) -> PublishedPullRequest:
        assert kwargs["diff"] == unsafe_diff
        raise RepositoryInvalidRequest()

    monkeypatch.setattr(
        RepositoryService, "publish_remediation_pull_request", reject_unsafe_diff
    )

    response = owner.client.post(
        f"/api/v1/remediations/{graph['remediation_id']}/pull-request",
        headers=owner.headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "resource_conflict"
    with principal_transaction(integration_engine, owner.user_id) as connection:
        persisted = (
            connection.execute(
                sa.select(Remediation).where(Remediation.id == graph["remediation_id"])
            )
            .mappings()
            .one()
        )
    assert persisted["status"] is RemediationStatus.PROPOSED
    assert persisted["pull_request"] is None
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
            .one_or_none()
        )
    assert notification is None


def test_concurrent_pr_creation_reuses_the_single_persisted_pr(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    credential_factory,
    external_repository_factory,
    integration_engine,
    local_project_factory,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(
        owner,
        project["id"],
        agent["id"],
        source_kind=RepositorySource.GITHUB,
        source_identifier="12345",
    )
    _make_github_project_with_accepted_finding(
        account=owner,
        project_id=project["id"],
        finding_id=graph["finding_id"],
        integration_engine=integration_engine,
        credential_factory=credential_factory,
        external_repository_factory=external_repository_factory,
    )
    first_publication_started = Event()
    allow_first_publication = Event()
    calls: list[dict[str, object]] = []
    calls_lock = Lock()

    class BlockingPublisher:
        def publish_remediation_pull_request(
            self, **kwargs: object
        ) -> PublishedPullRequest:
            with calls_lock:
                calls.append(kwargs)
                is_first_call = len(calls) == 1
            if is_first_call:
                first_publication_started.set()
                assert allow_first_publication.wait(timeout=5)
            return PublishedPullRequest(
                url="https://github.example.test/trace-test/remediations/pull/77",
                number=77,
                is_merged=False,
            )

    service = RemediationPullRequestService(
        integration_engine,
        BlockingPublisher(),  # type: ignore[arg-type]
        patch_store=_store(integration_engine),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            service.create,
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
            request_id="concurrent-first",
        )
        assert first_publication_started.wait(timeout=5)
        second = executor.submit(
            service.create,
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
            request_id="concurrent-second",
        )
        allow_first_publication.set()
        first_response, first_queued = first.result(timeout=10)
        second_response, second_queued = second.result(timeout=10)

    assert calls == [
        {
            "owner_id": owner.user_id,
            "repository_identifier": "12345",
            "source_revision": "a" * 40,
            "base_branch": "main",
            "remediation_id": graph["remediation_id"],
            "diff": _valid_patch().diff,
            "finding_title": "Integration finding",
        }
    ]
    assert not first_queued
    assert not second_queued
    assert (
        first_response["pull_request"]
        == second_response["pull_request"]
        == {
            "url": "https://github.example.test/trace-test/remediations/pull/77",
            "number": 77,
            "is_merged": False,
        }
    )
