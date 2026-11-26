"""SQLAlchemy model for per-agent skills.sh attachments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class AgentSkill(Base):
    __tablename__ = "agent_skills"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="agent_skills_owner_id_id_key"),
        sa.UniqueConstraint(
            "owner_id",
            "agent_id",
            "skill_id",
            name="agent_skills_owner_agent_skill_unique",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "agent_id"],
            ["public.agents.owner_id", "public.agents.id"],
            name="agent_skills_owner_agent_fkey",
            ondelete="CASCADE",
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
    agent_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    skill_id: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    slug: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    install_url: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    url: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    skill_md: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    files: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    sort_order: Mapped[int] = mapped_column(
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


sa.Index(
    "agent_skills_owner_agent_sort_idx",
    AgentSkill.owner_id,
    AgentSkill.agent_id,
    AgentSkill.sort_order,
    AgentSkill.created_at,
)


__all__ = ["AgentSkill"]
