"""Durable, owner-scoped in-app notifications."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import native_enum


class NotificationCategory(str, Enum):
    INFO = "info"
    SECURITY = "security"
    WARNING = "warning"


class NotificationEventType(str, Enum):
    REVIEW_QUEUED = "review_queued"
    FINDINGS_AVAILABLE = "findings_available"
    REVIEW_COMPLETED = "review_completed"
    REVIEW_FAILED = "review_failed"
    ACCOUNT_REGISTERED = "account_registered"
    EMAIL_VERIFIED = "email_verified"
    PASSWORD_RESET = "password_reset"
    PASSWORD_SIGNED_IN = "password_signed_in"
    OAUTH_SIGNED_IN = "oauth_signed_in"
    LOGGED_OUT = "logged_out"
    GITHUB_CONNECTED = "github_connected"
    ISSUE_CREATED = "issue_created"
    ISSUE_CREATION_FAILED = "issue_creation_failed"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id", "dedupe_key", name="notifications_owner_dedupe_key"
        ),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 200", name="notifications_title_length"
        ),
        sa.CheckConstraint(
            "length(body) BETWEEN 1 AND 2000", name="notifications_body_length"
        ),
        sa.CheckConstraint(
            "action_path IS NULL OR action_path ~ '^/[^/].*'",
            name="notifications_action_path_relative",
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
    category: Mapped[NotificationCategory] = mapped_column(
        native_enum(NotificationCategory, "notification_category", "public"),
        nullable=False,
    )
    event_type: Mapped[NotificationEventType] = mapped_column(
        native_enum(NotificationEventType, "notification_event_type", "public"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    action_path: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    data: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    dedupe_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    read_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


sa.Index(
    "notifications_owner_created_idx",
    Notification.owner_id,
    Notification.created_at.desc(),
    Notification.id.desc(),
)
sa.Index(
    "notifications_owner_unread_idx",
    Notification.owner_id,
    Notification.created_at.desc(),
    postgresql_where=Notification.read_at.is_(None),
)
