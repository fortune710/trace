"""Runtime construction for the internal audit recorder."""

from __future__ import annotations

from functools import lru_cache

from audit.config import AuditSettings
from audit.immudb import ImmudbAuditStore
from audit.outbox import AuditRecorder
from db.session import get_engine


@lru_cache
def get_audit_recorder() -> AuditRecorder | None:
    settings = AuditSettings()
    settings.validate_for_audit()
    if not settings.enabled:
        return None
    # The API only enqueues.  A separate worker owns the immudb client and its
    # process-local root state, avoiding unsafe cross-process SDK sharing.
    return AuditRecorder(get_engine())


@lru_cache
def get_audit_store() -> ImmudbAuditStore:
    settings = AuditSettings()
    settings.validate_for_audit()
    if not settings.enabled:
        raise RuntimeError("immutable audit storage is disabled")
    return ImmudbAuditStore.from_settings(settings)
