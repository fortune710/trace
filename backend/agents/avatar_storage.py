"""Avatar byte storage.

Everything that touches the ``private.agent_avatars`` table lives here so the
backing store can move to object storage without touching the routes.  Writes
run on a caller-supplied connection so the image row and the owning agent row
change in one owner-scoped transaction.  The public read has no principal and
goes through the ``public.read_agent_avatar`` SECURITY DEFINER function.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from agents.avatar_models import agent_avatars

AVATAR_URL_HASH_LENGTH = 12


@dataclass(frozen=True)
class StoredAvatar:
    content_type: str
    data: bytes
    sha256: str


def avatar_url(agent_id: UUID, digest: str) -> str:
    """Return the content-hashed public URL for an agent's avatar."""

    return f"/api/v1/agents/{agent_id}/avatar?v={digest[:AVATAR_URL_HASH_LENGTH]}"


def put(
    connection: Connection,
    *,
    owner_id: UUID,
    agent_id: UUID,
    content_type: str,
    data: bytes,
) -> str:
    """Insert or replace the avatar and return its SHA-256 hex digest."""

    digest = hashlib.sha256(data).hexdigest()
    values = {
        "content_type": content_type,
        "data": data,
        "sha256": digest,
        "byte_size": len(data),
    }
    connection.execute(
        pg_insert(agent_avatars)
        .values(owner_id=owner_id, agent_id=agent_id, **values)
        .on_conflict_do_update(
            index_elements=[agent_avatars.c.agent_id],
            set_={**values, "updated_at": sa.func.current_timestamp()},
        )
    )
    return digest


def delete(connection: Connection, *, owner_id: UUID, agent_id: UUID) -> None:
    connection.execute(
        sa.delete(agent_avatars).where(
            agent_avatars.c.owner_id == owner_id,
            agent_avatars.c.agent_id == agent_id,
        )
    )


def read_public(engine: Engine, agent_id: UUID) -> StoredAvatar | None:
    """Read an avatar without a principal through the SECURITY DEFINER function."""

    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                "SELECT content_type, data, sha256 "
                "FROM public.read_agent_avatar(:agent_id)"
            ),
            {"agent_id": agent_id},
        ).one_or_none()
    if row is None:
        return None
    return StoredAvatar(
        content_type=row.content_type, data=bytes(row.data), sha256=row.sha256
    )
