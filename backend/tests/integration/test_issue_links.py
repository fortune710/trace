from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import UUID

import pytest
import sqlalchemy as sa

from auth.credential_service import CredentialService
from auth.credentials import CredentialCipher
from auth.errors import (
    AuthorizationDenied,
    IssueDestinationNotConfigured,
    IssueProviderAuthorizationRequired,
    IssueProviderValidationError,
    ResourceUnavailable,
)
from credentials.models import CredentialKind, CredentialProvider
from db.rls import principal_transaction
from issue_tracking.catalog import LinearCatalogService
from issue_tracking.contracts import (
    CreatedExternalIssue,
    IssueProviderError,
    LinearProject,
    LinearTeam,
)
from issue_tracking.models import IssueLink, IssueLinkState, IssueProviderName
from issue_tracking.project_service import ProjectIssueTrackingService
from issue_tracking.service import IssueTrackingService
from notifications.models import Notification, NotificationEventType
from projects.models import Project

pytestmark = pytest.mark.integration


class BlockingGitHubProvider:
    name = IssueProviderName.GITHUB

    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self._lock = Lock()
        self.calls = 0
        self.verification_calls = 0

    def verify_destination(self, *, access_token, destination):  # type: ignore[no-untyped-def]
        del access_token, destination
        with self._lock:
            self.verification_calls += 1

    def create_issue(self, *, access_token, destination, payload):  # type: ignore[no-untyped-def]
        del access_token, destination, payload
        with self._lock:
            self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=10)
        return CreatedExternalIssue(
            external_id="21",
            url="https://github.example.test/acme/trace/issues/21",
        )


class RetriableGitHubProvider:
    name = IssueProviderName.GITHUB

    def __init__(self) -> None:
        self.error: IssueProviderError | None = IssueProviderError("validation")
        self.calls = 0
        self.verification_calls = 0

    def verify_destination(self, *, access_token, destination):  # type: ignore[no-untyped-def]
        del access_token, destination
        self.verification_calls += 1

    def create_issue(self, *, access_token, destination, payload):  # type: ignore[no-untyped-def]
        del access_token, destination, payload
        self.calls += 1
        if self.error is not None:
            raise self.error
        return CreatedExternalIssue(
            external_id="22",
            url="https://github.example.test/acme/trace/issues/22",
        )


class RecordingLinearCatalogProvider:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def list_teams(self, *, access_token):  # type: ignore[no-untyped-def]
        self.tokens.append(access_token.get_secret_value())
        return [
            LinearTeam(
                id="00000000-0000-0000-0000-000000000001", name="Engineering", key="ENG"
            )
        ]

    def list_projects(self, *, access_token, team_id):  # type: ignore[no-untyped-def]
        self.tokens.append(access_token.get_secret_value())
        assert team_id == "00000000-0000-0000-0000-000000000001"
        return [LinearProject(id="00000000-0000-0000-0000-000000000002", name="Trace")]


class ProjectLinearCatalog:
    team_id = "00000000-0000-0000-0000-000000000001"
    project_id = "00000000-0000-0000-0000-000000000002"

    def list_projects(self, *, owner_id, team_id):  # type: ignore[no-untyped-def]
        del owner_id
        if str(team_id) != self.team_id:
            return []
        return [LinearProject(id=self.project_id, name="Trace")]


def _service(*, engine, provider) -> IssueTrackingService:  # type: ignore[no-untyped-def]
    return IssueTrackingService(
        provider=provider,
        engine=engine,
        credential_service=CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
        ),
    )


def _connect_github(*, engine, owner_id) -> None:  # type: ignore[no-untyped-def]
    CredentialService(
        engine=engine,
        cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
    ).create_or_replace(
        owner_id=owner_id,
        provider=CredentialProvider.GITHUB,
        kind=CredentialKind.OAUTH,
        payload={"access_token": "integration-github-token"},
    )


def _connect_linear(*, engine, owner_id) -> None:  # type: ignore[no-untyped-def]
    CredentialService(
        engine=engine,
        cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
    ).create_or_replace(
        owner_id=owner_id,
        provider=CredentialProvider.LINEAR,
        kind=CredentialKind.OAUTH,
        payload={"access_token": "integration-linear-token"},
    )


