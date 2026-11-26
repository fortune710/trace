"""Persist and resolve per-agent skills.sh attachments."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from agents.models import Agent
from agents.skill_models import AgentSkill
from agents.skills.client import (
    SkillsShAuthError,
    SkillsShClient,
    SkillsShError,
    SkillsShNotFoundError,
    SkillsShRateLimitError,
    SkillsShUnavailableError,
)
from agents.skills.validation import (
    MAX_AGENT_SKILLS,
    SkillValidationError,
    is_skills_sh_skill,
    normalize_skill_id,
    skill_snapshot_dict,
)
from auth.errors import (
    AuthorizationDenied,
    RepositoryInvalidRequest,
    ResourceConflict,
    ResourceNotFound,
    ResourceUnavailable,
)
from auth.uuids import uuid7
from db.rls import principal_transaction


def _orm_scalars_all(connection: Connection, statement: Any) -> list[Any]:
    return list(connection.scalars(statement).all())


def _orm_scalar_one(connection: Connection, statement: Any) -> Any:
    return connection.scalars(statement).one()


def _raise_access(connection: Connection, resource_id: UUID) -> None:
    exists = connection.execute(
        sa.text("SELECT public.trace_agent_exists(:resource_id)"),
        {"resource_id": resource_id},
    ).scalar_one()
    if bool(exists):
        raise AuthorizationDenied()
    raise ResourceNotFound()


class AgentSkillService:
    def __init__(
        self,
        engine: Engine,
        *,
        client: SkillsShClient | None = None,
    ) -> None:
        self._engine = engine
        self._client = client or SkillsShClient()

    def list_catalog(
        self,
        *,
        view: str = "all-time",
        page: int = 0,
        per_page: int = 20,
        source: str | None = None,
    ) -> dict[str, Any]:
        return self._map_client_errors(
            lambda: self._client.list_skills(
                view=view, page=page, per_page=per_page, source=source
            )
        )

    def search_catalog(
        self,
        *,
        query: str,
        limit: int = 20,
        owner: str | None = None,
    ) -> dict[str, Any]:
        return self._map_client_errors(
            lambda: self._client.search_skills(query=query, limit=limit, owner=owner)
        )

    def curated_catalog(self) -> dict[str, Any]:
        return self._map_client_errors(self._client.curated_skills)

    def get_catalog_skill(self, skill_id: str) -> dict[str, Any]:
        return self._map_client_errors(lambda: self._client.get_skill(skill_id))

    def list_for_agent(
        self, *, owner_id: UUID, agent_id: UUID
    ) -> list[dict[str, object]]:
        with principal_transaction(self._engine, owner_id) as connection:
            self._owned_agent(connection, owner_id, agent_id)
            rows = cast(
                list[AgentSkill],
                _orm_scalars_all(
                    connection,
                    sa.select(AgentSkill)
                    .where(
                        AgentSkill.owner_id == owner_id,
                        AgentSkill.agent_id == agent_id,
                    )
                    .order_by(AgentSkill.sort_order.asc(), AgentSkill.created_at.asc()),
                ),
            )
        return [self._row_response(row) for row in rows]

    def attach(
        self, *, owner_id: UUID, agent_id: UUID, skill_id: str
    ) -> dict[str, object]:
        try:
            normalized = normalize_skill_id(skill_id)
        except SkillValidationError as error:
            raise RepositoryInvalidRequest() from error

        detail = self._map_client_errors(lambda: self._client.get_skill(normalized))
        snapshot = skill_snapshot_dict(
            skill_id=detail["id"],
            slug=detail["slug"],
            name=detail["name"],
            source=detail["source"],
            source_type=detail["source_type"],
            install_url=detail.get("install_url"),
            url=detail["url"],
            content_hash=detail.get("hash"),
            skill_md=detail["skill_md"],
            files=[
                {"path": file["path"], "contents": file["contents"]}
                for file in detail.get("files", [])
                if isinstance(file, dict)
                and isinstance(file.get("path"), str)
                and isinstance(file.get("contents"), str)
            ],
        )

        try:
            with principal_transaction(self._engine, owner_id) as connection:
                agent = self._owned_agent(connection, owner_id, agent_id)
                if agent.disabled_at is not None:
                    raise ResourceConflict("agent_disabled")
                existing = cast(
                    list[AgentSkill],
                    _orm_scalars_all(
                        connection,
                        sa.select(AgentSkill).where(
                            AgentSkill.owner_id == owner_id,
                            AgentSkill.agent_id == agent_id,
                        ),
                    ),
                )
                for row in existing:
                    if row.skill_id == normalized:
                        connection.execute(
                            sa.update(AgentSkill)
                            .where(
                                AgentSkill.owner_id == owner_id,
                                AgentSkill.id == row.id,
                            )
                            .values(
                                slug=detail["slug"],
                                name=detail["name"],
                                source=detail["source"],
                                source_type=detail["source_type"],
                                install_url=detail.get("install_url"),
                                url=detail["url"],
                                content_hash=detail.get("hash"),
                                skill_md=detail["skill_md"],
                                files=snapshot.get("files", []),
                                updated_at=sa.func.current_timestamp(),
                            )
                        )
                        self._sync_agent_skills_json(
                            connection, owner_id=owner_id, agent_id=agent_id
                        )
                        refreshed = _orm_scalar_one(
                            connection,
                            sa.select(AgentSkill).where(
                                AgentSkill.owner_id == owner_id,
                                AgentSkill.id == row.id,
                            ),
                        )
                        return self._row_response(refreshed)

                if len(existing) >= MAX_AGENT_SKILLS:
                    raise ResourceConflict("agent_skills_limit")

                skill_row_id = uuid7()
                connection.execute(
                    sa.insert(AgentSkill).values(
                        id=skill_row_id,
                        owner_id=owner_id,
                        agent_id=agent_id,
                        skill_id=detail["id"],
                        slug=detail["slug"],
                        name=detail["name"],
                        source=detail["source"],
                        source_type=detail["source_type"],
                        install_url=detail.get("install_url"),
                        url=detail["url"],
                        content_hash=detail.get("hash"),
                        skill_md=detail["skill_md"],
                        files=snapshot.get("files", []),
                        sort_order=len(existing),
                    )
                )
                self._sync_agent_skills_json(
                    connection, owner_id=owner_id, agent_id=agent_id
                )
                created = _orm_scalar_one(
                    connection,
                    sa.select(AgentSkill).where(
                        AgentSkill.owner_id == owner_id,
                        AgentSkill.id == skill_row_id,
                    ),
                )
        except sa.exc.IntegrityError as error:
            raise ResourceConflict("agent_skill_conflict") from error
        return self._row_response(created)

    def detach(self, *, owner_id: UUID, agent_id: UUID, skill_id: str) -> None:
        try:
            normalized = normalize_skill_id(skill_id)
        except SkillValidationError as error:
            raise RepositoryInvalidRequest() from error

        with principal_transaction(self._engine, owner_id) as connection:
            self._owned_agent(connection, owner_id, agent_id)
            result = connection.execute(
                sa.delete(AgentSkill).where(
                    AgentSkill.owner_id == owner_id,
                    AgentSkill.agent_id == agent_id,
                    AgentSkill.skill_id == normalized,
                )
            )
            if result.rowcount == 0:
                raise ResourceNotFound()
            self._sync_agent_skills_json(
                connection, owner_id=owner_id, agent_id=agent_id
            )

    def replace_skills_mirror(
        self,
        connection: Connection,
        *,
        owner_id: UUID,
        agent_id: UUID,
        skills: list[object],
    ) -> list[object]:
        """Validate a PATCH skills payload and refresh agent_skills + JSON mirror.

        Client-supplied skill markdown is rejected. skills.sh entries must be
        referenced by id and are resolved server-side.
        """

        if len(skills) > MAX_AGENT_SKILLS:
            raise RepositoryInvalidRequest()

        legacy: list[object] = []
        resolved_ids: list[str] = []
        for skill in skills:
            if isinstance(skill, str):
                text = skill.strip()
                if not text or len(text) > 200:
                    raise RepositoryInvalidRequest()
                legacy.append(text)
                continue
            if not isinstance(skill, dict):
                raise RepositoryInvalidRequest()
            if skill.get("skill_md") is not None or skill.get("files") is not None:
                raise RepositoryInvalidRequest()
            if is_skills_sh_skill(skill) or "id" in skill:
                skill_id = skill.get("id")
                if not isinstance(skill_id, str):
                    raise RepositoryInvalidRequest()
                try:
                    resolved_ids.append(normalize_skill_id(skill_id))
                except SkillValidationError as error:
                    raise RepositoryInvalidRequest() from error
                continue
            raise RepositoryInvalidRequest()

        # Deduplicate while preserving order.
        unique_ids: list[str] = []
        for skill_id in resolved_ids:
            if skill_id not in unique_ids:
                unique_ids.append(skill_id)

        connection.execute(
            sa.delete(AgentSkill).where(
                AgentSkill.owner_id == owner_id,
                AgentSkill.agent_id == agent_id,
            )
        )

        snapshots: list[object] = list(legacy)
        for index, skill_id in enumerate(unique_ids):
            detail = self._map_client_errors(
                lambda sid=skill_id: self._client.get_skill(sid)
            )
            snapshot = skill_snapshot_dict(
                skill_id=detail["id"],
                slug=detail["slug"],
                name=detail["name"],
                source=detail["source"],
                source_type=detail["source_type"],
                install_url=detail.get("install_url"),
                url=detail["url"],
                content_hash=detail.get("hash"),
                skill_md=detail["skill_md"],
                files=[
                    {"path": file["path"], "contents": file["contents"]}
                    for file in detail.get("files", [])
                    if isinstance(file, dict)
                    and isinstance(file.get("path"), str)
                    and isinstance(file.get("contents"), str)
                ],
            )
            connection.execute(
                sa.insert(AgentSkill).values(
                    id=uuid7(),
                    owner_id=owner_id,
                    agent_id=agent_id,
                    skill_id=detail["id"],
                    slug=detail["slug"],
                    name=detail["name"],
                    source=detail["source"],
                    source_type=detail["source_type"],
                    install_url=detail.get("install_url"),
                    url=detail["url"],
                    content_hash=detail.get("hash"),
                    skill_md=detail["skill_md"],
                    files=snapshot.get("files", []),
                    sort_order=index,
                )
            )
            snapshots.append(snapshot)

        connection.execute(
            sa.update(Agent)
            .where(Agent.id == agent_id, Agent.owner_id == owner_id)
            .values(
                skills=snapshots,
                configuration_version=Agent.configuration_version + 1,
                updated_at=sa.func.current_timestamp(),
            )
        )
        return snapshots

    def _sync_agent_skills_json(
        self,
        connection: Connection,
        *,
        owner_id: UUID,
        agent_id: UUID,
    ) -> None:
        agent = _orm_scalar_one(
            connection,
            sa.select(Agent).where(Agent.id == agent_id, Agent.owner_id == owner_id),
        )
        legacy = [
            skill
            for skill in agent.skills
            if isinstance(skill, str)
            or not (isinstance(skill, dict) and skill.get("provider") == "skills.sh")
        ]
        rows = cast(
            list[AgentSkill],
            _orm_scalars_all(
                connection,
                sa.select(AgentSkill)
                .where(
                    AgentSkill.owner_id == owner_id,
                    AgentSkill.agent_id == agent_id,
                )
                .order_by(AgentSkill.sort_order.asc(), AgentSkill.created_at.asc()),
            ),
        )
        snapshots: list[object] = list(legacy)
        for row in rows:
            snapshots.append(
                skill_snapshot_dict(
                    skill_id=row.skill_id,
                    slug=row.slug,
                    name=row.name,
                    source=row.source,
                    source_type=row.source_type,
                    install_url=row.install_url,
                    url=row.url,
                    content_hash=row.content_hash,
                    skill_md=row.skill_md,
                    files=[
                        {"path": str(file["path"]), "contents": str(file["contents"])}
                        for file in row.files
                        if isinstance(file, dict)
                        and "path" in file
                        and "contents" in file
                    ],
                )
            )
        connection.execute(
            sa.update(Agent)
            .where(Agent.id == agent_id, Agent.owner_id == owner_id)
            .values(
                skills=snapshots,
                configuration_version=Agent.configuration_version + 1,
                updated_at=sa.func.current_timestamp(),
            )
        )

    def _owned_agent(
        self, connection: Connection, owner_id: UUID, agent_id: UUID
    ) -> Agent:
        agent = connection.scalars(
            sa.select(Agent).where(Agent.id == agent_id, Agent.owner_id == owner_id)
        ).one_or_none()
        if agent is None:
            _raise_access(connection, agent_id)
        return cast(Agent, agent)

    def _row_response(self, row: AgentSkill) -> dict[str, object]:
        return {
            "id": row.id,
            "agent_id": row.agent_id,
            "skill_id": row.skill_id,
            "slug": row.slug,
            "name": row.name,
            "source": row.source,
            "source_type": row.source_type,
            "install_url": row.install_url,
            "url": row.url,
            "content_hash": row.content_hash,
            "sort_order": row.sort_order,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _map_client_errors(self, operation):
        try:
            return operation()
        except SkillValidationError as error:
            raise RepositoryInvalidRequest() from error
        except SkillsShNotFoundError as error:
            raise ResourceNotFound() from error
        except SkillsShRateLimitError as error:
            raise ResourceUnavailable() from error
        except SkillsShAuthError as error:
            raise ResourceUnavailable() from error
        except SkillsShUnavailableError as error:
            raise ResourceUnavailable() from error
        except SkillsShError as error:
            if error.status_code == 400:
                raise RepositoryInvalidRequest() from error
            raise ResourceUnavailable() from error
