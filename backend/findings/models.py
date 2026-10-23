"""Finding database models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import ReviewCategory, native_enum


class FindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="findings_owner_id_id_key"),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_run_id", "agent_id"],
            [
                "public.review_run_agents.owner_id",
                "public.review_run_agents.review_run_id",
                "public.review_run_agents.agent_id",
            ],
            name="findings_owner_run_agent_fkey",
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
    review_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    category: Mapped[ReviewCategory] = mapped_column(
        native_enum(ReviewCategory, "review_category", "public"), nullable=False
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        native_enum(FindingSeverity, "finding_severity", "public"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    explanation: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    evidence: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    source_location: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    recommendation: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[FindingStatus] = mapped_column(
        native_enum(FindingStatus, "finding_status", "public"),
        nullable=False,
        server_default=sa.text("'open'::public.finding_status"),
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


sa.Index("findings_owner_created_idx", Finding.owner_id, Finding.created_at.desc())


__all__ = ["Finding", "FindingSeverity", "FindingStatus"]
