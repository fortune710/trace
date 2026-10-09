from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
from typing import Any, NoReturn, Protocol, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from agents.models import Agent
from artifacts.models import LocalFileBackup, PullRequest
from auth.errors import AuthorizationDenied, ResourceConflict, ResourceNotFound
from auth.uuids import uuid7
from credentials.models import Credential
from db.rls import principal_transaction
from db.types import RepositorySource
from external_repositories.models import ExternalRepository
from findings.models import Finding, FindingStatus
from projects.models import Project, ProjectCategory
from remediations.models import Remediation, RemediationStatus
from reviews.models import (
    ReviewRun,
    ReviewRunAgent,
    ReviewRunAgentStatus,
    ReviewRunCategory,
    ReviewStatus,
)


class ReviewDispatcher(Protocol):
    def dispatch(self, *, review_id: UUID, owner_id: UUID) -> None: ...


class NoopReviewDispatcher:
    """API-phase dispatcher; execution workers can replace this adapter."""

    def dispatch(self, *, review_id: UUID, owner_id: UUID) -> None:
        return None


class ReviewDispatchUnavailable(RuntimeError):
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
        "skills": agent.skills,
        "fallback_order": agent.fallback_order,
        "credential_id": agent.credential_id,
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
                credential_id = values.get("credential_id", agent.credential_id)
                self._validate_credential(
                    connection, owner_id, credential_id, model_provider
                )
                connection.execute(
                    sa.update(Agent)
                    .where(Agent.id == agent_id, Agent.owner_id == owner_id)
                    .values(**values, updated_at=sa.func.current_timestamp())
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
        if credential.provider.value != model_provider:
            raise ResourceConflict("credential_provider_mismatch")


def _review_response(
    connection: sa.Connection, owner_id: UUID, review_id: UUID
) -> dict[str, object]:
    review = (
        connection.execute(
            sa.select(ReviewRun.__table__).where(
                ReviewRun.id == review_id, ReviewRun.owner_id == owner_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if review is None:
        _raise_access(connection, "review_run", review_id)
    categories = (
        connection.execute(
            sa.select(ReviewRunCategory.category)
            .where(
                ReviewRunCategory.owner_id == owner_id,
                ReviewRunCategory.review_run_id == review_id,
            )
            .order_by(ReviewRunCategory.category)
        )
        .scalars()
        .all()
    )
    assigned = (
        connection.execute(
            sa.select(
                ReviewRunAgent.status.label("assignment_status"),
                ReviewRunAgent.assigned_at,
                ReviewRunAgent.started_at.label("assignment_started_at"),
                ReviewRunAgent.completed_at.label("assignment_completed_at"),
                Agent.id.label("agent_id"),
                Agent.name.label("agent_name"),
                Agent.review_category.label("agent_review_category"),
            )
            .join(
                Agent,
                sa.and_(
                    Agent.id == ReviewRunAgent.agent_id,
                    Agent.owner_id == ReviewRunAgent.owner_id,
                ),
            )
            .where(
                ReviewRunAgent.owner_id == owner_id,
                ReviewRunAgent.review_run_id == review_id,
            )
            .order_by(Agent.fallback_order, Agent.id)
        )
        .mappings()
        .all()
    )
    return {
        "id": review["id"],
        "project_id": review["project_id"],
        "source_revision": review["source_revision"],
        "selected_categories": categories,
        "status": review["status"],
        "started_at": review["started_at"],
        "completed_at": review["completed_at"],
        "created_at": review["created_at"],
        "updated_at": review["updated_at"],
        "agents": [
            {
                "agent_id": assignment["agent_id"],
                "name": assignment["agent_name"],
                "review_category": assignment["agent_review_category"],
                "status": assignment["assignment_status"],
                "assigned_at": assignment["assigned_at"],
                "started_at": assignment["assignment_started_at"],
                "completed_at": assignment["assignment_completed_at"],
            }
            for assignment in assigned
        ],
    }


class ReviewService:
    def __init__(
        self, engine: Engine, dispatcher: ReviewDispatcher | None = None
    ) -> None:
        self._engine = engine
        self._dispatcher = dispatcher or NoopReviewDispatcher()

    def create(self, *, owner_id: UUID, values: dict[str, Any]) -> dict[str, object]:
        categories = list(dict.fromkeys(values["selected_categories"]))
        if len(categories) != len(values["selected_categories"]):
            raise ValueError("Review categories must be unique")
        agent_ids = values.get("agent_ids")
        try:
            with principal_transaction(self._engine, owner_id) as connection:
                project = cast(
                    Project | None,
                    _orm_scalar_one_or_none(
                        connection,
                        sa.select(Project).where(
                            Project.id == values["project_id"],
                            Project.owner_id == owner_id,
                            Project.archived_at.is_(None),
                        ),
                    ),
                )
                if project is None:
                    _raise_access(connection, "project", values["project_id"])
                if agent_ids is None:
                    agents = cast(
                        list[Agent],
                        _orm_scalars_all(
                            connection,
                            sa.select(Agent)
                            .where(
                                Agent.owner_id == owner_id,
                                Agent.disabled_at.is_(None),
                                Agent.review_category.in_(categories),
                            )
                            .order_by(Agent.fallback_order, Agent.id),
                        ),
                    )
                else:
                    if len(set(agent_ids)) != len(agent_ids):
                        raise ValueError("Review agents must be unique")
                    agents = cast(
                        list[Agent],
                        _orm_scalars_all(
                            connection,
                            sa.select(Agent).where(
                                Agent.owner_id == owner_id,
                                Agent.id.in_(agent_ids),
                                Agent.disabled_at.is_(None),
                            ),
                        ),
                    )
                    if len(agents) != len(agent_ids):
                        missing = next(
                            agent_id
                            for agent_id in agent_ids
                            if agent_id not in {agent.id for agent in agents}
                        )
                        _raise_access(connection, "agent", missing)
                    if any(agent.review_category not in categories for agent in agents):
                        raise ResourceConflict("agent_category_mismatch")
                if not agents:
                    raise ResourceConflict("no_matching_agents")
                review_id = uuid7()
                connection.execute(
                    sa.insert(ReviewRun).values(
                        id=review_id,
                        owner_id=owner_id,
                        project_id=project.id,
                        source_revision=values["source_revision"],
                        status=ReviewStatus.QUEUED,
                    )
                )
                connection.execute(
                    sa.insert(ReviewRunCategory),
                    [
                        {
                            "owner_id": owner_id,
                            "review_run_id": review_id,
                            "category": category,
                        }
                        for category in categories
                    ],
                )
                connection.execute(
                    sa.insert(ReviewRunAgent),
                    [
                        {
                            "owner_id": owner_id,
                            "review_run_id": review_id,
                            "agent_id": agent.id,
                            "status": ReviewRunAgentStatus.ASSIGNED,
                        }
                        for agent in agents
                    ],
                )
        except sa.exc.IntegrityError as error:
            raise ResourceConflict("review_conflict") from error
        try:
            self._dispatcher.dispatch(review_id=review_id, owner_id=owner_id)
        except Exception as error:
            raise ReviewDispatchUnavailable from error
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
            query = sa.select(ReviewRun).where(ReviewRun.owner_id == owner_id)
            if project_id is not None:
                query = query.where(ReviewRun.project_id == project_id)
            if status is not None:
                query = query.where(ReviewRun.status == status)
            reviews = cast(
                list[ReviewRun],
                _orm_scalars_all(
                    connection,
                    query.order_by(ReviewRun.created_at.desc(), ReviewRun.id.desc())
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
            review = self._owned_review(connection, owner_id, review_id)
            if review["status"] not in {ReviewStatus.QUEUED, ReviewStatus.RUNNING}:
                raise ResourceConflict("review_state_conflict")
            connection.execute(
                sa.update(ReviewRun)
                .where(ReviewRun.id == review_id, ReviewRun.owner_id == owner_id)
                .values(
                    status=ReviewStatus.CANCELLED,
                    updated_at=sa.func.current_timestamp(),
                )
            )
            return _review_response(connection, owner_id, review_id)

    def retry(self, *, owner_id: UUID, review_id: UUID) -> dict[str, object]:
        observed_version = self._read_retry_version(
            owner_id=owner_id, review_id=review_id
        )

        with principal_transaction(self._engine, owner_id) as connection:
            original = self._owned_review(
                connection, owner_id, review_id, for_update=True
            )
            if original["retry_version"] != observed_version:
                raise ResourceConflict("review_retry_conflict")
            if original["status"] not in {
                ReviewStatus.FAILED,
                ReviewStatus.CANCELLED,
            }:
                raise ResourceConflict("review_state_conflict")
            categories = (
                connection.execute(
                    sa.select(ReviewRunCategory.category).where(
                        ReviewRunCategory.owner_id == owner_id,
                        ReviewRunCategory.review_run_id == review_id,
                    )
                )
                .scalars()
                .all()
            )
            agents = (
                connection.execute(
                    sa.select(Agent.__table__)
                    .join(
                        ReviewRunAgent,
                        sa.and_(
                            ReviewRunAgent.agent_id == Agent.id,
                            ReviewRunAgent.owner_id == Agent.owner_id,
                        ),
                    )
                    .where(
                        ReviewRunAgent.owner_id == owner_id,
                        ReviewRunAgent.review_run_id == review_id,
                        Agent.disabled_at.is_(None),
                    )
                )
                .mappings()
                .all()
            )
            if not agents:
                raise ResourceConflict("no_matching_agents")
            new_id = uuid7()
            connection.execute(
                sa.insert(ReviewRun).values(
                    id=new_id,
                    owner_id=owner_id,
                    project_id=original["project_id"],
                    source_revision=original["source_revision"],
                    status=ReviewStatus.QUEUED,
                )
            )
            connection.execute(
                sa.insert(ReviewRunCategory),
                [
                    {
                        "owner_id": owner_id,
                        "review_run_id": new_id,
                        "category": category,
                    }
                    for category in categories
                ],
            )
            connection.execute(
                sa.insert(ReviewRunAgent),
                [
                    {
                        "owner_id": owner_id,
                        "review_run_id": new_id,
                        "agent_id": agent["id"],
                        "status": ReviewRunAgentStatus.ASSIGNED,
                    }
                    for agent in agents
                ],
            )
            result = connection.execute(
                sa.update(ReviewRun)
                .where(
                    ReviewRun.id == review_id,
                    ReviewRun.owner_id == owner_id,
                    ReviewRun.retry_version == observed_version,
                )
                .values(
                    retry_version=ReviewRun.retry_version + 1,
                    updated_at=sa.func.current_timestamp(),
                )
            )
            if result.rowcount != 1:
                raise ResourceConflict("review_retry_conflict")
        try:
            self._dispatcher.dispatch(review_id=new_id, owner_id=owner_id)
        except Exception as error:
            raise ReviewDispatchUnavailable from error
        return self.get(owner_id=owner_id, review_id=new_id)

    def _read_retry_version(self, *, owner_id: UUID, review_id: UUID) -> int:
        with principal_transaction(self._engine, owner_id) as connection:
            observed_version = connection.execute(
                sa.select(ReviewRun.retry_version).where(
                    ReviewRun.id == review_id,
                    ReviewRun.owner_id == owner_id,
                )
            ).scalar_one_or_none()
            if observed_version is None:
                _raise_access(connection, "review_run", review_id)
            return observed_version

    @staticmethod
    def _owned_review(
        connection: sa.Connection,
        owner_id: UUID,
        review_id: UUID,
        *,
        for_update: bool = False,
    ) -> sa.RowMapping:
        query = sa.select(ReviewRun.__table__).where(
            ReviewRun.id == review_id, ReviewRun.owner_id == owner_id
        )
        if for_update:
            query = query.with_for_update()
        review = connection.execute(query).mappings().one_or_none()
        if review is None:
            _raise_access(connection, "review_run", review_id)
        return review


class FindingService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
                sa.select(ReviewRun.id).where(
                    ReviewRun.id == review_id, ReviewRun.owner_id == owner_id
                )
            ).scalar_one_or_none()
            if review is None:
                _raise_access(connection, "review_run", review_id)
            query = sa.select(Finding).where(
                Finding.owner_id == owner_id, Finding.review_run_id == review_id
            )
            for field in ("category", "severity", "status", "agent_id"):
                if filters.get(field) is not None:
                    query = query.where(getattr(Finding, field) == filters[field])
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
        return [_finding_response(finding) for finding in selected], next_offset

    def get(self, *, owner_id: UUID, finding_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            finding = self._owned_finding(connection, owner_id, finding_id)
        return _finding_response(finding)

    def update_status(
        self, *, owner_id: UUID, finding_id: UUID, status: FindingStatus
    ) -> dict[str, object]:
        allowed = {
            FindingStatus.OPEN: {
                FindingStatus.ACCEPTED,
                FindingStatus.RESOLVED,
                FindingStatus.DISMISSED,
            },
            FindingStatus.ACCEPTED: {
                FindingStatus.OPEN,
                FindingStatus.RESOLVED,
                FindingStatus.DISMISSED,
            },
            FindingStatus.RESOLVED: {FindingStatus.OPEN},
            FindingStatus.DISMISSED: {FindingStatus.OPEN},
        }
        with principal_transaction(self._engine, owner_id) as connection:
            finding = self._owned_finding(connection, owner_id, finding_id)
            if finding.status != status and status not in allowed[finding.status]:
                raise ResourceConflict("finding_state_conflict")
            connection.execute(
                sa.update(Finding)
                .where(Finding.id == finding_id, Finding.owner_id == owner_id)
                .values(status=status, updated_at=sa.func.current_timestamp())
            )
            finding = self._owned_finding(connection, owner_id, finding_id)
        return _finding_response(finding)

    @staticmethod
    def _owned_finding(
        connection: sa.Connection, owner_id: UUID, finding_id: UUID
    ) -> Finding:
        finding = cast(
            Finding | None,
            _orm_scalar_one_or_none(
                connection,
                sa.select(Finding).where(
                    Finding.id == finding_id, Finding.owner_id == owner_id
                ),
            ),
        )
        if finding is None:
            _raise_access(connection, "finding", finding_id)
        return finding


def _finding_response(finding: Finding) -> dict[str, object]:
    return {
        "id": finding.id,
        "review_run_id": finding.review_run_id,
        "agent_id": finding.agent_id,
        "category": finding.category,
        "severity": finding.severity,
        "title": finding.title,
        "explanation": finding.explanation,
        "evidence": finding.evidence,
        "source_location": finding.source_location,
        "recommendation": finding.recommendation,
        "status": finding.status,
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
                sa.select(Finding.id, ReviewRun.project_id)
                .join(
                    ReviewRun,
                    sa.and_(
                        ReviewRun.id == Finding.review_run_id,
                        ReviewRun.owner_id == Finding.owner_id,
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
