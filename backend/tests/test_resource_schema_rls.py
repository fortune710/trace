from __future__ import annotations

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa

from agents.models import Agent
from auth.models import AuthUser, UserStatus
from auth.uuids import uuid7
from credentials.models import (
    Credential,
    CredentialEncryptionProvider,
    CredentialKind,
    CredentialProvider,
)
from db.rls import principal_transaction
from db.types import RepositorySource
from external_repositories.models import ExternalRepository
from findings.models import Finding, FindingSeverity
from projects.models import Project, ProjectCategory
from remediations.models import Remediation, RemediationStatus
from reviews.models import (
    Review,
    ReviewAgent,
    ReviewAgentStatus,
    ReviewCategory,
    ReviewDispatchJob,
)
from users.models import User


def credential_values(owner_id: object, credential_id: object) -> dict[str, object]:
    return {
        "id": credential_id,
        "owner_id": owner_id,
        "provider": CredentialProvider.GITHUB,
        "credential_kind": CredentialKind.OAUTH,
        "ciphertext": b"ciphertext-only-test-value",
        "nonce": b"nonce",
        "key_version": "test-v1",
        "aad_version": "credential-v1",
        "encryption_provider": CredentialEncryptionProvider.LOCAL,
        "key_reference": "test-key",
    }


