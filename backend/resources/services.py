from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from enum import Enum
from typing import Any, NoReturn, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from agents.catalog import supports_model
from agents.models import Agent
from artifacts.models import LocalFileBackup, PullRequest
from audit.outbox import AuditRecorder
from auth.errors import AuthorizationDenied, ResourceConflict, ResourceNotFound
from auth.uuids import uuid7
from credentials.models import Credential, CredentialKind
from db.rls import principal_transaction
from db.types import RepositorySource
from external_repositories.models import ExternalRepository
from findings.models import Finding, FindingStatus
from notifications.models import NotificationEventType
from notifications.service import create_notification
from projects.models import Project, ProjectCategory
from remediations.models import Remediation, RemediationStatus
from reviews.models import (
    Review,
    ReviewAgent,
    ReviewAgentExecutionConfig,
    ReviewAgentStatus,
    ReviewDispatchJob,
    ReviewDispatchStatus,
    ReviewStatus,
)


class InvalidIdempotencyKey(ValueError):
    pass


def _orm_scalar_one_or_none(connection: sa.Connection, statement: Any) -> Any:
    with Session(bind=connection, expire_on_commit=False) as session:
        return session.execute(statement).scalar_one_or_none()


def _orm_scalar_one(connection: sa.Connection, statement: Any) -> Any:
    with Session(bind=connection, expire_on_commit=False) as session:
        return session.execute(statement).scalar_one()


def _orm_scalars_all(connection: sa.Connection, statement: Any) -> list[Any]:
    with Session(bind=connection, expire_on_commit=False) as session:
        return list(session.execute(statement).scalars().all())


def provision_external_repository(
    *, engine: Engine, owner_id: UUID, credential_id: UUID, external_user_id: str
) -> None:
    """Upsert provider-account metadata after a validated repository OAuth callback."""

    with principal_transaction(engine, owner_id) as connection:
        repository_id = _orm_scalar_one_or_none(
            connection,
            sa.select(ExternalRepository.id)
            .where(
                ExternalRepository.owner_id == owner_id,
                ExternalRepository.source == RepositorySource.GITHUB,
                ExternalRepository.external_user_id == external_user_id,
            )
            .order_by(
                ExternalRepository.created_at.desc(), ExternalRepository.id.desc()
            ),
        )
        if repository_id is None:
            connection.execute(
                sa.insert(ExternalRepository).values(
                    id=uuid7(),
                    owner_id=owner_id,
                    source=RepositorySource.GITHUB,
                    external_user_id=external_user_id,
                    credential_id=credential_id,
                    revoked_at=None,
                )
            )
        else:
            connection.execute(
                sa.update(ExternalRepository)
                .where(
                    ExternalRepository.id == repository_id,
                    ExternalRepository.owner_id == owner_id,
                )
                .values(
                    credential_id=credential_id,
                    revoked_at=None,
                    updated_at=sa.func.current_timestamp(),
                )
            )


