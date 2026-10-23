"""Agent database models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import ReviewCategory, native_enum


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="agents_owner_id_id_key"),
        sa.ForeignKeyConstraint(
            ["owner_id", "credential_id"],
            ["private.credentials.owner_id", "private.credentials.id"],
            name="agents_owner_credential_fkey",
            ondelete="RESTRICT",
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
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    personality: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    review_category: Mapped[ReviewCategory] = mapped_column(
        native_enum(ReviewCategory, "review_category", "public"), nullable=False
    )
    model_provider: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    model_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    credential_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    skills: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    fallback_order: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
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
    disabled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


sa.Index("agents_owner_created_idx", Agent.owner_id, Agent.created_at.desc())
sa.Index("agents_owner_credential_idx", Agent.owner_id, Agent.credential_id)


__all__ = ["Agent"]