def _configure_github_destination(*, engine, owner_id, project_id) -> None:  # type: ignore[no-untyped-def]
    with principal_transaction(engine, owner_id) as connection:
        connection.execute(
            sa.update(Project)
            .where(Project.id == project_id, Project.owner_id == owner_id)
            .values(
                repository_owner="acme",
                repository_name="trace",
                issue_tracking_details={
                    "connected_projects": [
                        {"provider": "github", "owner": "acme", "project": "trace"}
                    ]
                },
            )
        )


def test_issue_link_concurrency_creates_one_external_ticket(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    local_project_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    _connect_github(engine=integration_engine, owner_id=owner.user_id)
    provider = BlockingGitHubProvider()
    first = _service(engine=integration_engine, provider=provider)
    second = _service(engine=integration_engine, provider=provider)

    with pytest.raises(IssueDestinationNotConfigured):
        first.create_remediation_issue(
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
        )
    _configure_github_destination(
        engine=integration_engine,
        owner_id=owner.user_id,
        project_id=UUID(project["id"]),
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_call = executor.submit(
            first.create_remediation_issue,
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
        )
        assert provider.entered.wait(timeout=10)
        pending = second.create_remediation_issue(
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
        )
        assert pending.state is IssueLinkState.PENDING
        assert provider.calls == 1
        provider.release.set()
        created = first_call.result(timeout=10)

    assert created.state is IssueLinkState.CREATED
    assert created.external_identifier == "21"
    assert provider.calls == 1
    assert provider.verification_calls == 1
    with principal_transaction(integration_engine, owner.user_id) as connection:
        notification = (
            connection.execute(
                sa.select(Notification.__table__).where(
                    Notification.owner_id == owner.user_id,
                    Notification.event_type == NotificationEventType.ISSUE_CREATED,
                )
            )
            .mappings()
            .one()
        )
    assert notification["dedupe_key"] == f"issue-link:{created.id}:created"
    assert notification["action_path"] == (
        f"/reviews/{graph['review_id']}/findings/{graph['finding_id']}"
    )
    assert notification["data"] == {
        "finding_id": str(graph["finding_id"]),
        "issue_link_id": str(created.id),
        "provider": "github",
    }


def test_failed_known_provider_request_can_retry_and_foreign_link_is_denied(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    local_project_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    _connect_github(engine=integration_engine, owner_id=owner.user_id)
    _configure_github_destination(
        engine=integration_engine,
        owner_id=owner.user_id,
        project_id=UUID(project["id"]),
    )
    provider = RetriableGitHubProvider()
    service = _service(engine=integration_engine, provider=provider)

    with pytest.raises(IssueProviderValidationError):
        service.create_remediation_issue(
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
        )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        failure_notifications = (
            connection.execute(
                sa.select(Notification.__table__).where(
                    Notification.owner_id == owner.user_id,
                    Notification.event_type
                    == NotificationEventType.ISSUE_CREATION_FAILED,
                )
            )
            .mappings()
            .all()
        )
    assert len(failure_notifications) == 1
    failure_notification = failure_notifications[0]
    assert failure_notification["dedupe_key"].startswith("issue-link:")
    assert failure_notification["dedupe_key"].endswith(":failed")
    assert failure_notification["action_path"] == (
        f"/reviews/{graph['review_id']}/findings/{graph['finding_id']}"
    )
    assert failure_notification["data"] == {
        "finding_id": str(graph["finding_id"]),
        "issue_link_id": str(failure_notification["dedupe_key"]).split(":")[1],
        "provider": "github",
        "failure_code": "validation",
    }
    with principal_transaction(integration_engine, other.user_id) as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(Notification)
                .where(
                    Notification.event_type
                    == NotificationEventType.ISSUE_CREATION_FAILED
                )
            ).scalar_one()
            == 0
        )

    with pytest.raises(IssueProviderValidationError):
        service.create_remediation_issue(
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
        )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(Notification)
                .where(
                    Notification.owner_id == owner.user_id,
                    Notification.event_type
                    == NotificationEventType.ISSUE_CREATION_FAILED,
                )
            ).scalar_one()
            == 1
        )
    provider.error = None
    created = service.create_remediation_issue(
        owner_id=owner.user_id,
        remediation_id=graph["remediation_id"],
    )

    assert created.state is IssueLinkState.CREATED
    assert provider.calls == 3
    assert provider.verification_calls == 3
    with pytest.raises(AuthorizationDenied):
        service.get_link(owner_id=other.user_id, link_id=created.id)


