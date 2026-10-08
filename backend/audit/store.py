"""Secret-resistant append-only audit contracts and test implementation."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

_COMPONENT = re.compile(r"^[a-z0-9_.-]{1,96}$")
_FORBIDDEN_FIELD = re.compile(
    r"(?:token|secret|password|ciphertext|private[_-]?key|request[_-]?body|raw[_-]?body)",
    re.IGNORECASE,
)
_FORBIDDEN_VALUE = re.compile(
    r"(?:"
    r"bearer\s+[a-z0-9._~+/=-]{16,}|"
    r"-----begin[^\n]{0,64}-----|"
    r"eyj[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}|"
    r"gh[opusr]_[-a-z0-9_]{8,}|"
    r"sk-[-a-z0-9_]{8,}|"
    r"hvs\.[-a-z0-9_]{8,}|"
    r"vault:v[0-9]+:[-a-z0-9_]{8,}"
    r")",
    re.IGNORECASE,
)
_MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 50


class AuditIntegrityError(RuntimeError):
    """Raised when an immutable record no longer matches its stored hash."""


class AuditIntegrityConflict(ValueError):
    """Raised when an event ID is reused for different content."""


def validate_page(page: int, page_size: int) -> tuple[int, int]:
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("audit page must be one-based")
    if (
        not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or page_size < 1
        or page_size > _MAX_PAGE_SIZE
    ):
        raise ValueError("audit page size is invalid")
    return page, page_size


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Bounded event metadata; credentials and raw request data are excluded."""

    event_type: str
    event_id: UUID
    occurred_at: datetime
    request_id: str
    owner_id: UUID | None
    fields: Mapping[str, str]

    def __post_init__(self) -> None:
        if not _COMPONENT.fullmatch(self.event_type) or _FORBIDDEN_FIELD.search(
            self.event_type
        ):
            raise ValueError("audit event type is invalid")
        if not isinstance(self.event_id, UUID):
            raise TypeError("audit event id is invalid")
        if (
            not self.request_id
            or len(self.request_id) > 128
            or _FORBIDDEN_VALUE.search(self.request_id)
        ):
            raise ValueError("audit request id is invalid")
        if self.owner_id is not None and not isinstance(self.owner_id, UUID):
            raise TypeError("audit owner id is invalid")
        normalized_fields: dict[str, str] = {}
        for key, value in self.fields.items():
            if (
                not isinstance(key, str)
                or not _COMPONENT.fullmatch(key)
                or _FORBIDDEN_FIELD.search(key)
            ):
                raise ValueError("audit event contains a sensitive field")
            if not isinstance(value, str) or len(value) > 512:
                raise ValueError("audit field exceeds its maximum length")
            if _FORBIDDEN_VALUE.search(value):
                raise ValueError("audit event contains a sensitive value")
            normalized_fields[key] = value
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        object.__setattr__(self, "fields", normalized_fields)


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    """An event plus its application and immudb integrity metadata."""

    event: AuditEvent
    event_hash: str
    hash_algorithm: str = "sha256"
    transaction_id: int | None = None
    transaction_hash: str | None = None
    event_key: str | None = None

    @property
    def event_type(self) -> str:
        return self.event.event_type

    @property
    def event_id(self) -> UUID:
        return self.event.event_id

    @property
    def occurred_at(self) -> datetime:
        return self.event.occurred_at

    @property
    def request_id(self) -> str:
        return self.event.request_id

    @property
    def owner_id(self) -> UUID | None:
        return self.event.owner_id

    @property
    def fields(self) -> Mapping[str, str]:
        return self.event.fields


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: tuple[AuditEventRecord, ...]
    page: int
    page_size: int
    next_page: int | None


@dataclass(frozen=True, slots=True)
class AuditEnqueueReceipt:
    event_id: UUID
    event_hash: str
    status: str = "queued"


def canonical_event_document(event: AuditEvent) -> dict[str, object]:
    """Return the only payload permitted to cross the audit boundary."""

    return {
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "occurred_at": event.occurred_at.isoformat(),
        "owner_id": str(event.owner_id) if event.owner_id is not None else None,
        "request_id": event.request_id,
        "fields": {key: event.fields[key] for key in sorted(event.fields)},
    }


