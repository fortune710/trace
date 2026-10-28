"""Opaque server handles for metadata that remains on the desktop."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class LocalProjectHandle(Base):
    """An owner-scoped reference with no name, filesystem path, or source data."""

    __tablename__ = "local_project_handles"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id",
            "client_project_id",
            name="local_project_handles_owner_client_key",
        ),
        sa.UniqueConstraint(
            "owner_id", "id", name="local_project_handles_owner_id_id_key"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(issue_tracking_details) = 'object' "
            "AND issue_tracking_details ? 'connected_projects' "
            "AND jsonb_typeof(issue_tracking_details -> 'connected_projects') = 'array'",
            name="local_project_handles_issue_tracking_details_shape_check",
        ),
        {"schema": "public"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    issue_tracking_details: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{\"connected_projects\":[]}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


sa.Index(
    "local_project_handles_owner_created_idx",
    LocalProjectHandle.owner_id,
    LocalProjectHandle.created_at.desc(),
)


__all__ = ["LocalProjectHandle"]
