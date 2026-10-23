from datetime import UTC, datetime
from uuid import uuid4

import pytest

from audit.store import AuditEvent, AuditIntegrityConflict, InMemoryAuditStore


def make_event(**fields: str) -> AuditEvent:
    return AuditEvent(
        event_type="credential.rotated",
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        request_id="request-1",
        owner_id=uuid4(),
        fields=fields,
    )


def test_audit_store_is_append_only_and_idempotent_for_same_event() -> None:
    store = InMemoryAuditStore()
    event = make_event(provider="github")
    first = store.append(event)
    second = store.append(event)
    assert store.snapshot() == (event,)
    assert second == first


def test_audit_store_rejects_reused_event_id_with_different_content() -> None:
    store = InMemoryAuditStore()
    event = make_event(provider="github")
    store.append(event)
    conflicting = AuditEvent(
        event_type=event.event_type,
        event_id=event.event_id,
        occurred_at=event.occurred_at,
        request_id=event.request_id,
        owner_id=event.owner_id,
        fields={"provider": "gitlab"},
    )
    with pytest.raises(AuditIntegrityConflict, match="integrity"):
        store.append(conflicting)


@pytest.mark.parametrize(
    "field", ["access_token", "client_secret", "raw_request_body", "ciphertext"]
)
def test_audit_event_rejects_secret_or_raw_body_fields(field: str) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        make_event(**{field: "do-not-store"})
