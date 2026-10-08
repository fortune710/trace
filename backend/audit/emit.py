"""Safe best-effort bridge from request logging to the durable outbox."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from uuid import UUID

from audit.outbox import AuditRecorder

logger = logging.getLogger("trace.audit")


def enqueue_audit(
    recorder: AuditRecorder | None,
    *,
    event_type: str,
    request_id: str,
    owner_id: UUID | None,
    fields: Mapping[str, str],
) -> None:
    if recorder is None:
        return
    try:
        recorder.create_event(
            event_type=event_type,
            request_id=request_id,
            owner_id=owner_id,
            fields=fields,
        )
    except Exception:  # noqa: BLE001 - audit failures are intentionally redacted
        # The event envelope is deliberately not included in the log.  The
        # outbox worker remains responsible for delivery once enqueue succeeds.
        logger.error("audit_enqueue_failed")
