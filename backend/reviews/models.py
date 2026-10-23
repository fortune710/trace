"""Review execution and assignment models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import ReviewCategory, native_enum


class ReviewStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewRunAgentStatus(str, Enum):
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewRun(Base):
    __tablename__ = "review_runs"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="review_runs_owner_id_id_key"),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["public.projects.owner_id", "public.projects.id"],
            name="review_runs_owner_project_fkey",
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
    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    source_revision: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        native_enum(ReviewStatus, "review_status", "public"),
        nullable=False,
        server_default=sa.text("'queued'::public.review_status"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
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
    retry_version: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )


class ReviewRunAgent(Base):
    __tablename__ = "review_run_agents"
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "review_run_id", "agent_id", name="review_run_agents_pkey"
        ),
        sa.UniqueConstraint(
            "owner_id",
            "review_run_id",
            "agent_id",
            name="review_run_agents_owner_tuple_key",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_run_id"],
            ["public.review_runs.owner_id", "public.review_runs.id"],
            name="review_run_agents_owner_run_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "agent_id"],
            ["public.agents.owner_id", "public.agents.id"],
            name="review_run_agents_owner_agent_fkey",
            ondelete="CASCADE",
        ),
        {"schema": "public"},
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    status: Mapped[ReviewRunAgentStatus] = mapped_column(
        native_enum(ReviewRunAgentStatus, "review_run_agent_status", "public"),
        nullable=False,
        server_default=sa.text("'assigned'::public.review_run_agent_status"),
    )
    error_reason: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class ReviewRunCategory(Base):
    __tablename__ = "review_run_categories"
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "review_run_id", "category", name="review_run_categories_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_run_id"],
            ["public.review_runs.owner_id", "public.review_runs.id"],
            name="review_run_categories_owner_run_fkey",
            ondelete="CASCADE",
        ),
        {"schema": "public"},
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    category: Mapped[ReviewCategory] = mapped_column(
        native_enum(ReviewCategory, "review_category", "public"), nullable=False
    )


sa.Index(
    "review_runs_owner_created_idx", ReviewRun.owner_id, ReviewRun.created_at.desc()
)
sa.Index(
    "review_run_agents_owner_run_idx",
    ReviewRunAgent.owner_id,
    ReviewRunAgent.review_run_id,
)
sa.Index(
    "review_run_categories_owner_run_idx",
    ReviewRunCategory.owner_id,
    ReviewRunCategory.review_run_id,
)


__all__ = [
    "ReviewCategory",
    "ReviewRun",
    "ReviewRunAgent",
    "ReviewRunAgentStatus",
    "ReviewRunCategory",
    "ReviewStatus",
]