@pytest.mark.integration
def test_resource_graph_has_forced_rls_and_same_owner_relationships() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    engine = sa.create_engine(database_url)
    owner_id = uuid4()
    other_owner_id = uuid4()
    credential_id = uuid4()
    connection_id = uuid4()
    project_id = uuid4()
    agent_id = uuid4()
    second_agent_id = uuid4()
    run_id = uuid4()
    second_run_id = uuid4()
    finding_id = uuid4()
    remediation_id = uuid4()

    try:
        with engine.begin() as connection:
            for user_id, email in (
                (owner_id, f"resource-owner-{owner_id}@example.test"),
                (other_owner_id, f"resource-other-{other_owner_id}@example.test"),
            ):
                connection.execute(
                    sa.insert(AuthUser).values(
                        id=user_id,
                        email=email,
                        status=UserStatus.ACTIVE,
                    )
                )
                connection.execute(sa.insert(User).values(id=user_id))

        with principal_transaction(engine, owner_id) as connection:
            connection.execute(
                sa.insert(Credential).values(
                    **credential_values(owner_id, credential_id)
                )
            )
            connection.execute(
                sa.insert(ExternalRepository).values(
                    id=connection_id,
                    owner_id=owner_id,
                    source=RepositorySource.GITHUB,
                    external_user_id="github-user-1",
                    credential_id=credential_id,
                )
            )
            connection.execute(
                sa.insert(Project).values(
                    id=project_id,
                    owner_id=owner_id,
                    name="imported repository",
                    source=RepositorySource.GITHUB,
                    external_repository_id="repo-123",
                    external_repository_connection_id=connection_id,
                    category=ProjectCategory.OTHER,
                )
            )
            connection.execute(
                sa.insert(Agent).values(
                    id=agent_id,
                    owner_id=owner_id,
                    name="security agent",
                    review_category=ReviewCategory.SECURITY,
                    model_provider="openai",
                    model_name="test-model",
                )
            )
            connection.execute(
                sa.insert(Agent).values(
                    id=second_agent_id,
                    owner_id=owner_id,
                    name="legal agent",
                    review_category=ReviewCategory.LEGAL,
                    model_provider="openai",
                    model_name="test-model",
                )
            )
            connection.execute(
                sa.insert(Review).values(
                    id=run_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    source_revision="a" * 64,
                    source_kind=RepositorySource.LOCAL,
                    source_identifier="rls-local-source",
                    integrity_algorithm="sha256-directory-manifest-v1",
                )
            )
            connection.execute(
                sa.insert(Review).values(
                    id=second_run_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    source_revision="b" * 64,
                    source_kind=RepositorySource.LOCAL,
                    source_identifier="rls-local-source",
                    integrity_algorithm="sha256-directory-manifest-v1",
                )
            )
            connection.execute(
                sa.insert(ReviewAgent).values(
                    owner_id=owner_id,
                    review_id=run_id,
                    agent_id=agent_id,
                    agent_display_name="security agent",
                    agent_specialization=ReviewCategory.SECURITY,
                    agent_model_provider="openai",
                    agent_model_name="test-model",
                    agent_skills=[],
                    agent_configuration_version=1,
                    status=ReviewAgentStatus.ASSIGNED,
                )
            )
            connection.execute(
                sa.insert(ReviewAgent).values(
                    owner_id=owner_id,
                    review_id=run_id,
                    agent_id=second_agent_id,
                    agent_display_name="legal agent",
                    agent_specialization=ReviewCategory.LEGAL,
                    agent_model_provider="openai",
                    agent_model_name="test-model",
                    agent_skills=[],
                    agent_configuration_version=1,
                    status=ReviewAgentStatus.ASSIGNED,
                )
            )
            connection.execute(
                sa.insert(ReviewAgent).values(
                    owner_id=owner_id,
                    review_id=second_run_id,
                    agent_id=agent_id,
                    agent_display_name="security agent",
                    agent_specialization=ReviewCategory.SECURITY,
                    agent_model_provider="openai",
                    agent_model_name="test-model",
                    agent_skills=[],
                    agent_configuration_version=1,
                    status=ReviewAgentStatus.ASSIGNED,
                )
            )
            assignment_id = connection.execute(
                sa.select(ReviewAgent.id).where(
                    ReviewAgent.owner_id == owner_id,
                    ReviewAgent.review_id == run_id,
                    ReviewAgent.agent_id == agent_id,
                )
            ).scalar_one()
            connection.execute(
                sa.insert(ReviewDispatchJob).values(
                    idempotency_id=uuid7(),
                    owner_id=owner_id,
                    review_id=run_id,
                    review_agent_id=assignment_id,
                )
            )
            select_savepoint = connection.begin_nested()
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.select(ReviewDispatchJob)).all()
            select_savepoint.rollback()
            savepoint = connection.begin_nested()
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(
                    sa.insert(ReviewDispatchJob).values(
                        idempotency_id=uuid7(),
                        owner_id=owner_id,
                        review_id=run_id,
                        review_agent_id=assignment_id,
                    )
                )
            savepoint.rollback()
            connection.execute(
                sa.insert(Finding).values(
                    id=finding_id,
                    owner_id=owner_id,
                    review_id=run_id,
                    agent_id=agent_id,
                    category=ReviewCategory.SECURITY,
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
                    proposed_diff="diff",
                    status=RemediationStatus.PROPOSED,
                )
            )

            assert (
                connection.execute(
                    sa.select(sa.func.count()).select_from(ReviewAgent)
                ).scalar_one()
                == 3
            )
            assert (
                connection.execute(
                    sa.select(sa.func.count()).select_from(Finding)
                ).scalar_one()
                == 1
            )

            connection.execute(
                sa.update(ExternalRepository)
                .where(ExternalRepository.id == connection_id)
                .values(revoked_at=sa.func.current_timestamp())
            )
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(
                    sa.insert(Project).values(
                        id=uuid4(),
                        owner_id=owner_id,
                        name="revoked connection project",
                        source=RepositorySource.GITHUB,
                        external_repository_id="repo-456",
                        external_repository_connection_id=connection_id,
                    )
                )

        with principal_transaction(engine, other_owner_id) as connection:
            assert (
                connection.execute(sa.select(ExternalRepository)).scalars().all() == []
            )
            assert connection.execute(sa.select(Project)).scalars().all() == []
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(
                    sa.insert(Review).values(
                        id=uuid4(),
                        owner_id=other_owner_id,
                        project_id=project_id,
                        source_revision="cross-account",
                    )
                )
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(
                    sa.insert(Finding).values(
                        id=uuid4(),
                        owner_id=other_owner_id,
                        review_id=run_id,
                        agent_id=agent_id,
                        category=ReviewCategory.SECURITY,
                        severity=FindingSeverity.LOW,
                        title="cross-account finding",
                        explanation="must fail",
                    )
                )

        with engine.connect() as connection:
            rls_state = connection.execute(
                sa.text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid = (:table_name)::regclass"
                ),
                {"table_name": "public.findings"},
            ).one()
            assert rls_state == (True, True)
            assert (
                connection.execute(
                    sa.text(
                        "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'trace_app'"
                    )
                ).scalar_one()
                is False
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                sa.delete(AuthUser).where(AuthUser.id.in_([owner_id, other_owner_id]))
            )
        engine.dispose()
