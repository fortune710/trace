"""Internal audit service facade used by application and maintenance code."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from audit.outbox import AuditRecorder
from audit.store import AppendOnlyAuditStore, AuditEnqueueReceipt, AuditPage


class AuditService:
    def __init__(self, *, recorder: AuditRecorder, store: AppendOnlyAuditStore) -> None:
        self._recorder = recorder
        self._store = store

    def create_event(
        self,
        *,
        event_type: str,
        request_id: str,
        owner_id: UUID | None,
        fields: Mapping[str, str],
        occurred_at: datetime | None = None,
        event_id: UUID | None = None,
    ) -> AuditEnqueueReceipt:
        return self._recorder.create_event(
            event_type=event_type,
            request_id=request_id,
            owner_id=owner_id,
            fields=fields,
            occurred_at=occurred_at,
            event_id=event_id,
        )

    def list_all(self, *, page: int = 1, page_size: int = 20) -> AuditPage:
        return self._store.list_all(page=page, page_size=page_size)

    def list_for_user(
        self, owner_id: UUID, *, page: int = 1, page_size: int = 20
    ) -> AuditPage:
        return self._store.list_for_user(owner_id, page=page, page_size=page_size)
