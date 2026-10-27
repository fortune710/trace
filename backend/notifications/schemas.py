from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from notifications.models import NotificationCategory, NotificationEventType


class NotificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    category: NotificationCategory
    event_type: NotificationEventType
    title: str
    body: str
    action_path: str | None
    data: dict[str, object]
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    next_offset: int | None
    unread_count: int


class MarkReadResponse(BaseModel):
    item: NotificationResponse
    changed: bool


class MarkAllReadResponse(BaseModel):
    marked_count: int = Field(ge=0)
    read_at: datetime | None
