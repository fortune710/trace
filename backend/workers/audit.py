"""Process entry point for the immutable audit delivery worker."""

from __future__ import annotations

from audit.config import get_audit_settings
from audit.immudb import ImmudbAuditStore
from audit.worker import AuditDeliveryWorker
from db.session import get_engine


def main() -> None:
    settings = get_audit_settings()
    if not settings.enabled:
        raise RuntimeError("audit worker requires AUDIT_ENABLED=true")
    worker = AuditDeliveryWorker(
        engine=get_engine(),
        store=ImmudbAuditStore.from_settings(settings),
        max_attempts=settings.max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
        outbox_retention_days=settings.outbox_retention_days,
        dead_letter_retention_days=settings.dead_letter_retention_days,
    )
    worker.run_forever()


if __name__ == "__main__":
    main()
