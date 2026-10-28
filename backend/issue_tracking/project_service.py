"""Owner-scoped issue-tracking configuration for Trace projects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from auth.errors import (
    AuthorizationDenied,
    IssueProviderValidationError,
    ResourceNotFound,
)
from db.rls import principal_transaction
from db.types import RepositorySource
from issue_tracking.catalog import LinearCatalogService
from issue_tracking.models import IssueProviderName
from projects.models import Project


class ProjectIssueTrackingService:
    """Read and update validated provider destinations for one owned project."""

    def __init__(
        self,
        *,
        engine: Engine,
        linear_catalog_service: LinearCatalogService,
    ) -> None:
        self._engine = engine
        self._linear_catalog_service = linear_catalog_service

    def get(self, *, owner_id: UUID, project_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            project = self._owned_project(
                connection,
                owner_id=owner_id,
                project_id=project_id,
            )
        return _issue_tracking_details(project)

    def update(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        connected_projects: list[dict[str, str]],
    ) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            project = self._owned_project(
                connection,
                owner_id=owner_id,
                project_id=project_id,
            )

        details = self._validated_details(
            owner_id=owner_id,
            project=project,
            connected_projects=connected_projects,
        )
        with principal_transaction(self._engine, owner_id) as connection:
            result = connection.execute(
                sa.update(Project)
                .where(Project.id == project_id, Project.owner_id == owner_id)
                .values(
                    issue_tracking_details=details,
                    updated_at=sa.func.current_timestamp(),
                )
            )
            if result.rowcount != 1:
                self._raise_project_access(connection, project_id)
        return details

    def _validated_details(
        self,
        *,
        owner_id: UUID,
        project: Mapping[str, Any],
        connected_projects: list[dict[str, str]],
    ) -> dict[str, object]:
        root = _source_destination(project)
        validated: list[dict[str, str]] = [root] if root is not None else []
        seen = {
            (entry["provider"], entry["owner"], entry["project"]) for entry in validated
        }
        configured_providers = {entry["provider"] for entry in validated}
        linear_projects_by_team: dict[str, set[str]] = {}

        for entry in connected_projects:
            provider = entry["provider"]
            owner = entry["owner"]
            destination_project = entry["project"]
            key = (provider, owner, destination_project)
            if provider == IssueProviderName.GITHUB.value:
                if key in seen:
                    continue
                raise IssueProviderValidationError()
            if provider != IssueProviderName.LINEAR.value:
                raise IssueProviderValidationError()
            if provider in configured_providers:
                raise IssueProviderValidationError()
            try:
                team_id = UUID(owner)
                project_id = UUID(destination_project)
            except ValueError as error:
                raise IssueProviderValidationError() from error
            available_projects = linear_projects_by_team.get(owner)
            if available_projects is None:
                available_projects = {
                    project.id
                    for project in self._linear_catalog_service.list_projects(
                        owner_id=owner_id,
                        team_id=team_id,
                    )
                }
                linear_projects_by_team[owner] = available_projects
            if str(project_id) not in available_projects:
                raise IssueProviderValidationError()
            validated.append(
                {
                    "provider": IssueProviderName.LINEAR.value,
                    "owner": str(team_id),
                    "project": str(project_id),
                }
            )
            seen.add(key)
            configured_providers.add(provider)
        return {"connected_projects": validated}

    @staticmethod
    def _owned_project(
        connection: sa.Connection,
        *,
        owner_id: UUID,
        project_id: UUID,
    ) -> Mapping[str, Any]:
        project = (
            connection.execute(
                sa.select(Project.__table__).where(
                    Project.id == project_id,
                    Project.owner_id == owner_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if project is not None:
            return cast(Mapping[str, Any], project)
        ProjectIssueTrackingService._raise_project_access(connection, project_id)

    @staticmethod
    def _raise_project_access(connection: sa.Connection, project_id: UUID) -> NoReturn:
        exists = connection.execute(
            sa.text("SELECT public.trace_project_exists(:project_id)"),
            {"project_id": project_id},
        ).scalar_one()
        if exists:
            raise AuthorizationDenied()
        raise ResourceNotFound()


def _source_destination(project: Mapping[str, Any]) -> dict[str, str] | None:
    source = project["source"]
    source_value = getattr(source, "value", source)
    if source_value != RepositorySource.GITHUB.value:
        return None
    owner = project["repository_owner"]
    repository = project["repository_name"]
    if (
        not isinstance(owner, str)
        or not owner
        or not isinstance(repository, str)
        or not repository
    ):
        raise IssueProviderValidationError()
    return {
        "provider": source_value,
        "owner": owner,
        "project": repository,
    }


def _issue_tracking_details(project: Mapping[str, Any]) -> dict[str, object]:
    details = project["issue_tracking_details"]
    if not isinstance(details, dict):
        raise IssueProviderValidationError()
    return details


__all__ = ["ProjectIssueTrackingService"]
