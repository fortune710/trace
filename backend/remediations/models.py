"""Remediation database models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import native_enum


class RemediationStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class Remediation(Base):
    __tablename__ = "remediations"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="remediations_owner_id_id_key"),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["public.projects.owner_id", "public.projects.id"],
            name="remediations_owner_project_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "finding_id"],
            ["public.findings.owner_id", "public.findings.id"],
            name="remediations_owner_finding_fkey",
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
    finding_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    proposed_diff: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[RemediationStatus] = mapped_column(
        native_enum(RemediationStatus, "remediation_status", "public"),
        nullable=False,
        server_default=sa.text("'proposed'::public.remediation_status"),
    )
    approved_at: Mapped[datetime | None] = mapped_column(
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
    mutation_version: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )


sa.Index(
    "remediations_owner_created_idx",
    Remediation.owner_id,
    Remediation.created_at.desc(),
)


__all__ = ["Remediation", "RemediationStatus"]
