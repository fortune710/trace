"""Persistence for opaque desktop-local project handles."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from auth.uuids import uuid7
from db.rls import principal_transaction
from local_projects.models import LocalProjectHandle


class LocalProjectHandleService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ensure(self, *, owner_id: UUID, client_project_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            connection.execute(
                insert(LocalProjectHandle)
                .values(
                    id=uuid7(),
                    owner_id=owner_id,
                    client_project_id=client_project_id,
                )
                .on_conflict_do_nothing(
                    constraint="local_project_handles_owner_client_key"
                )
            )
            handle = (
                connection.execute(
                    sa.select(
                        LocalProjectHandle.id,
                        LocalProjectHandle.client_project_id,
                    ).where(
                        LocalProjectHandle.owner_id == owner_id,
                        LocalProjectHandle.client_project_id == client_project_id,
                    )
                )
                .mappings()
                .one()
            )
        return {
            "id": handle["id"],
            "client_project_id": handle["client_project_id"],
        }


__all__ = ["LocalProjectHandleService"]
