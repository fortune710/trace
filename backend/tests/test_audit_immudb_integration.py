import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from audit.config import AuditSettings
from audit.immudb import ImmudbAuditStore
from audit.store import AuditEvent


@pytest.mark.integration
def test_immudb_connection_and_verified_audit_round_trip() -> None:
    if os.environ.get("AUDIT_ENABLED", "false").lower() != "true":
        pytest.skip("immudb integration service is not configured")
    settings = AuditSettings()
    settings.validate_for_audit()
    store = ImmudbAuditStore.from_settings(settings)
    event = AuditEvent(
        event_type="integration.audit",
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        request_id="integration-request",
        owner_id=None,
        fields={"status": "connected"},
    )
    record = store.append(event)
    assert record.event_hash
    assert store.list_all(page=1, page_size=20).items