def test_ambiguous_provider_failure_leaves_a_pending_link_without_notification(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    local_project_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    _connect_github(engine=integration_engine, owner_id=owner.user_id)
    _configure_github_destination(
        engine=integration_engine,
        owner_id=owner.user_id,
        project_id=UUID(project["id"]),
    )
    provider = RetriableGitHubProvider()
    provider.error = IssueProviderError("unavailable")
    service = _service(engine=integration_engine, provider=provider)

    with pytest.raises(ResourceUnavailable):
        service.create_remediation_issue(
            owner_id=owner.user_id,
            remediation_id=graph["remediation_id"],
        )

    with principal_transaction(integration_engine, owner.user_id) as connection:
        link_state = connection.execute(
            sa.select(IssueLink.state).where(
                IssueLink.owner_id == owner.user_id,
                IssueLink.finding_id == graph["finding_id"],
            )
        ).scalar_one()
        notifications = connection.execute(
            sa.select(sa.func.count())
            .select_from(Notification)
            .where(
                Notification.owner_id == owner.user_id,
                Notification.event_type == NotificationEventType.ISSUE_CREATION_FAILED,
            )
        ).scalar_one()
    assert link_state is IssueLinkState.PENDING
    assert notifications == 0


def test_linear_catalog_uses_only_the_owner_oauth_credential(
    account_pair,
    integration_engine,
) -> None:
    owner, other = account_pair
    _connect_linear(engine=integration_engine, owner_id=owner.user_id)
    provider = RecordingLinearCatalogProvider()
    service = LinearCatalogService(
        provider=provider,  # type: ignore[arg-type]
        engine=integration_engine,
        credential_service=CredentialService(
            engine=integration_engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
        ),
    )

    teams = service.list_teams(owner_id=owner.user_id)
    projects = service.list_projects(
        owner_id=owner.user_id,
        team_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert [(team.name, team.key) for team in teams] == [("Engineering", "ENG")]
    assert [project.name for project in projects] == ["Trace"]
    assert provider.tokens == ["integration-linear-token", "integration-linear-token"]
    with pytest.raises(IssueProviderAuthorizationRequired):
        service.list_teams(owner_id=other.user_id)


def test_project_issue_tracking_validates_linear_destinations_and_ownership(
    account_pair,
    integration_engine,
    local_project_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    catalog = ProjectLinearCatalog()
    service = ProjectIssueTrackingService(
        engine=integration_engine,
        linear_catalog_service=catalog,  # type: ignore[arg-type]
    )
    linear_destination = {
        "provider": "linear",
        "owner": catalog.team_id,
        "project": catalog.project_id,
    }

    updated = service.update(
        owner_id=owner.user_id,
        project_id=UUID(project["id"]),
        connected_projects=[linear_destination],
    )

    assert updated == {"connected_projects": [linear_destination]}
    assert (
        service.get(owner_id=owner.user_id, project_id=UUID(project["id"])) == updated
    )

    with pytest.raises(IssueProviderValidationError):
        service.update(
            owner_id=owner.user_id,
            project_id=UUID(project["id"]),
            connected_projects=[linear_destination, linear_destination],
        )

    with pytest.raises(IssueProviderValidationError):
        service.update(
            owner_id=owner.user_id,
            project_id=UUID(project["id"]),
            connected_projects=[
                {"provider": "linear", "owner": "not-a-uuid", "project": "not-a-uuid"}
            ],
        )
    with pytest.raises(IssueProviderValidationError):
        service.update(
            owner_id=owner.user_id,
            project_id=UUID(project["id"]),
            connected_projects=[
                {
                    "provider": "linear",
                    "owner": "00000000-0000-0000-0000-000000000099",
                    "project": catalog.project_id,
                }
            ],
        )
    with pytest.raises(IssueProviderValidationError):
        service.update(
            owner_id=owner.user_id,
            project_id=UUID(project["id"]),
            connected_projects=[
                {"provider": "github", "owner": "acme", "project": "other-repo"}
            ],
        )
    with pytest.raises(AuthorizationDenied):
        service.get(owner_id=other.user_id, project_id=UUID(project["id"]))
