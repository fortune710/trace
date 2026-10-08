"""Audit delivery outbox database model."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import native_enum


class AuditDeliveryStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


class AuditDeliveryJob(Base):
    """Transient delivery metadata; immudb remains the canonical audit log."""

    __tablename__ = "audit_delivery_jobs"
    __table_args__ = {"schema": "private"}  # noqa: RUF012

    event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("public.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    canonical_json: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    event_hash: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[AuditDeliveryStatus] = mapped_column(
        native_enum(AuditDeliveryStatus, "audit_delivery_status", "private"),
        nullable=False,
        server_default=sa.text("'pending'::private.audit_delivery_status"),
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    transaction_id: Mapped[int | None] = mapped_column(sa.BigInteger(), nullable=True)
    transaction_hash: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
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
    "private_audit_delivery_jobs_pending_idx",
    AuditDeliveryJob.status,
    AuditDeliveryJob.next_attempt_at,
    AuditDeliveryJob.created_at,
    postgresql_where=AuditDeliveryJob.status == AuditDeliveryStatus.PENDING,
)


__all__ = ["AuditDeliveryJob", "AuditDeliveryStatus"]