def canonical_event_json(event: AuditEvent) -> str:
    return json.dumps(
        canonical_event_document(event),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def event_from_canonical_json(value: str) -> AuditEvent:
    try:
        document = json.loads(value)
        return AuditEvent(
            event_type=document["event_type"],
            event_id=UUID(document["event_id"]),
            occurred_at=datetime.fromisoformat(document["occurred_at"]),
            request_id=document["request_id"],
            owner_id=(UUID(document["owner_id"]) if document["owner_id"] else None),
            fields=document["fields"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AuditIntegrityError("audit event serialization is invalid") from error


def event_hash(event: AuditEvent) -> str:
    return hashlib.sha256(canonical_event_json(event).encode("utf-8")).hexdigest()


def event_key(event: AuditEvent) -> str:
    timestamp_ns = int(event.occurred_at.timestamp() * 1_000_000_000)
    return f"audit:event:{timestamp_ns:020d}:{event.event_id}"


def user_index_key(event: AuditEvent) -> str | None:
    if event.owner_id is None:
        return None
    timestamp_ns = int(event.occurred_at.timestamp() * 1_000_000_000)
    return f"audit:user:{event.owner_id}:{timestamp_ns:020d}:{event.event_id}"


def verify_record(record: AuditEventRecord) -> AuditEventRecord:
    if (
        record.hash_algorithm != "sha256"
        or event_hash(record.event) != record.event_hash
    ):
        raise AuditIntegrityError("audit record integrity validation failed")
    return record


class AppendOnlyAuditStore(Protocol):
    """Adapter implemented by immudb and the deterministic test double."""

    def append(self, event: AuditEvent) -> AuditEventRecord: ...

    def list_all(
        self, *, page: int = 1, page_size: int = _DEFAULT_PAGE_SIZE
    ) -> AuditPage: ...

    def list_for_user(
        self, owner_id: UUID, *, page: int = 1, page_size: int = _DEFAULT_PAGE_SIZE
    ) -> AuditPage: ...


def _page_records(
    records: Sequence[AuditEventRecord], *, page: int, page_size: int
) -> AuditPage:
    validate_page(page, page_size)
    ordered = sorted(
        records,
        key=lambda record: (record.occurred_at, str(record.event_id)),
        reverse=True,
    )
    start = (page - 1) * page_size
    selected = tuple(ordered[start : start + page_size])
    has_more = len(ordered) > start + page_size
    return AuditPage(selected, page, page_size, page + 1 if has_more else None)


class InMemoryAuditStore:
    """Deterministic test double with the same idempotency and paging contract."""

    def __init__(self) -> None:
        self._events: dict[UUID, AuditEventRecord] = {}
        self._lock = threading.RLock()

    def append(self, event: AuditEvent) -> AuditEventRecord:
        candidate = AuditEventRecord(
            event=event, event_hash=event_hash(event), event_key=event_key(event)
        )
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is not None:
                if existing.event_hash != candidate.event_hash:
                    raise AuditIntegrityConflict("audit event integrity conflict")
                return existing
            self._events[event.event_id] = candidate
            return candidate

    def create_event(
        self,
        *,
        event_type: str,
        event_id: UUID,
        request_id: str,
        owner_id: UUID | None,
        fields: Mapping[str, str],
        occurred_at: datetime | None = None,
    ) -> AuditEnqueueReceipt:
        event = AuditEvent(
            event_type=event_type,
            event_id=event_id,
            occurred_at=occurred_at or datetime.now(UTC),
            request_id=request_id,
            owner_id=owner_id,
            fields=fields,
        )
        record = self.append(event)
        return AuditEnqueueReceipt(record.event_id, record.event_hash, "persisted")

    def list_all(
        self, *, page: int = 1, page_size: int = _DEFAULT_PAGE_SIZE
    ) -> AuditPage:
        with self._lock:
            return _page_records(
                tuple(self._events.values()), page=page, page_size=page_size
            )

    def list_for_user(
        self, owner_id: UUID, *, page: int = 1, page_size: int = _DEFAULT_PAGE_SIZE
    ) -> AuditPage:
        if not isinstance(owner_id, UUID):
            raise TypeError("audit owner id is invalid")
        with self._lock:
            return _page_records(
                tuple(
                    record
                    for record in self._events.values()
                    if record.owner_id == owner_id
                ),
                page=page,
                page_size=page_size,
            )

    def snapshot(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(record.event for record in self._events.values())
