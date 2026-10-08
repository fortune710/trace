from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from agents.models import Agent
from auth.credential_service import CredentialConflict, CredentialService
from auth.credentials import CredentialCipher, EncryptedCredential
from auth.errors import ResourceConflict
from auth.models import AuthUser, UserStatus
from credentials.models import CredentialKind, CredentialProvider
from db.rls import principal_transaction
from db.types import ProjectSourceType
from findings.models import Finding, FindingSeverity
from projects.models import Project
from remediations.models import Remediation, RemediationStatus
from resources.services import ArtifactService, ReviewService
from reviews.models import (
    ReviewRun,
    ReviewRunAgent,
    ReviewRunAgentStatus,
    ReviewRunCategory,
    ReviewStatus,
)
from users.models import User


class BlockingCredentialCipher(CredentialCipher):
    def __init__(self, barrier: Barrier) -> None:
        super().__init__(key=b"c" * 32, key_version="test-v1")
        self._barrier = barrier

    def encrypt_json(
        self,
        value: dict[str, object],
        *,
        credential_id: UUID,
        owner_id: UUID,
        provider: str,
        credential_kind: str,
    ) -> EncryptedCredential:
        self._barrier.wait(timeout=10)
        return super().encrypt_json(
            value,
            credential_id=credential_id,
            owner_id=owner_id,
            provider=provider,
            credential_kind=credential_kind,
        )


