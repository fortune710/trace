from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from artifacts.models import LocalFileBackup, PullRequest
from audit.runtime import get_audit_recorder
from auth.config import AuthSettings
from auth.csrf import issue_csrf_token
from auth.models import AuthSession, AuthUser, UserStatus
from auth.tokens import jwt_service_from_settings
from db.rls import principal_transaction
from db.session import get_engine, get_redis_client
from db.types import RepositorySource
from external_repositories.models import ExternalRepository
from findings.models import Finding, FindingSeverity, FindingStatus
from integration.github_stub import GithubApiStub
from main import create_app
from remediations.models import Remediation, RemediationStatus
from reviews.models import (
    ReviewRun,
    ReviewRunAgent,
    ReviewRunAgentStatus,
    ReviewRunCategory,
    ReviewStatus,
)
from users.models import User


def _encoded_key(byte: bytes) -> str:
    return base64.urlsafe_b64encode(byte * 32).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class TestAccount:
    user_id: UUID
    session_id: UUID
    client: TestClient
    csrf_token: str

    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf_token}

    def request(self, method: str, path: str, **kwargs: Any):
        headers = dict(kwargs.pop("headers", {}))
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            headers.setdefault("X-CSRF-Token", self.csrf_token)
        return self.client.request(method, path, headers=headers, **kwargs)


class AuthenticatedTestClient:
    """Account-scoped view over one TestClient event loop.

    Starlette's TestClient owns an async portal when used as a context
    manager. Sharing that portal prevents the process-wide async Redis pool
    from being reused across event loops, while resetting cookies keeps the
    two test accounts isolated at the HTTP boundary.
    """

    def __init__(
        self,
        client: TestClient,
        *,
        access_cookie_name: str,
        access_token: str,
        csrf_cookie_name: str,
        csrf_token: str,
    ) -> None:
        self._client = client
        self._access_cookie_name = access_cookie_name
        self._access_token = access_token
        self._csrf_cookie_name = csrf_cookie_name
        self._csrf_token = csrf_token

    def _set_account_cookies(self) -> None:
        self._client.cookies.set(self._access_cookie_name, self._access_token)
        self._client.cookies.set(self._csrf_cookie_name, self._csrf_token)

    def request(self, method: str, path: str, **kwargs: Any):
        self._set_account_cookies()
        return self._client.request(method, path, **kwargs)

    def get(self, path: str, **kwargs: Any):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any):
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any):
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any):
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        # The fixture owns the shared TestClient context.
        return None


@dataclass
class DispatcherStub:
    calls: list[tuple[UUID, UUID]]

    def dispatch(self, *, review_id: UUID, owner_id: UUID) -> None:
        self.calls.append((review_id, owner_id))


@pytest.fixture(scope="session")
def integration_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or "postgres-test" not in database_url:
        pytest.skip("PostgreSQL integration service is not configured")
    return database_url


