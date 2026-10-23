"""Durable, transient delivery queue for immutable audit events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine

from audit.models import AuditDeliveryJob, AuditDeliveryStatus
from audit.store import (
    AuditEnqueueReceipt,
    AuditEvent,
    AuditIntegrityConflict,
    canonical_event_json,
    event_hash,
)
from auth.uuids import uuid7


class AuditRecorder:
    """Create bounded audit events and enqueue them without storing secrets."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _enqueue(connection: Connection, event: AuditEvent) -> AuditEnqueueReceipt:
        payload = canonical_event_json(event)
        digest = event_hash(event)
        statement = (
            insert(AuditDeliveryJob)
            .values(
                event_id=event.event_id,
                owner_id=event.owner_id,
                canonical_json=payload,
                event_hash=digest,
                status=AuditDeliveryStatus.PENDING,
            )
            .on_conflict_do_nothing(index_elements=[AuditDeliveryJob.event_id])
        )
        connection.execute(statement)
        row = connection.execute(
            sa.select(
                AuditDeliveryJob.event_id,
                AuditDeliveryJob.event_hash,
                AuditDeliveryJob.status,
            ).where(AuditDeliveryJob.event_id == event.event_id)
        ).one()
        if row.event_hash != digest:
            raise AuditIntegrityConflict("audit event integrity conflict")
        status = (
            row.status.value
            if isinstance(row.status, AuditDeliveryStatus)
            else str(row.status)
        )
        return AuditEnqueueReceipt(event.event_id, digest, status)

    def enqueue(
        self, event: AuditEvent, *, connection: Connection | None = None
    ) -> AuditEnqueueReceipt:
        if connection is not None:
            return self._enqueue(connection, event)
        with self._engine.begin() as owned_connection:
            return self._enqueue(owned_connection, event)

    def create_event(
        self,
        *,
        event_type: str,
        request_id: str,
        owner_id: UUID | None,
        fields: Mapping[str, str],
        event_id: UUID | None = None,
        occurred_at: datetime | None = None,
        connection: Connection | None = None,
    ) -> AuditEnqueueReceipt:
        event = AuditEvent(
            event_type=event_type,
            event_id=event_id or uuid7(),
            occurred_at=occurred_at or datetime.now(UTC),
            request_id=request_id,
            owner_id=owner_id,
            fields=fields,
        )
        return self.enqueue(event, connection=connection)
