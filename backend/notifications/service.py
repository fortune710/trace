"""Notification creation and owner-scoped persistence operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from db.rls import principal_transaction
from notifications.models import (
    Notification,
    NotificationCategory,
    NotificationEventType,
)


@dataclass(frozen=True)
class NotificationTemplate:
    category: NotificationCategory
    title: str
    body: str


_TEMPLATES: dict[NotificationEventType, NotificationTemplate] = {
    NotificationEventType.REVIEW_QUEUED: NotificationTemplate(
        NotificationCategory.INFO, "Review queued", "Your review has been queued."
    ),
    NotificationEventType.FINDINGS_AVAILABLE: NotificationTemplate(
        NotificationCategory.INFO,
        "Findings available",
        "Your review has started producing findings.",
    ),
    NotificationEventType.REVIEW_COMPLETED: NotificationTemplate(
        NotificationCategory.INFO, "Review completed", "Your review is ready to view."
    ),
    NotificationEventType.REVIEW_FAILED: NotificationTemplate(
        NotificationCategory.WARNING,
        "Review needs attention",
        "Your review could not be completed. Open it to try again.",
    ),
    NotificationEventType.ACCOUNT_REGISTERED: NotificationTemplate(
        NotificationCategory.SECURITY,
        "Account created",
        "Verify your email to finish setting up your account.",
    ),
    NotificationEventType.EMAIL_VERIFIED: NotificationTemplate(
        NotificationCategory.SECURITY,
        "Email verified",
        "Your email address has been verified.",
    ),
    NotificationEventType.PASSWORD_RESET: NotificationTemplate(
        NotificationCategory.SECURITY,
        "Password reset",
        "Your password was reset successfully.",
    ),
    NotificationEventType.PASSWORD_SIGNED_IN: NotificationTemplate(
        NotificationCategory.SECURITY, "Signed in", "You signed in with your password."
    ),
    NotificationEventType.OAUTH_SIGNED_IN: NotificationTemplate(
        NotificationCategory.SECURITY,
        "Signed in",
        "You signed in with your connected account.",
    ),
    NotificationEventType.LOGGED_OUT: NotificationTemplate(
        NotificationCategory.SECURITY, "Signed out", "You signed out successfully."
    ),
    NotificationEventType.GITHUB_CONNECTED: NotificationTemplate(
        NotificationCategory.INFO,
        "GitHub connected",
        "Your GitHub account is connected.",
    ),
    NotificationEventType.ISSUE_CREATED: NotificationTemplate(
        NotificationCategory.INFO,
        "Issue created",
        "Your finding has been added to an issue tracker.",
    ),
    NotificationEventType.ISSUE_CREATION_FAILED: NotificationTemplate(
        NotificationCategory.WARNING,
        "Issue creation needs attention",
        "Trace could not create an issue for your finding. Open it to review the saved destination and try again.",
    ),
}


def create_notification(
    connection: Connection,
    *,
    owner_id: UUID,
    event_type: NotificationEventType,
    dedupe_key: str,
    review_id: UUID | None = None,
    action_path: str | None = None,
    data: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Insert a templated notification and announce only its safe identifiers."""
    template = _TEMPLATES[event_type]
    notification_data: dict[str, object] = (
        {"review_id": str(review_id)} if review_id else {}
    )
    if data:
        notification_data.update(data)
    notification_action_path = action_path
    if review_id and notification_action_path is None:
        notification_action_path = (
            f"/reviews/{review_id}?tab=findings"
            if event_type is NotificationEventType.FINDINGS_AVAILABLE
            else f"/reviews/{review_id}"
        )
    row = (
        connection.execute(
            pg_insert(Notification)
            .values(
                owner_id=owner_id,
                category=template.category,
                event_type=event_type,
                title=template.title,
                body=template.body,
                action_path=notification_action_path,
                data=notification_data,
                dedupe_key=dedupe_key,
            )
            .on_conflict_do_nothing(
                index_elements=[Notification.owner_id, Notification.dedupe_key]
            )
            .returning(Notification.__table__)
        )
        .mappings()
        .one_or_none()
    )
    if row is not None:
        connection.execute(
            sa.text("SELECT pg_notify('trace_notifications', :payload)"),
            {
                "payload": json.dumps(
                    {"owner_id": str(owner_id), "notification_id": str(row["id"])}
                )
            },
        )
    return _response(row) if row is not None else None


class NotificationService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(
        self, *, owner_id: UUID, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int | None, int]:
        with principal_transaction(self._engine, owner_id) as connection:
            rows = (
                connection.execute(
                    sa.select(Notification.__table__)
                    .where(Notification.owner_id == owner_id)
                    .order_by(Notification.created_at.desc(), Notification.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
            unread_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(Notification)
                .where(
                    Notification.owner_id == owner_id, Notification.read_at.is_(None)
                )
            ).scalar_one()
        return (
            [_response(row) for row in rows[:limit]],
            (offset + limit if len(rows) > limit else None),
            unread_count,
        )

    def get(self, *, owner_id: UUID, notification_id: UUID) -> dict[str, object] | None:
        with principal_transaction(self._engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.select(Notification.__table__).where(
                        Notification.owner_id == owner_id,
                        Notification.id == notification_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _response(row) if row is not None else None

    def mark_read(
        self, *, owner_id: UUID, notification_id: UUID
    ) -> tuple[dict[str, object] | None, bool]:
        with principal_transaction(self._engine, owner_id) as connection:
            changed = (
                connection.execute(
                    sa.update(Notification)
                    .where(
                        Notification.owner_id == owner_id,
                        Notification.id == notification_id,
                        Notification.read_at.is_(None),
                    )
                    .values(read_at=sa.func.now())
                    .returning(Notification.id)
                ).scalar_one_or_none()
                is not None
            )
            row = (
                connection.execute(
                    sa.select(Notification.__table__).where(
                        Notification.owner_id == owner_id,
                        Notification.id == notification_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return (_response(row) if row is not None else None), changed

    def mark_all_read(self, *, owner_id: UUID) -> tuple[int, object | None]:
        with principal_transaction(self._engine, owner_id) as connection:
            rows = (
                connection.execute(
                    sa.update(Notification)
                    .where(
                        Notification.owner_id == owner_id,
                        Notification.read_at.is_(None),
                    )
                    .values(read_at=sa.func.now())
                    .returning(Notification.read_at)
                )
                .scalars()
                .all()
            )
        return len(rows), (rows[0] if rows else None)


def _response(row: Notification | sa.RowMapping | None) -> dict[str, object]:
    assert row is not None
    return {
        "id": str(row.id if isinstance(row, Notification) else row["id"]),
        "category": (
            row.category if isinstance(row, Notification) else row["category"]
        ).value,
        "event_type": (
            row.event_type if isinstance(row, Notification) else row["event_type"]
        ).value,
        "title": row.title if isinstance(row, Notification) else row["title"],
        "body": row.body if isinstance(row, Notification) else row["body"],
        "action_path": row.action_path
        if isinstance(row, Notification)
        else row["action_path"],
        "data": row.data if isinstance(row, Notification) else row["data"],
        "created_at": row.created_at
        if isinstance(row, Notification)
        else row["created_at"],
        "read_at": row.read_at if isinstance(row, Notification) else row["read_at"],
    }