class BlockingCredentialService(CredentialService):
    def __init__(self, *, barrier: Barrier, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._barrier = barrier

    def _mutation_row(self, *, owner_id: UUID, credential_id: UUID):  # type: ignore[no-untyped-def]
        row = super()._mutation_row(owner_id=owner_id, credential_id=credential_id)
        self._barrier.wait(timeout=10)
        return row


class BlockingReviewService(ReviewService):
    def __init__(self, *, barrier: Barrier, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._barrier = barrier

    def _read_retry_version(self, *, owner_id: UUID, review_id: UUID) -> int:
        version = super()._read_retry_version(owner_id=owner_id, review_id=review_id)
        self._barrier.wait(timeout=10)
        return version


class BlockingArtifactService(ArtifactService):
    def __init__(self, *, barrier: Barrier, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._barrier = barrier

    def _read_mutation_version(self, *, owner_id: UUID, remediation_id: UUID) -> int:
        version = super()._read_mutation_version(
            owner_id=owner_id, remediation_id=remediation_id
        )
        self._barrier.wait(timeout=10)
        return version


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    return database_url


def _create_user(connection: sa.Connection, user_id: UUID, prefix: str) -> None:
    connection.execute(
        sa.insert(AuthUser).values(
            id=user_id,
            email=f"{prefix}-{user_id}@example.test",
            status=UserStatus.ACTIVE,
        )
    )
    connection.execute(sa.insert(User).values(id=user_id))


def _run_concurrently(
    callables: list[Callable[[], object]],
) -> list[object | Exception]:
    def invoke(callable: Callable[[], object]) -> object | Exception:
        try:
            return callable()
        except Exception as error:  # noqa: BLE001 - preserve concurrent outcomes for assertions
            return error

    with ThreadPoolExecutor(max_workers=len(callables)) as executor:
        futures = [executor.submit(invoke, callable) for callable in callables]
        return [future.result() for future in futures]


@pytest.mark.integration
def test_credential_revoke_and_rotate_allow_one_concurrent_mutation() -> None:
    engine = sa.create_engine(_database_url())
    owner_id = uuid4()
    try:
        with engine.begin() as connection:
            _create_user(connection, owner_id, "mutation-credential")

        service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
        )
        metadata = service.create_or_replace(
            owner_id=owner_id,
            provider=CredentialProvider.GITHUB,
            kind=CredentialKind.OAUTH,
            payload={"access_token": "initial"},
        )

        revoke_service = BlockingCredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
            barrier=Barrier(2),
        )
        results = _run_concurrently(
            [
                lambda: revoke_service.revoke(
                    owner_id=owner_id, credential_id=metadata.id
                ),
                lambda: revoke_service.revoke(
                    owner_id=owner_id, credential_id=metadata.id
                ),
            ]
        )
        assert sum(result is None for result in results) == 1
        conflicts = [result for result in results if isinstance(result, Exception)]
        assert len(conflicts) == 1
        assert isinstance(conflicts[0], CredentialConflict)

        with pytest.raises(CredentialConflict, match="credential_already_revoked"):
            service.revoke(owner_id=owner_id, credential_id=metadata.id)

        metadata = service.create_or_replace(
            owner_id=owner_id,
            provider=CredentialProvider.GITHUB,
            kind=CredentialKind.OAUTH,
            payload={"access_token": "replacement"},
        )
        rotate_service = CredentialService(
            engine=engine,
            cipher=BlockingCredentialCipher(Barrier(2)),
        )
        results = _run_concurrently(
            [
                lambda: rotate_service.replace_payload(
                    owner_id=owner_id,
                    credential_id=metadata.id,
                    payload={"access_token": "rotated-a"},
                ),
                lambda: rotate_service.replace_payload(
                    owner_id=owner_id,
                    credential_id=metadata.id,
                    payload={"access_token": "rotated-b"},
                ),
            ]
        )
        assert (
            sum(
                result is not None and not isinstance(result, Exception)
                for result in results
            )
            == 1
        )
        conflicts = [result for result in results if isinstance(result, Exception)]
        assert len(conflicts) == 1
        assert isinstance(conflicts[0], CredentialConflict)

        # A later rotation is valid after the concurrent operation has settled.
        service.replace_payload(
            owner_id=owner_id,
            credential_id=metadata.id,
            payload={"access_token": "rotated-later"},
        )
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()


@pytest.mark.integration
def test_review_retry_allows_one_concurrent_retry_and_future_retry() -> None:
    engine = sa.create_engine(_database_url())
    owner_id = uuid4()
    project_id = uuid4()
    agent_id = uuid4()
    review_id = uuid4()
    try:
        with engine.begin() as connection:
            _create_user(connection, owner_id, "mutation-review")

        with principal_transaction(engine, owner_id) as connection:
            connection.execute(
                sa.insert(Project).values(
                    id=project_id,
                    owner_id=owner_id,
                    name="retry project",
                    source=ProjectSourceType.LOCAL,
                    local_path_hash=b"retry-project",
                )
            )
            connection.execute(
                sa.insert(Agent).values(
                    id=agent_id,
                    owner_id=owner_id,
                    name="retry agent",
                    review_category="security",
                    model_provider="trace",
                    model_name="test",
                )
            )
            connection.execute(
                sa.insert(ReviewRun).values(
                    id=review_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    source_revision="abc123",
                    status=ReviewStatus.FAILED,
                )
            )
            connection.execute(
                sa.insert(ReviewRunCategory).values(
                    owner_id=owner_id,
                    review_run_id=review_id,
                    category="security",
                )
            )
            connection.execute(
                sa.insert(ReviewRunAgent).values(
                    owner_id=owner_id,
                    review_run_id=review_id,
                    agent_id=agent_id,
                    status=ReviewRunAgentStatus.ASSIGNED,
                )
            )

        service = BlockingReviewService(engine=engine, barrier=Barrier(2))
        results = _run_concurrently(
            [
                lambda: service.retry(owner_id=owner_id, review_id=review_id),
                lambda: service.retry(owner_id=owner_id, review_id=review_id),
            ]
        )
        successful = [result for result in results if isinstance(result, dict)]
        conflicts = [result for result in results if isinstance(result, Exception)]
        assert len(successful) == 1
        assert len(conflicts) == 1
        assert isinstance(conflicts[0], ResourceConflict)

        # The original failed review remains retryable for a later operation.
        later = ReviewService(engine).retry(owner_id=owner_id, review_id=review_id)
        assert later["status"] == ReviewStatus.QUEUED
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()


@pytest.mark.integration
def test_remediation_decision_allows_one_concurrent_mutation() -> None:
    engine = sa.create_engine(_database_url())
    owner_id = uuid4()
    project_id = uuid4()
    agent_id = uuid4()
    review_id = uuid4()
    finding_id = uuid4()
    remediation_id = uuid4()
    try:
        with engine.begin() as connection:
            _create_user(connection, owner_id, "mutation-remediation")

        with principal_transaction(engine, owner_id) as connection:
            connection.execute(
                sa.insert(Project).values(
                    id=project_id,
                    owner_id=owner_id,
                    name="remediation project",
                    source=ProjectSourceType.LOCAL,
                    local_path_hash=b"remediation-project",
                )
            )
            connection.execute(
                sa.insert(Agent).values(
                    id=agent_id,
                    owner_id=owner_id,
                    name="remediation agent",
                    review_category="security",
                    model_provider="trace",
                    model_name="test",
                )
            )
            connection.execute(
                sa.insert(ReviewRun).values(
                    id=review_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    source_revision="abc123",
                    status=ReviewStatus.COMPLETED,
                )
            )
            connection.execute(
                sa.insert(ReviewRunCategory).values(
                    owner_id=owner_id,
                    review_run_id=review_id,
                    category="security",
                )
            )
            connection.execute(
                sa.insert(ReviewRunAgent).values(
                    owner_id=owner_id,
                    review_run_id=review_id,
                    agent_id=agent_id,
                    status=ReviewRunAgentStatus.COMPLETED,
                )
            )
            connection.execute(
                sa.insert(Finding).values(
                    id=finding_id,
                    owner_id=owner_id,
                    review_run_id=review_id,
                    agent_id=agent_id,
                    category="security",
                    severity=FindingSeverity.HIGH,
                    title="test finding",
                    explanation="test explanation",
                )
            )
            connection.execute(
                sa.insert(Remediation).values(
                    id=remediation_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    finding_id=finding_id,
                    proposed_diff="diff --git a/file b/file",
                    status=RemediationStatus.PROPOSED,
                )
            )

        service = BlockingArtifactService(engine=engine, barrier=Barrier(2))
        results = _run_concurrently(
            [
                lambda: service.set_remediation_status(
                    owner_id=owner_id,
                    remediation_id=remediation_id,
                    status=RemediationStatus.APPROVED,
                ),
                lambda: service.set_remediation_status(
                    owner_id=owner_id,
                    remediation_id=remediation_id,
                    status=RemediationStatus.APPROVED,
                ),
            ]
        )
        successful = [result for result in results if isinstance(result, dict)]
        conflicts = [result for result in results if isinstance(result, Exception)]
        assert len(successful) == 1
        assert len(conflicts) == 1
        assert isinstance(conflicts[0], ResourceConflict)

        with pytest.raises(ResourceConflict):
            ArtifactService(engine).set_remediation_status(
                owner_id=owner_id,
                remediation_id=remediation_id,
                status=RemediationStatus.REJECTED,
            )
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