def _value(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _hash_text(value: bytes | None) -> str | None:
    return value.hex() if value is not None else None


def _hash_bytes(value: str | None) -> bytes | None:
    return bytes.fromhex(value) if value is not None else None


def _raise_access(
    connection: sa.Connection, function: str, resource_id: UUID
) -> NoReturn:
    exists = connection.execute(
        sa.text(f"SELECT public.trace_{function}_exists(:resource_id)"),
        {"resource_id": resource_id},
    ).scalar_one()
    if bool(exists):
        raise AuthorizationDenied()
    raise ResourceNotFound()


def _page[T](rows: Sequence[T], limit: int, offset: int) -> tuple[list[T], int | None]:
    values = list(rows)
    next_offset = offset + limit if len(values) > limit else None
    return values[:limit], next_offset


def _project_response(project: Project) -> dict[str, object]:
    return {
        "id": project.id,
        "name": project.name,
        "source": project.source,
        "external_repository_id": project.external_repository_id,
        "external_repository_connection_id": project.external_repository_connection_id,
        "repository_owner": project.repository_owner,
        "repository_name": project.repository_name,
        "branch_name": project.branch_name,
        "repository_visibility": project.repository_visibility,
        "imported_at": project.imported_at,
        "source_hash": _hash_text(project.source_hash),
        "current_revision": project.current_revision,
        "category": project.category,
        "auto_create_pull_requests": project.auto_create_pull_requests,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "archived_at": project.archived_at,
    }


class ProjectService:
    def __init__(
        self,
        engine: Engine,
        repository_name_resolver: Callable[[UUID, UUID, str], str | None] | None = None,
        repository_service: Any | None = None,
    ) -> None:
        self._engine = engine
        self._repository_name_resolver = repository_name_resolver
        self._repository_service = repository_service

    def list(
        self,
        *,
        owner_id: UUID,
        source: RepositorySource | None,
        category: ProjectCategory | None,
        archived: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int | None]:
        with principal_transaction(self._engine, owner_id) as connection:
            query = sa.select(Project).where(Project.owner_id == owner_id)
            query = query.where(
                Project.archived_at.is_not(None)
                if archived
                else Project.archived_at.is_(None)
            )
            if source is not None:
                query = query.where(Project.source == source)
            if category is not None:
                query = query.where(Project.category == category)
            rows = cast(
                list[Project],
                _orm_scalars_all(
                    connection,
                    query.order_by(Project.created_at.desc(), Project.id.desc())
                    .offset(offset)
                    .limit(limit + 1),
                ),
            )
        selected, next_offset = _page(rows, limit, offset)
        return [_project_response(project) for project in selected], next_offset

    def get(self, *, owner_id: UUID, project_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            project = cast(
                Project | None,
                _orm_scalar_one_or_none(
                    connection,
                    sa.select(Project).where(
                        Project.id == project_id, Project.owner_id == owner_id
                    ),
                ),
            )
            if project is None:
                _raise_access(connection, "project", project_id)
        return _project_response(project)

    def create(self, *, owner_id: UUID, values: dict[str, Any]) -> dict[str, object]:
        if not isinstance(owner_id, UUID):
            raise TypeError("authenticated owner is required")
        source = values["source"]
        if not isinstance(source, RepositorySource):
            source = RepositorySource(str(source))
        external_id = values.get("repository_id")
        local_hash = values.get("local_path_hash")
        github_connection_id: UUID | None = None
        github_external_id: str | None = None
        if source is RepositorySource.GITHUB:
            if (
                not isinstance(external_id, str)
                or not isinstance(values.get("name"), str)
                or not isinstance(values.get("branch_name"), str)
                or not isinstance(values.get("category"), ProjectCategory)
                or local_hash is not None
                or values.get("current_revision") is not None
            ):
                raise ValueError("GitHub project fields are invalid")
            assert isinstance(external_id, str)
            github_external_id = external_id
        elif external_id is not None or not isinstance(local_hash, str):
            raise ValueError("Local project fields are invalid")

        repository_metadata = None
        branch_metadata = None
        if source is RepositorySource.GITHUB and values.get("branch_name"):
            if self._repository_service is None:
                raise ValueError("Repository service is unavailable")
            repository_metadata, branch_metadata = (
                self._repository_service.resolve_branch(
                    owner_id=owner_id,
                    source=RepositorySource.GITHUB.value,
                    repository_identifier=github_external_id,
                    branch_name=values["branch_name"],
                )
            )
            github_connection_id = self._repository_service.connection_id(
                owner_id=owner_id,
                source=RepositorySource.GITHUB.value,
            )

        try:
            with principal_transaction(self._engine, owner_id) as connection:
                if source is RepositorySource.GITHUB:
                    assert github_connection_id is not None
                    assert github_external_id is not None
                    repository = _orm_scalar_one_or_none(
                        connection,
                        sa.select(ExternalRepository.id).where(
                            ExternalRepository.id == github_connection_id,
                            ExternalRepository.owner_id == owner_id,
                            ExternalRepository.source == RepositorySource.GITHUB,
                            ExternalRepository.revoked_at.is_(None),
                        ),
                    )
                    if repository is None:
                        _raise_access(
                            connection, "external_repository", github_connection_id
                        )
                    name = values["name"]
                else:
                    name = values.get("name")
                    if not isinstance(name, str):
                        raise ValueError("Local project name is required")

                project_id = uuid7()
                connection.execute(
                    sa.insert(Project).values(
                        id=project_id,
                        owner_id=owner_id,
                        name=name,
                        source=source,
                        external_repository_id=github_external_id
                        if source is RepositorySource.GITHUB
                        else None,
                        external_repository_connection_id=github_connection_id
                        if source is RepositorySource.GITHUB
                        else None,
                        repository_owner=(
                            repository_metadata.owner_login
                            if repository_metadata is not None
                            else None
                        ),
                        repository_name=(
                            repository_metadata.name
                            if repository_metadata is not None
                            else None
                        ),
                        branch_name=(
                            branch_metadata.name
                            if branch_metadata is not None
                            else None
                        ),
                        repository_visibility=(
                            repository_metadata.visibility
                            if repository_metadata is not None
                            else None
                        ),
                        local_path_hash=_hash_bytes(cast(str, local_hash))
                        if isinstance(local_hash, str)
                        else None,
                        source_hash=_hash_bytes(cast(str, values.get("source_hash")))
                        if isinstance(values.get("source_hash"), str)
                        else None,
                        current_revision=(
                            branch_metadata.commit_sha
                            if branch_metadata is not None
                            else values.get("current_revision")
                        ),
                        category=values.get("category") or ProjectCategory.OTHER,
                        auto_create_pull_requests=bool(
                            values.get("auto_create_pull_requests", False)
                        ),
                        imported_at=sa.func.current_timestamp()
                        if repository_metadata is not None
                        else None,
                    )
                )
                project = cast(
                    Project,
                    _orm_scalar_one(
                        connection,
                        sa.select(Project).where(
                            Project.id == project_id, Project.owner_id == owner_id
                        ),
                    ),
                )
        except sa.exc.IntegrityError as error:
            raise ResourceConflict("project_conflict") from error
        return _project_response(project)

    def update(
        self, *, owner_id: UUID, project_id: UUID, values: dict[str, Any]
    ) -> dict[str, object]:
        if not values:
            return self.get(owner_id=owner_id, project_id=project_id)
        try:
            with principal_transaction(self._engine, owner_id) as connection:
                project = cast(
                    Project | None,
                    _orm_scalar_one_or_none(
                        connection,
                        sa.select(Project).where(
                            Project.id == project_id, Project.owner_id == owner_id
                        ),
                    ),
                )
                if project is None:
                    _raise_access(connection, "project", project_id)
                connection.execute(
                    sa.update(Project)
                    .where(Project.id == project_id, Project.owner_id == owner_id)
                    .values(**values, updated_at=sa.func.current_timestamp())
                )
                project = cast(
                    Project,
                    _orm_scalar_one(
                        connection,
                        sa.select(Project).where(
                            Project.id == project_id, Project.owner_id == owner_id
                        ),
                    ),
                )
        except sa.exc.IntegrityError as error:
            raise ResourceConflict("project_conflict") from error
        return _project_response(project)

    def archive(self, *, owner_id: UUID, project_id: UUID) -> None:
        self._set_archive(owner_id=owner_id, project_id=project_id, archived=True)

    def restore(self, *, owner_id: UUID, project_id: UUID) -> dict[str, object]:
        self._set_archive(owner_id=owner_id, project_id=project_id, archived=False)
        return self.get(owner_id=owner_id, project_id=project_id)

    def _set_archive(self, *, owner_id: UUID, project_id: UUID, archived: bool) -> None:
        try:
            with principal_transaction(self._engine, owner_id) as connection:
                result = connection.execute(
                    sa.update(Project)
                    .where(Project.id == project_id, Project.owner_id == owner_id)
                    .values(
                        archived_at=sa.func.current_timestamp() if archived else None,
                        updated_at=sa.func.current_timestamp(),
                    )
                )
                if result.rowcount != 1:
                    _raise_access(connection, "project", project_id)
        except sa.exc.IntegrityError as error:
            raise ResourceConflict("project_conflict") from error


def _agent_response(agent: Agent) -> dict[str, object]:
    return {
        "id": agent.id,
        "name": agent.name,
        "personality": agent.personality,
        "review_category": agent.review_category,
        "model_provider": agent.model_provider,
        "model_name": agent.model_name,
        "avatar": agent.avatar,
        "skills": agent.skills,
        "credential_id": agent.credential_id,
        "configuration_version": agent.configuration_version,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "disabled_at": agent.disabled_at,
    }


class AgentService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(
        self, *, owner_id: UUID, include_disabled: bool, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int | None]:
        with principal_transaction(self._engine, owner_id) as connection:
            query = sa.select(Agent).where(Agent.owner_id == owner_id)
            if not include_disabled:
                query = query.where(Agent.disabled_at.is_(None))
            rows = cast(
                list[Agent],
                _orm_scalars_all(
                    connection,
                    query.order_by(Agent.created_at.desc(), Agent.id.desc())
                    .offset(offset)
                    .limit(limit + 1),
                ),
            )
        selected, next_offset = _page(rows, limit, offset)
        return [_agent_response(agent) for agent in selected], next_offset

    def get(self, *, owner_id: UUID, agent_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            agent = self._owned_agent(connection, owner_id, agent_id)
        return _agent_response(agent)

    def create(self, *, owner_id: UUID, values: dict[str, Any]) -> dict[str, object]:
        if not supports_model(values["model_provider"], values["model_name"]):
            raise UnsupportedAgentModel()
        try:
            with principal_transaction(self._engine, owner_id) as connection:
                self._validate_credential(
                    connection,
                    owner_id,
                    values.get("credential_id"),
                    values["model_provider"],
                )
                agent_id = uuid7()
                connection.execute(
                    sa.insert(Agent).values(id=agent_id, owner_id=owner_id, **values)
                )
                agent = cast(
                    Agent,
                    _orm_scalar_one(
                        connection,
                        sa.select(Agent).where(
                            Agent.id == agent_id, Agent.owner_id == owner_id
                        ),
                    ),
                )
        except sa.exc.IntegrityError as error:
            raise ResourceConflict("agent_conflict") from error
        return _agent_response(agent)

    def update(
        self, *, owner_id: UUID, agent_id: UUID, values: dict[str, Any]
    ) -> dict[str, object]:
        try:
            with principal_transaction(self._engine, owner_id) as connection:
                agent = self._owned_agent(connection, owner_id, agent_id)
                model_provider = values.get("model_provider", agent.model_provider)
                model_name = values.get("model_name", agent.model_name)
                if not supports_model(model_provider, model_name):
                    raise UnsupportedAgentModel()
                credential_id = values.get("credential_id", agent.credential_id)
                self._validate_credential(
                    connection, owner_id, credential_id, model_provider
                )
                connection.execute(
                    sa.update(Agent)
                    .where(Agent.id == agent_id, Agent.owner_id == owner_id)
                    .values(
                        **values,
                        configuration_version=Agent.configuration_version + 1,
                        updated_at=sa.func.current_timestamp(),
                    )
                )
                agent = _orm_scalar_one(
                    connection,
                    sa.select(Agent).where(
                        Agent.id == agent_id, Agent.owner_id == owner_id
                    ),
                )
        except sa.exc.IntegrityError as error:
            raise ResourceConflict("agent_conflict") from error
        return _agent_response(agent)

    def disable(self, *, owner_id: UUID, agent_id: UUID) -> None:
        with principal_transaction(self._engine, owner_id) as connection:
            result = connection.execute(
                sa.update(Agent)
                .where(
                    Agent.id == agent_id,
                    Agent.owner_id == owner_id,
                    Agent.disabled_at.is_(None),
                )
                .values(
                    disabled_at=sa.func.current_timestamp(),
                    updated_at=sa.func.current_timestamp(),
                )
            )
            if result.rowcount != 1:
                _raise_access(connection, "agent", agent_id)

    @staticmethod
    def _owned_agent(
        connection: sa.Connection, owner_id: UUID, agent_id: UUID
    ) -> Agent:
        agent = cast(
            Agent | None,
            _orm_scalar_one_or_none(
                connection,
                sa.select(Agent).where(
                    Agent.id == agent_id, Agent.owner_id == owner_id
                ),
            ),
        )
        if agent is None:
            _raise_access(connection, "agent", agent_id)
        return agent

    @staticmethod
    def _validate_credential(
        connection: sa.Connection,
        owner_id: UUID,
        credential_id: object,
        model_provider: object,
    ) -> None:
        if credential_id is None:
            return
        if not isinstance(credential_id, UUID):
            raise TypeError("Credential ID is invalid")
        credential = cast(
            Credential | None,
            _orm_scalar_one_or_none(
                connection,
                sa.select(Credential).where(
                    Credential.id == credential_id,
                    Credential.owner_id == owner_id,
                    Credential.revoked_at.is_(None),
                ),
            ),
        )
        if credential is None:
            _raise_access(connection, "credential", credential_id)
        if credential.provider.value != _value(model_provider):
            raise ResourceConflict("credential_provider_mismatch")
        if credential.credential_kind != CredentialKind.API_KEY:
            raise ResourceConflict("credential_kind_mismatch")


class UnsupportedAgentModel(ValueError):
    """Raised when an agent request uses a provider/model pair outside the catalog."""


def _review_response(
    connection: sa.Connection, owner_id: UUID, review_id: UUID
) -> dict[str, object]:
    review = (
        connection.execute(
            sa.select(Review.__table__).where(
                Review.id == review_id, Review.owner_id == owner_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if review is None:
        _raise_access(connection, "review", review_id)
    assigned = (
        connection.execute(
            sa.select(
                ReviewAgent.id.label("assignment_id"),
                ReviewAgent.status.label("assignment_status"),
                ReviewAgent.assigned_at,
                ReviewAgent.started_at.label("assignment_started_at"),
                ReviewAgent.completed_at.label("assignment_completed_at"),
                ReviewAgent.agent_id,
                ReviewAgent.agent_display_name,
                ReviewAgent.agent_specialization,
                ReviewAgent.agent_model_provider,
                ReviewAgent.agent_model_name,
                ReviewAgent.agent_personality,
                ReviewAgent.agent_skills,
                ReviewAgent.agent_configuration_version,
            )
            .where(
                ReviewAgent.owner_id == owner_id,
                ReviewAgent.review_id == review_id,
            )
            .order_by(ReviewAgent.agent_id)
        )
        .mappings()
        .all()
    )
    return {
        "id": review["id"],
        "project_id": review["project_id"],
        "source_revision": review["source_revision"],
        "source_snapshot": {
            "source_kind": review["source_kind"],
            "source_identifier": review["source_identifier"],
            "integrity_algorithm": review["integrity_algorithm"],
            "revision": review["source_revision"],
            "captured_at": review["source_captured_at"],
        },
        "status": review["status"],
        "started_at": review["started_at"],
        "completed_at": review["completed_at"],
        "created_at": review["created_at"],
        "updated_at": review["updated_at"],
        "agents": [
            {
                "assignment_id": assignment["assignment_id"],
                "agent_id": assignment["agent_id"],
                "name": assignment["agent_display_name"],
                "review_category": assignment["agent_specialization"],
                "model_provider": assignment["agent_model_provider"],
                "model_name": assignment["agent_model_name"],
                "personality": assignment["agent_personality"],
                "skills": assignment["agent_skills"],
                "configuration_version": assignment["agent_configuration_version"],
                "status": assignment["assignment_status"],
                "assigned_at": assignment["assigned_at"],
                "started_at": assignment["assignment_started_at"],
                "completed_at": assignment["assignment_completed_at"],
            }
            for assignment in assigned
        ],
    }


_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_LOCAL_SOURCE_ALGORITHM = "sha256-directory-manifest-v1"
_GITHUB_SOURCE_ALGORITHM = "git-commit-sha1-v1"
_SENSITIVE_CONFIGURATION_KEY = re.compile(
    r"(?:credential|token|secret|password|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)


def _idempotency_key_digest(key: str | None) -> bytes:
    """Validate an opaque HTTP idempotency key and retain only its digest."""

    if (
        key is None
        or not 1 <= len(key) <= 255
        or key.strip() != key
        or any(not 0x21 <= ord(character) <= 0x7E for character in key)
    ):
        raise InvalidIdempotencyKey("Idempotency-Key is invalid")
    return hashlib.sha256(key.encode("ascii")).digest()


def _review_request_digest(
    *,
    project_id: UUID,
    agent_ids: Sequence[UUID],
    local_source_snapshot: object = None,
) -> bytes:
    """Hash the semantic request shape so selected-agent order does not matter."""

    payload = json.dumps(
        {
            "agent_ids": sorted(str(agent_id) for agent_id in agent_ids),
            "local_source_snapshot": local_source_snapshot,
            "project_id": str(project_id),
        },
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("ascii")).digest()


def _local_source_identity_hash(source_id: UUID) -> bytes:
    return hashlib.sha256(
        b"trace-local-source-id-v1\0" + str(source_id).encode("ascii")
    ).digest()


def _safe_review_agent_skills(skills: list[object]) -> list[object]:
    """Copy only serializable, non-secret behavioral configuration."""

    def copy_value(value: object) -> object:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list):
            return [copy_value(item) for item in value]
        if isinstance(value, dict):
            copied: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str) or _SENSITIVE_CONFIGURATION_KEY.search(key):
                    raise ResourceConflict("agent_configuration_unsafe")
                copied[key] = copy_value(item)
            return copied
        raise ResourceConflict("agent_configuration_unsafe")

    return [copy_value(skill) for skill in skills]


def _resolve_review_source_revision(project: Project) -> str:
    """Compatibility helper for stored project source values."""

    if project.source is RepositorySource.GITHUB:
        revision = project.current_revision
        if isinstance(revision, str) and _COMMIT_SHA.fullmatch(revision):
            return revision.lower()
    elif project.source is RepositorySource.LOCAL:
        source_hash = project.source_hash
        if isinstance(source_hash, bytes) and len(source_hash) == 32:
            return source_hash.hex()
    raise ResourceConflict("project_source_revision_invalid")


def _resolve_local_review_snapshot(
    project: Project, supplied: object
) -> tuple[RepositorySource, str, str, str]:
    if not isinstance(supplied, dict):
        raise ResourceConflict("local_source_snapshot_required")
    source_id = supplied.get("source_id")
    algorithm = supplied.get("integrity_algorithm")
    digest = supplied.get("digest")
    if (
        not isinstance(source_id, UUID)
        or algorithm != _LOCAL_SOURCE_ALGORITHM
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or project.local_path_hash != _local_source_identity_hash(source_id)
    ):
        raise ResourceConflict("project_source_revision_invalid")
    return RepositorySource.LOCAL, str(source_id), algorithm, digest


def _resolve_github_review_snapshot(
    project: Project, repository_service: Any | None, owner_id: UUID
) -> tuple[RepositorySource, str, str, str]:
    repository_id = project.external_repository_id
    branch_name = project.branch_name
    if not isinstance(repository_id, str) or not isinstance(branch_name, str):
        raise ResourceConflict("project_source_revision_invalid")
    if repository_service is not None:
        _, branch = repository_service.resolve_branch(
            owner_id=owner_id,
            source=RepositorySource.GITHUB.value,
            repository_identifier=repository_id,
            branch_name=branch_name,
        )
        revision = branch.commit_sha
    else:
        revision = project.current_revision
    if not isinstance(revision, str) or not _COMMIT_SHA.fullmatch(revision):
        raise ResourceConflict("project_source_revision_invalid")
    return (
        RepositorySource.GITHUB,
        repository_id,
        _GITHUB_SOURCE_ALGORITHM,
        revision.lower(),
    )


class ReviewService:
    def __init__(self, engine: Engine, repository_service: Any | None = None) -> None:
        self._engine = engine
        self._repository_service = repository_service

    def create(
        self,
        *,
        owner_id: UUID,
        values: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, object]:
        agent_ids = values["agent_ids"]
        if not agent_ids or len(set(agent_ids)) != len(agent_ids):
            raise ValueError("Review agents must be unique and non-empty")
        key_digest = _idempotency_key_digest(idempotency_key)
        request_digest = _review_request_digest(
            project_id=values["project_id"],
            agent_ids=agent_ids,
            local_source_snapshot=values.get("local_source_snapshot"),
        )
        try:
            with principal_transaction(self._engine, owner_id) as connection:
                existing = (
                    connection.execute(
                        sa.select(Review.__table__).where(
                            Review.owner_id == owner_id,
                            Review.idempotency_key_digest == key_digest,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if existing["request_digest"] != request_digest:
                        raise ResourceConflict("idempotency_key_reused")
                    return _review_response(connection, owner_id, existing["id"])
                project = cast(
                    Project | None,
                    _orm_scalar_one_or_none(
                        connection,
                        sa.select(Project).where(
                            Project.id == values["project_id"],
                            Project.owner_id == owner_id,
                        ),
                    ),
                )
                if project is None:
                    _raise_access(connection, "project", values["project_id"])
                if project.archived_at is not None:
                    raise ResourceConflict("project_archived")
                if project.source is RepositorySource.LOCAL:
                    (
                        source_kind,
                        source_identifier,
                        integrity_algorithm,
                        source_revision,
                    ) = _resolve_local_review_snapshot(
                        project, values.get("local_source_snapshot")
                    )
                else:
                    if values.get("local_source_snapshot") is not None:
                        raise ResourceConflict("github_source_snapshot_forbidden")
                    (
                        source_kind,
                        source_identifier,
                        integrity_algorithm,
                        source_revision,
                    ) = _resolve_github_review_snapshot(
                        project, self._repository_service, owner_id
                    )
                agents: list[Agent] = []
                for agent_id in agent_ids:
                    agent = cast(
                        Agent | None,
                        _orm_scalar_one_or_none(
                            connection,
                            sa.select(Agent).where(
                                Agent.id == agent_id, Agent.owner_id == owner_id
                            ),
                        ),
                    )
                    if agent is None:
                        _raise_access(connection, "agent", agent_id)
                    if agent.disabled_at is not None:
                        raise ResourceConflict("agent_disabled")
                    agents.append(agent)
                review_id = uuid7()
                connection.execute(
                    sa.insert(Review).values(
                        id=review_id,
                        owner_id=owner_id,
                        project_id=project.id,
                        source_revision=source_revision,
                        source_kind=source_kind,
                        source_identifier=source_identifier,
                        integrity_algorithm=integrity_algorithm,
                        status=ReviewStatus.QUEUED,
                        idempotency_id=uuid7(),
                        idempotency_key_digest=key_digest,
                        request_digest=request_digest,
                    )
                )
                assignments = [
                    {
                        "id": uuid7(),
                        "owner_id": owner_id,
                        "review_id": review_id,
                        "agent_id": agent.id,
                        "agent_display_name": agent.name,
                        "agent_specialization": agent.review_category,
                        "agent_model_provider": _value(agent.model_provider),
                        "agent_model_name": agent.model_name,
                        "agent_personality": agent.personality,
                        "agent_skills": _safe_review_agent_skills(agent.skills),
                        "agent_configuration_version": agent.configuration_version,
                        "status": ReviewAgentStatus.ASSIGNED,
                    }
                    for agent in agents
                ]
                connection.execute(sa.insert(ReviewAgent), assignments)
                connection.execute(
                    sa.insert(ReviewAgentExecutionConfig),
                    [
                        {
                            "owner_id": owner_id,
                            "review_id": review_id,
                            "review_agent_id": assignment["id"],
                            "credential_id": agent.credential_id,
                        }
                        for assignment, agent in zip(assignments, agents, strict=True)
                    ],
                )
                connection.execute(
                    sa.insert(ReviewDispatchJob),
                    [
                        {
                            "idempotency_id": uuid7(),
                            "owner_id": owner_id,
                            "review_id": review_id,
                            "review_agent_id": assignment["id"],
                            "status": ReviewDispatchStatus.PENDING,
                        }
                        for assignment in assignments
                    ],
                )
                create_notification(
                    connection,
                    owner_id=owner_id,
                    event_type=NotificationEventType.REVIEW_QUEUED,
                    dedupe_key=f"review:{review_id}:queued",
                    review_id=review_id,
                )
        except sa.exc.IntegrityError as error:
            # A concurrent identical request can win the unique idempotency
            # index after this transaction performed its initial lookup.
            with principal_transaction(self._engine, owner_id) as connection:
                existing = (
                    connection.execute(
                        sa.select(Review.__table__).where(
                            Review.owner_id == owner_id,
                            Review.idempotency_key_digest == key_digest,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if existing["request_digest"] != request_digest:
                        raise ResourceConflict("idempotency_key_reused") from error
                    return _review_response(connection, owner_id, existing["id"])
            raise ResourceConflict("review_conflict") from error
        with principal_transaction(self._engine, owner_id) as connection:
            response = _review_response(connection, owner_id, review_id)
        return response

    def list(
        self,
        *,
        owner_id: UUID,
        project_id: UUID | None,
        status: ReviewStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int | None]:
        with principal_transaction(self._engine, owner_id) as connection:
            query = sa.select(Review).where(Review.owner_id == owner_id)
            if project_id is not None:
                query = query.where(Review.project_id == project_id)
            if status is not None:
                query = query.where(Review.status == status)
            reviews = cast(
                list[Review],
                _orm_scalars_all(
                    connection,
                    query.order_by(Review.created_at.desc(), Review.id.desc())
                    .offset(offset)
                    .limit(limit + 1),
                ),
            )
            selected, next_offset = _page(reviews, limit, offset)
            result = [
                _review_response(connection, owner_id, review.id) for review in selected
            ]
        return result, next_offset

    def get(self, *, owner_id: UUID, review_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            return _review_response(connection, owner_id, review_id)

    def cancel(self, *, owner_id: UUID, review_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            review = self._owned_review(
                connection, owner_id, review_id, for_update=True
            )
            if review["status"] is not ReviewStatus.QUEUED:
                raise ResourceConflict("review_state_conflict")
            now = sa.func.current_timestamp()
            connection.execute(
                sa.update(Review)
                .where(Review.id == review_id, Review.owner_id == owner_id)
                .values(
                    status=ReviewStatus.CANCELLED,
                    updated_at=now,
                )
            )
            connection.execute(
                sa.text(
                    "SELECT private.cancel_review_dispatch_jobs(:owner_id, :review_id)"
                ),
                {"owner_id": owner_id, "review_id": review_id},
            )
            return _review_response(connection, owner_id, review_id)

    @staticmethod
    def _owned_review(
        connection: sa.Connection,
        owner_id: UUID,
        review_id: UUID,
        *,
        for_update: bool = False,
    ) -> sa.RowMapping:
        query = sa.select(Review.__table__).where(
            Review.id == review_id, Review.owner_id == owner_id
        )
        if for_update:
            query = query.with_for_update()
        review = connection.execute(query).mappings().one_or_none()
        if review is None:
            _raise_access(connection, "review", review_id)
        return review


class FindingService:
    def __init__(
        self, engine: Engine, audit_recorder: AuditRecorder | None = None
    ) -> None:
        self._engine = engine
        self._audit_recorder = audit_recorder

    def list_for_review(
        self,
        *,
        owner_id: UUID,
        review_id: UUID,
        filters: dict[str, object],
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int | None]:
        with principal_transaction(self._engine, owner_id) as connection:
            review = connection.execute(
                sa.select(Review.id).where(
                    Review.id == review_id, Review.owner_id == owner_id
                )
            ).scalar_one_or_none()
            if review is None:
                _raise_access(connection, "review", review_id)
            query = sa.select(Finding).where(
                Finding.owner_id == owner_id, Finding.review_id == review_id
            )
            for field in ("category", "severity", "status", "agent_id"):
                if filters.get(field) is not None:
                    query = query.where(getattr(Finding, field) == filters[field])
            if filters.get("exclude_status") is not None:
                query = query.where(Finding.status != filters["exclude_status"])
            findings = cast(
                list[Finding],
                _orm_scalars_all(
                    connection,
                    query.order_by(Finding.created_at.desc(), Finding.id.desc())
                    .offset(offset)
                    .limit(limit + 1),
                ),
            )
            selected, next_offset = _page(findings, limit, offset)
            review_agents = {
                review_agent.agent_id: review_agent
                for review_agent in cast(
                    list[ReviewAgent],
                    _orm_scalars_all(
                        connection,
                        sa.select(ReviewAgent).where(
                            ReviewAgent.owner_id == owner_id,
                            ReviewAgent.review_id == review_id,
                            ReviewAgent.agent_id.in_(
                                {finding.agent_id for finding in selected}
                            ),
                        ),
                    ),
                )
            }
            responses = [
                _finding_response(finding, review_agents[finding.agent_id])
                for finding in selected
            ]
        return responses, next_offset

    def get(self, *, owner_id: UUID, finding_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            finding = self._owned_finding(connection, owner_id, finding_id)
            return self._response(connection, finding)

    def update_status(
        self,
        *,
        owner_id: UUID,
        finding_id: UUID,
        status: FindingStatus,
        request_id: str,
    ) -> dict[str, object]:
        allowed = {
            FindingStatus.OPEN: {
                FindingStatus.ACCEPTED,
                FindingStatus.DISMISSED,
            },
            FindingStatus.ACCEPTED: {FindingStatus.RESOLVED},
            FindingStatus.RESOLVED: {FindingStatus.ACCEPTED},
            FindingStatus.DISMISSED: {FindingStatus.OPEN},
        }
        with principal_transaction(self._engine, owner_id) as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(CAST(:finding_lock_key AS text), 0))"
                ),
                {"finding_lock_key": str(finding_id)},
            )
            finding = self._owned_finding(
                connection, owner_id, finding_id, for_update=True
            )
            previous_status = finding.status
            if status not in allowed[previous_status]:
                raise ResourceConflict("finding_state_conflict")
            connection.execute(
                sa.update(Finding)
                .where(Finding.id == finding_id, Finding.owner_id == owner_id)
                .values(
                    status=status,
                    status_changed_at=sa.func.current_timestamp(),
                    updated_at=sa.func.current_timestamp(),
                )
            )
            if self._audit_recorder is not None:
                self._audit_recorder.create_event(
                    event_type="resource.finding.triaged",
                    request_id=request_id,
                    owner_id=owner_id,
                    fields={
                        "finding_id": str(finding_id),
                        "review_id": str(finding.review_id),
                        "from_status": previous_status.value,
                        "to_status": status.value,
                    },
                    connection=connection,
                )
            finding = self._owned_finding(connection, owner_id, finding_id)
            return self._response(connection, finding)

    @staticmethod
    def _response(connection: sa.Connection, finding: Finding) -> dict[str, object]:
        review_agent = cast(
            ReviewAgent,
            _orm_scalar_one(
                connection,
                sa.select(ReviewAgent).where(
                    ReviewAgent.owner_id == finding.owner_id,
                    ReviewAgent.review_id == finding.review_id,
                    ReviewAgent.agent_id == finding.agent_id,
                ),
            ),
        )
        return _finding_response(finding, review_agent)

    @staticmethod
    def _owned_finding(
        connection: sa.Connection,
        owner_id: UUID,
        finding_id: UUID,
        *,
        for_update: bool = False,
    ) -> Finding:
        query = sa.select(Finding).where(
            Finding.id == finding_id, Finding.owner_id == owner_id
        )
        if for_update:
            query = query.with_for_update()
        finding = cast(
            Finding | None,
            _orm_scalar_one_or_none(
                connection,
                query,
            ),
        )
        if finding is None:
            _raise_access(connection, "finding", finding_id)
        return finding


def _finding_response(finding: Finding, review_agent: ReviewAgent) -> dict[str, object]:
    return {
        "id": finding.id,
        "review_id": finding.review_id,
        "agent_id": finding.agent_id,
        "reviewing_agent": {
            "assignment_id": review_agent.id,
            "agent_id": review_agent.agent_id,
            "display_name": review_agent.agent_display_name,
            "specialization": review_agent.agent_specialization,
        },
        "category": finding.category,
        "severity": finding.severity,
        "title": finding.title,
        "explanation": finding.explanation,
        "evidence": finding.evidence,
        "source_location": finding.source_location,
        "recommendation": finding.recommendation,
        "status": finding.status,
        "status_changed_at": finding.status_changed_at,
        "created_at": finding.created_at,
        "updated_at": finding.updated_at,
    }


class ArtifactService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_remediation(
        self, *, owner_id: UUID, finding_id: UUID, proposed_diff: str
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            row = connection.execute(
                sa.select(Finding.id, Review.project_id)
                .join(
                    Review,
                    sa.and_(
                        Review.id == Finding.review_id,
                        Review.owner_id == Finding.owner_id,
                    ),
                )
                .where(Finding.id == finding_id, Finding.owner_id == owner_id)
            ).one_or_none()
            if row is None:
                _raise_access(connection, "finding", finding_id)
            assert row is not None
            remediation_id = uuid7()
            connection.execute(
                sa.insert(Remediation).values(
                    id=remediation_id,
                    owner_id=owner_id,
                    project_id=row.project_id,
                    finding_id=finding_id,
                    proposed_diff=proposed_diff,
                    status=RemediationStatus.PROPOSED,
                )
            )
            remediation = (
                connection.execute(
                    sa.select(Remediation.__table__).where(
                        Remediation.id == remediation_id,
                        Remediation.owner_id == owner_id,
                    )
                )
                .mappings()
                .one()
            )
        return _remediation_response(remediation)

    def list_remediations(
        self, *, owner_id: UUID, finding_id: UUID
    ) -> list[dict[str, object]]:
        with principal_transaction(self._engine, owner_id) as connection:
            finding = connection.execute(
                sa.select(Finding.id).where(
                    Finding.id == finding_id, Finding.owner_id == owner_id
                )
            ).scalar_one_or_none()
            if finding is None:
                _raise_access(connection, "finding", finding_id)
            rows = (
                connection.execute(
                    sa.select(Remediation.__table__)
                    .where(
                        Remediation.owner_id == owner_id,
                        Remediation.finding_id == finding_id,
                    )
                    .order_by(Remediation.created_at.desc(), Remediation.id.desc())
                )
                .mappings()
                .all()
            )
        return [_remediation_response(row) for row in rows]

    def get_remediation(
        self, *, owner_id: UUID, remediation_id: UUID
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            row = self._owned_remediation(connection, owner_id, remediation_id)
        return _remediation_response(row)

    def set_remediation_status(
        self, *, owner_id: UUID, remediation_id: UUID, status: RemediationStatus
    ) -> dict[str, object]:
        if status not in {RemediationStatus.APPROVED, RemediationStatus.REJECTED}:
            raise ResourceConflict("remediation_state_conflict")
        observed_version = self._read_mutation_version(
            owner_id=owner_id, remediation_id=remediation_id
        )
        with principal_transaction(self._engine, owner_id) as connection:
            remediation = self._owned_remediation(
                connection, owner_id, remediation_id, for_update=True
            )
            if remediation["mutation_version"] != observed_version:
                raise ResourceConflict("remediation_conflict")
            if remediation["status"] != RemediationStatus.PROPOSED:
                raise ResourceConflict("remediation_state_conflict")
            result = connection.execute(
                sa.update(Remediation)
                .where(
                    Remediation.id == remediation_id,
                    Remediation.owner_id == owner_id,
                    Remediation.mutation_version == observed_version,
                    Remediation.status == RemediationStatus.PROPOSED,
                )
                .values(
                    status=status,
                    approved_at=sa.func.current_timestamp()
                    if status is RemediationStatus.APPROVED
                    else None,
                    mutation_version=Remediation.mutation_version + 1,
                    updated_at=sa.func.current_timestamp(),
                )
            )
            if result.rowcount != 1:
                raise ResourceConflict("remediation_conflict")
            remediation = (
                connection.execute(
                    sa.select(Remediation.__table__).where(
                        Remediation.id == remediation_id,
                        Remediation.owner_id == owner_id,
                    )
                )
                .mappings()
                .one()
            )
        return _remediation_response(remediation)

    def _read_mutation_version(self, *, owner_id: UUID, remediation_id: UUID) -> int:
        with principal_transaction(self._engine, owner_id) as connection:
            version = connection.execute(
                sa.select(Remediation.mutation_version).where(
                    Remediation.id == remediation_id,
                    Remediation.owner_id == owner_id,
                )
            ).scalar_one_or_none()
            if version is None:
                _raise_access(connection, "remediation", remediation_id)
            return version

    def get_pull_request(
        self, *, owner_id: UUID, remediation_id: UUID
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            self._owned_remediation(connection, owner_id, remediation_id)
            row = cast(
                PullRequest | None,
                _orm_scalar_one_or_none(
                    connection,
                    sa.select(PullRequest).where(
                        PullRequest.owner_id == owner_id,
                        PullRequest.remediation_id == remediation_id,
                    ),
                ),
            )
            if row is None:
                raise ResourceNotFound()
            assert row is not None
        return _artifact_response(row)

    def get_local_backup(
        self, *, owner_id: UUID, remediation_id: UUID
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            self._owned_remediation(connection, owner_id, remediation_id)
            row = cast(
                LocalFileBackup | None,
                _orm_scalar_one_or_none(
                    connection,
                    sa.select(LocalFileBackup).where(
                        LocalFileBackup.owner_id == owner_id,
                        LocalFileBackup.remediation_id == remediation_id,
                    ),
                ),
            )
            if row is None:
                raise ResourceNotFound()
            assert row is not None
        return _artifact_response(row)

    def get_pull_request_by_id(
        self, *, owner_id: UUID, artifact_id: UUID
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            row = cast(
                PullRequest | None,
                _orm_scalar_one_or_none(
                    connection,
                    sa.select(PullRequest).where(
                        PullRequest.id == artifact_id, PullRequest.owner_id == owner_id
                    ),
                ),
            )
            if row is None:
                _raise_access(connection, "pull_request", artifact_id)
        return _artifact_response(row)

    def get_local_backup_by_id(
        self, *, owner_id: UUID, artifact_id: UUID
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            row = cast(
                LocalFileBackup | None,
                _orm_scalar_one_or_none(
                    connection,
                    sa.select(LocalFileBackup).where(
                        LocalFileBackup.id == artifact_id,
                        LocalFileBackup.owner_id == owner_id,
                    ),
                ),
            )
            if row is None:
                _raise_access(connection, "local_file_backup", artifact_id)
        return _artifact_response(row)

    @staticmethod
    def _owned_remediation(
        connection: sa.Connection,
        owner_id: UUID,
        remediation_id: UUID,
        *,
        for_update: bool = False,
    ) -> sa.RowMapping:
        query = sa.select(Remediation.__table__).where(
            Remediation.id == remediation_id, Remediation.owner_id == owner_id
        )
        if for_update:
            query = query.with_for_update()
        row = connection.execute(query).mappings().one_or_none()
        if row is None:
            _raise_access(connection, "remediation", remediation_id)
        return row


def _remediation_response(row: sa.RowMapping) -> dict[str, object]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "finding_id": row["finding_id"],
        "proposed_diff": row["proposed_diff"],
        "status": row["status"],
        "approved_at": row["approved_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _artifact_response(row: PullRequest | LocalFileBackup) -> dict[str, object]:
    if isinstance(row, PullRequest):
        return {
            "id": row.id,
            "remediation_id": row.remediation_id,
            "repository_url": row.repository_url,
            "pull_request_number": row.pull_request_number,
            "pull_request_url": row.pull_request_url,
            "branch_name": row.branch_name,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    return {
        "id": row.id,
        "remediation_id": row.remediation_id,
        "file_path": row.file_path,
        "backup_path": row.backup_path,
        "source_hash": _hash_text(row.source_hash),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
