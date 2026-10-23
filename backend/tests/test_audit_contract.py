from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from audit.config import AuditConfigurationError, AuditSettings
from audit.immudb import ImmudbAuditStore
from audit.store import (
    AuditEvent,
    AuditIntegrityError,
    InMemoryAuditStore,
    canonical_event_json,
    event_hash,
    event_key,
    user_index_key,
)


def make_event(
    *,
    event_id: UUID | None = None,
    owner_id: UUID | None = None,
    occurred_at: datetime | None = None,
    **fields: str,
) -> AuditEvent:
    return AuditEvent(
        event_type="project.created",
        event_id=event_id or uuid4(),
        occurred_at=occurred_at or datetime.now(UTC),
        request_id="request-1",
        owner_id=owner_id,
        fields=fields,
    )


def test_canonical_serialization_and_hash_are_mapping_order_independent() -> None:
    timestamp = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    first = make_event(
        owner_id=uuid4(), occurred_at=timestamp, zeta="last", alpha="first"
    )
    second = AuditEvent(
        event_type=first.event_type,
        event_id=first.event_id,
        occurred_at=timestamp,
        request_id=first.request_id,
        owner_id=first.owner_id,
        fields={"alpha": "first", "zeta": "last"},
    )
    assert canonical_event_json(first) == canonical_event_json(second)
    assert event_hash(first) == event_hash(second)


def test_hash_changes_when_event_content_changes() -> None:
    event = make_event(owner_id=uuid4(), action="created")
    changed = AuditEvent(
        event_type=event.event_type,
        event_id=event.event_id,
        occurred_at=event.occurred_at,
        request_id=event.request_id,
        owner_id=event.owner_id,
        fields={"action": "updated"},
    )
    assert event_hash(event) != event_hash(changed)


def test_event_and_user_index_keys_are_deterministic_and_ownerless_has_no_index() -> (
    None
):
    timestamp = datetime(2026, 10, 7, 12, 0, 0, 123456, tzinfo=UTC)
    owner = uuid4()
    event = make_event(owner_id=owner, occurred_at=timestamp)
    assert event_key(event).startswith("audit:event:")
    assert user_index_key(event) == (
        f"audit:user:{owner}:{int(timestamp.timestamp() * 1_000_000_000):020d}:"
        f"{event.event_id}"
    )
    assert user_index_key(make_event(occurred_at=timestamp)) is None


def test_in_memory_pagination_is_newest_first_and_owner_scoped() -> None:
    store = InMemoryAuditStore()
    owner = uuid4()
    for index in range(3):
        store.append(
            make_event(
                owner_id=owner,
                occurred_at=datetime(2026, 10, 7, 12, index, tzinfo=UTC),
                sequence=str(index),
            )
        )
    store.append(
        make_event(
            owner_id=uuid4(),
            occurred_at=datetime(2026, 10, 7, 13, tzinfo=UTC),
            sequence="foreign",
        )
    )
    page = store.list_for_user(owner, page=1, page_size=2)
    assert [item.fields["sequence"] for item in page.items] == ["2", "1"]
    assert page.next_page == 2
    assert [
        item.fields["sequence"]
        for item in store.list_for_user(owner, page=2, page_size=2).items
    ] == ["0"]
    assert store.list_all(page=1, page_size=2).next_page == 2


@pytest.mark.parametrize("page,page_size", [(0, 20), (1, 0), (1, 101), (True, 20)])
def test_page_validation_rejects_invalid_values(page: int, page_size: int) -> None:
    with pytest.raises(ValueError):
        InMemoryAuditStore().list_all(page=page, page_size=page_size)


def test_audit_configuration_rejects_incomplete_enabled_configuration(
    tmp_path: Path,
) -> None:
    with pytest.raises(AuditConfigurationError):
        AuditSettings(enabled=True, root_state_dir=str(tmp_path)).validate_for_audit()

    with pytest.raises(AuditConfigurationError):
        AuditSettings(
            enabled=True,
            username="audit",
            password="password",
            root_state_dir="relative/state",
        ).validate_for_audit()


class _Response:
    def __init__(self, value: bytes | None = None, transaction_id: int = 1) -> None:
        self.value = value
        self.id = transaction_id


class _FakeClient:
    def __init__(self) -> None:
        self.values: dict[bytes, bytes] = {}
        self.verified_write_ids: list[int] = []

    def setAll(self, values: dict[bytes, bytes]) -> _Response:
        self.values.update(values)
        return _Response(transaction_id=7)

    def verifiedTxById(self, transaction_id: int) -> None:
        self.verified_write_ids.append(transaction_id)

    def verifiedGet(self, key: bytes) -> _Response:
        return _Response(self.values[key], transaction_id=7)

    def scan(
        self, *, key: bytes, prefix: bytes, desc: bool, limit: int
    ) -> dict[bytes, bytes]:
        matching = sorted(
            (
                (stored_key, value)
                for stored_key, value in self.values.items()
                if stored_key.startswith(prefix)
            ),
            key=lambda pair: pair[0],
            reverse=desc,
        )
        return dict(matching[:limit])


def test_immudb_adapter_uses_atomic_write_and_verified_transaction() -> None:
    client = _FakeClient()
    store = ImmudbAuditStore(client=client)
    event = make_event(owner_id=uuid4())
    record = store.append(event)
    assert record.transaction_id == 7
    assert client.verified_write_ids == [7]
    assert len(client.values) == 2
    assert store.append(event) == record


def test_immudb_adapter_detects_read_hash_mismatch() -> None:
    client = _FakeClient()
    store = ImmudbAuditStore(client=client)
    event = make_event(owner_id=uuid4())
    store.append(event)
    key = next(key for key in client.values if key.startswith(b"audit:event:"))
    client.values[key] = client.values[key].replace(
        b"project.created", b"project.updated"
    )
    with pytest.raises(AuditIntegrityError):
        store.list_all()
