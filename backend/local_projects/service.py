"""Persistence for opaque desktop-local project handles."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from auth.uuids import uuid7
from db.rls import principal_transaction
from local_projects.models import LocalProjectHandle


class LocalProjectHandleService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ensure(self, *, owner_id: UUID, client_project_id: UUID) -> dict[str, object]:
        with principal_transaction(self._engine, owner_id) as connection:
            handle = (
                connection.execute(
                    sa.select(LocalProjectHandle).where(
                        LocalProjectHandle.owner_id == owner_id,
                        LocalProjectHandle.client_project_id == client_project_id,
                    )
                )
                .scalars()
                .one_or_none()
            )
            if handle is None:
                handle_id = uuid7()
                connection.execute(
                    sa.insert(LocalProjectHandle).values(
                        id=handle_id,
                        owner_id=owner_id,
                        client_project_id=client_project_id,
                    )
                )
                handle = (
                    connection.execute(
                        sa.select(LocalProjectHandle).where(
                            LocalProjectHandle.id == handle_id,
                            LocalProjectHandle.owner_id == owner_id,
                        )
                    )
                    .scalars()
                    .one()
                )
        return {"id": handle.id, "client_project_id": handle.client_project_id}


__all__ = ["LocalProjectHandleService"]