@pytest.fixture(scope="session")
def integration_engine(integration_database_url: str):
    engine = sa.create_engine(integration_database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def integration_settings() -> AuthSettings:
    return AuthSettings(
        environment="test",
        github_api_url="https://github.example.test",
        cookie_secure=False,
        jwt_private_key=_encoded_key(b"a"),
        token_hash_key=_encoded_key(b"b"),
        credential_encryption_key=_encoded_key(b"c"),
        csrf_hmac_key=_encoded_key(b"d"),
        audit_hash_key=_encoded_key(b"e"),
    )


@pytest.fixture
def dispatcher_stub() -> DispatcherStub:
    return DispatcherStub([])


@pytest.fixture
def integration_app(
    integration_settings: AuthSettings, dispatcher_stub: DispatcherStub
):
    get_engine.cache_clear()
    get_redis_client.cache_clear()
    get_audit_recorder.cache_clear()
    application = create_app(
        integration_settings,
        review_dispatcher=dispatcher_stub,
    )
    yield application
    get_audit_recorder.cache_clear()
    get_redis_client.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def account_pair(
    integration_engine,
    integration_app,
    integration_settings: AuthSettings,
):
    accounts: list[TestAccount] = []
    now = datetime.now(UTC)
    jwt_service = jwt_service_from_settings(integration_settings)
    csrf_key = base64.urlsafe_b64decode(
        integration_settings.csrf_hmac_key.get_secret_value() + "=="
    )

    with TestClient(integration_app) as shared_client:
        with integration_engine.begin() as connection:
            for label in ("a", "b"):
                user_id = uuid4()
                session_id = uuid4()
                connection.execute(
                    sa.insert(AuthUser).values(
                        id=user_id,
                        email=f"integration-{label}-{user_id}@example.test",
                        status=UserStatus.ACTIVE,
                        email_confirmed_at=now,
                    )
                )
                connection.execute(sa.insert(User).values(id=user_id))
                connection.execute(
                    sa.insert(AuthSession).values(
                        id=session_id,
                        user_id=user_id,
                        expires_at=now + timedelta(hours=1),
                    )
                )
                access_token = jwt_service.issue(
                    user_id=user_id,
                    session_id=session_id,
                    now=now,
                )
                csrf_token = issue_csrf_token(session_id=session_id, key=csrf_key)
                client = AuthenticatedTestClient(
                    shared_client,
                    access_cookie_name=integration_settings.access_cookie_name,
                    access_token=access_token,
                    csrf_cookie_name=integration_settings.csrf_cookie_name,
                    csrf_token=csrf_token,
                )
                accounts.append(TestAccount(user_id, session_id, client, csrf_token))

        try:
            yield accounts[0], accounts[1]
        finally:
            with integration_engine.begin() as connection:
                connection.execute(
                    sa.delete(AuthUser).where(
                        AuthUser.id.in_([a.user_id for a in accounts])
                    )
                )


@pytest.fixture
def local_project_factory():
    def create(
        account: TestAccount, *, name: str = "integration-project"
    ) -> dict[str, Any]:
        response = account.request(
            "POST",
            "/api/v1/projects",
            json={
                "name": name,
                "source": "local",
                "local_path_hash": (uuid4().hex + uuid4().hex)[:64],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    return create


@pytest.fixture
def credential_factory():
    def create(
        account: TestAccount, *, access_token: str | None = None
    ) -> dict[str, Any]:
        response = account.request(
            "POST",
            "/api/v1/credentials",
            json={
                "provider": "github",
                "kind": "oauth",
                "payload": {"access_token": access_token or f"test-token-{uuid4()}"},
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    return create


@pytest.fixture
def external_repository_factory(integration_engine):
    def create(account: TestAccount, credential_id: UUID) -> UUID:
        credential_id = UUID(str(credential_id))
        repository_id = uuid4()
        with principal_transaction(integration_engine, account.user_id) as connection:
            connection.execute(
                sa.insert(ExternalRepository).values(
                    id=repository_id,
                    owner_id=account.user_id,
                    source=RepositorySource.GITHUB,
                    external_user_id=f"github-user-{account.user_id}",
                    credential_id=credential_id,
                )
            )
        return repository_id

    return create


@pytest.fixture
def github_stub(monkeypatch) -> GithubApiStub:
    stub = GithubApiStub()
    stub.install(monkeypatch)
    return stub


@pytest.fixture
def agent_factory():
    def create(
        account: TestAccount,
        *,
        name: str = "integration-agent",
        credential_id: UUID | None = None,
        category: str = "security",
        provider: str = "github",
    ) -> dict[str, Any]:
        response = account.request(
            "POST",
            "/api/v1/agents",
            json={
                "name": name,
                "review_category": category,
                "model_provider": provider,
                "model_name": "integration-model",
                "skills": [],
                "fallback_order": 0,
                "credential_id": str(credential_id) if credential_id else None,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    return create


@pytest.fixture
def review_factory():
    def create(
        account: TestAccount,
        project_id: UUID,
        agent_ids: list[UUID],
        *,
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        response = account.request(
            "POST",
            "/api/v1/reviews",
            json={
                "project_id": str(project_id),
                "source_revision": "integration-revision",
                "selected_categories": categories or ["security"],
                "agent_ids": [str(agent_id) for agent_id in agent_ids],
            },
        )
        assert response.status_code == 202, response.text
        return response.json()

    return create


@pytest.fixture
def artifact_graph_factory(integration_engine):
    def create(
        account: TestAccount, project_id: UUID, agent_id: UUID
    ) -> dict[str, UUID]:
        review_id = uuid4()
        finding_id = uuid4()
        remediation_id = uuid4()
        pull_request_id = uuid4()
        backup_id = uuid4()
        with principal_transaction(integration_engine, account.user_id) as connection:
            connection.execute(
                sa.insert(ReviewRun).values(
                    id=review_id,
                    owner_id=account.user_id,
                    project_id=project_id,
                    source_revision="integration-revision",
                    status=ReviewStatus.COMPLETED,
                )
            )
            connection.execute(
                sa.insert(ReviewRunCategory).values(
                    owner_id=account.user_id,
                    review_run_id=review_id,
                    category="security",
                )
            )
            connection.execute(
                sa.insert(ReviewRunAgent).values(
                    owner_id=account.user_id,
                    review_run_id=review_id,
                    agent_id=agent_id,
                    status=ReviewRunAgentStatus.COMPLETED,
                )
            )
            connection.execute(
                sa.insert(Finding).values(
                    id=finding_id,
                    owner_id=account.user_id,
                    review_run_id=review_id,
                    agent_id=agent_id,
                    category="security",
                    severity=FindingSeverity.HIGH,
                    title="Integration finding",
                    explanation="Integration explanation",
                    status=FindingStatus.OPEN,
                )
            )
            connection.execute(
                sa.insert(Remediation).values(
                    id=remediation_id,
                    owner_id=account.user_id,
                    project_id=project_id,
                    finding_id=finding_id,
                    proposed_diff="diff --git a/file b/file",
                    status=RemediationStatus.PROPOSED,
                )
            )
            connection.execute(
                sa.insert(PullRequest).values(
                    id=pull_request_id,
                    owner_id=account.user_id,
                    remediation_id=remediation_id,
                    repository_url="https://github.example.test/repo",
                    pull_request_number=7,
                    pull_request_url="https://github.example.test/repo/pull/7",
                    branch_name="trace/integration",
                )
            )
            connection.execute(
                sa.insert(LocalFileBackup).values(
                    id=backup_id,
                    owner_id=account.user_id,
                    remediation_id=remediation_id,
                    file_path="src/example.py",
                    backup_path=".trace-backups/example.py",
                    source_hash=b"source-hash",
                )
            )
        return {
            "review_id": review_id,
            "finding_id": finding_id,
            "remediation_id": remediation_id,
            "pull_request_id": pull_request_id,
            "backup_id": backup_id,
        }

    return create
