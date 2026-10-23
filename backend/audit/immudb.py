"""immudb-backed append-only audit store.

The SDK is imported lazily so unit tests can use :class:`InMemoryAuditStore`
without requiring a running immudb server.  Each worker process owns one client
and one root-state file; the SDK documents that root state must not be shared
between processes.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from audit.store import (
    AuditEvent,
    AuditEventRecord,
    AuditIntegrityConflict,
    AuditIntegrityError,
    AuditPage,
    _page_records,
    canonical_event_document,
    event_hash,
    event_key,
    user_index_key,
    validate_page,
    verify_record,
)

logger = logging.getLogger("trace.audit.immudb")


class ImmudbAuditStore:
    """Append and read audit records using the official Python SDK."""

    def __init__(
        self,
        *,
        client: Any,
        client_lock: threading.RLock | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._client = client
        self._lock = client_lock or threading.RLock()
        self._client_factory = client_factory

    @classmethod
    def from_settings(cls, settings: Any) -> ImmudbAuditStore:
        state_dir = Path(settings.root_state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / f"immudb-{settings.database}.state"
        if state_file.exists() and not state_file.is_file():
            raise ValueError("audit root state path is invalid")

        try:
            from immudb.client import ImmudbClient  # type: ignore[import-not-found]
            from immudb.rootService import (  # type: ignore[import-not-found]
                PersistentRootService,
            )
        except ImportError as error:  # pragma: no cover - exercised in packaging
            raise RuntimeError("the immudb SDK is not installed") from error

        public_key = settings.public_key_file or None

        def factory() -> Any:
            # immudb-py currently exposes gRPC credentials through its client
            # constructor.  TLS/public-key paths are validated by settings and
            # the signing key is passed to the SDK for proof verification.
            client = ImmudbClient(
                f"{settings.host}:{settings.port}",
                rs=PersistentRootService(str(state_file)),
                publicKeyFile=public_key,
                timeout=settings.request_timeout_seconds,
            )
            if settings.tls:
                import grpc  # type: ignore[import-untyped]

                secure_credentials = grpc.ssl_channel_credentials(
                    root_certificates=Path(settings.ca_file).read_bytes()
                    if settings.ca_file
                    else None
                )
                client.channel.close()
                client.channel = grpc.secure_channel(
                    f"{settings.host}:{settings.port}", secure_credentials
                )
                client._resetStub()
            client.login(
                settings.username,
                settings.password.get_secret_value(),
                database=settings.database.encode("utf-8"),
            )
            return client

        return cls(client=factory(), client_factory=factory)

    def _client_or_reconnect(self) -> Any:
        if self._client is None:
            if self._client_factory is None:
                raise RuntimeError("audit client is unavailable")
            self._client = self._client_factory()
        return self._client

    @staticmethod
    def _payload(event: AuditEvent) -> bytes:
        return json.dumps(
            {
                "event": canonical_event_document(event),
                "event_hash": event_hash(event),
                "hash_algorithm": "sha256",
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _tx_metadata(response: Any) -> tuple[int | None, str | None]:
        header = getattr(response, "header", None)
        if header is not None:
            response = header
        transaction_id = getattr(response, "id", None)
        if transaction_id is None:
            transaction_id = getattr(response, "tx", None)
        if transaction_id is not None:
            try:
                transaction_id = int(transaction_id)
            except (TypeError, ValueError):
                transaction_id = None
        transaction_hash = getattr(response, "txHash", None)
        if transaction_hash is None:
            transaction_hash = getattr(response, "hash", None)
        if isinstance(transaction_hash, bytes):
            transaction_hash = transaction_hash.hex()
        elif transaction_hash is not None:
            transaction_hash = str(transaction_hash)
        return transaction_id, transaction_hash

    def _verified_set_all(
        self, values: dict[bytes, bytes]
    ) -> tuple[int | None, str | None]:
        client = self._client_or_reconnect()
        response = client.setAll(values)
        transaction_id, transaction_hash = self._tx_metadata(response)
        if transaction_id is None:
            raise AuditIntegrityError("immudb did not return transaction metadata")
        # setAll is atomic.  The transaction proof is verified immediately
        # after the write; verifiedTxById also advances the SDK root state.
        #
        # immudb 1.10 returns a valid first transaction, but immudb-py 1.5.0
        # cannot verify that transaction through verifiedTxById when the
        # database root is still at transaction zero.  The write has already
        # committed at that point, so verify every key from the same atomic
        # transaction with verifiedGet and advance the root from those proofs.
        # This fallback is deliberately limited to the SDK's corruption-proof
        # error and still fails closed if any key, value, or transaction ID
        # does not match.
        try:
            proof = client.verifiedTxById(transaction_id)
        except Exception as error:
            try:
                from immudb.exceptions import (  # type: ignore[import-not-found]
                    ErrCorruptedData,
                )
            except ImportError as import_error:
                raise RuntimeError("the immudb SDK is not installed") from import_error
            if not isinstance(error, ErrCorruptedData):
                raise
            verified_ids: set[int] = set()
            for key, expected_value in values.items():
                verified_value = client.verifiedGet(key)
                actual_value = getattr(verified_value, "value", None)
                if actual_value != expected_value:
                    raise AuditIntegrityError("immudb write verification failed")
                verified_id = getattr(verified_value, "id", None)
                if verified_id is None:
                    raise AuditIntegrityError("immudb write metadata is incomplete")
                verified_ids.add(int(verified_id))
            if verified_ids != {transaction_id}:
                raise AuditIntegrityError("immudb write was not atomic")
            state = getattr(client, "_rs", None)
            state = state.get() if state is not None else None
            state_id = getattr(state, "txId", None)
            state_hash = getattr(state, "txHash", None)
            if state_id != transaction_id:
                raise AuditIntegrityError("immudb verification state is invalid")
            if isinstance(state_hash, bytes):
                transaction_hash = state_hash.hex()
            elif state_hash is not None:
                transaction_hash = str(state_hash)
            return transaction_id, transaction_hash
        if transaction_hash is None:
            _, transaction_hash = self._tx_metadata(proof)
        return transaction_id, transaction_hash

    def _scan(
        self, *, prefix: str, page: int, page_size: int
    ) -> list[tuple[str, bytes]]:
        validate_page(page, page_size)
        with self._lock:
            client = self._client_or_reconnect()
            requested = (page * page_size) + 1
            values = client.scan(
                key=b"",
                prefix=prefix.encode("utf-8"),
                desc=True,
                limit=requested,
            )
        return [
            (key.decode("utf-8"), value)
            for key, value in values.items()
            if key.decode("utf-8").startswith(prefix)
        ]

    @staticmethod
    def _record_from_payload(
        payload: bytes, *, event_key_value: str
    ) -> AuditEventRecord:
        try:
            decoded = json.loads(payload.decode("utf-8"))
            document = decoded["event"]
            event = AuditEvent(
                event_type=document["event_type"],
                event_id=UUID(document["event_id"]),
                occurred_at=__import__("datetime").datetime.fromisoformat(
                    document["occurred_at"]
                ),
                request_id=document["request_id"],
                owner_id=(UUID(document["owner_id"]) if document["owner_id"] else None),
                fields=document["fields"],
            )
            record = AuditEventRecord(
                event=event,
                event_hash=decoded["event_hash"],
                hash_algorithm=decoded["hash_algorithm"],
                event_key=event_key_value,
            )
            return verify_record(record)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise AuditIntegrityError(
                "audit record integrity validation failed"
            ) from error

    def _read_event(self, key: str) -> AuditEventRecord:
        with self._lock:
            response = self._client_or_reconnect().verifiedGet(key.encode("utf-8"))
            payload = getattr(response, "value", None)
            if payload is None:
                raise AuditIntegrityError("immudb returned an empty audit record")
            record = self._record_from_payload(payload, event_key_value=key)
            tx_id, tx_hash = self._tx_metadata(response)
            if tx_id is None:
                tx_id, tx_hash = self._tx_metadata(getattr(response, "tx", response))
            return AuditEventRecord(
                event=record.event,
                event_hash=record.event_hash,
                hash_algorithm=record.hash_algorithm,
                transaction_id=tx_id,
                transaction_hash=tx_hash,
                event_key=record.event_key,
            )

    def append(self, event: AuditEvent) -> AuditEventRecord:
        candidate_hash = event_hash(event)
        primary_key = event_key(event)
        index_key = user_index_key(event)
        with self._lock:
            # The event key is deterministic for normal retries.  Scan by ID
            # as well so a reused ID with changed content becomes an integrity
            # conflict rather than a second logical event.
            existing = self._find_event_id(event.event_id)
            if existing is not None:
                if existing.event_hash != candidate_hash:
                    raise AuditIntegrityConflict("audit event integrity conflict")
                return existing

            values = {primary_key.encode("utf-8"): self._payload(event)}
            if index_key is not None:
                values[index_key.encode("utf-8")] = primary_key.encode("utf-8")
            tx_id, tx_hash = self._verified_set_all(values)
            record = AuditEventRecord(
                event=event,
                event_hash=candidate_hash,
                transaction_id=tx_id,
                transaction_hash=tx_hash,
                event_key=primary_key,
            )
            return verify_record(record)

    def _find_event_id(self, event_id: UUID) -> AuditEventRecord | None:
        client = self._client_or_reconnect()
        values = client.scan(
            key=b"",
            prefix=b"audit:event:",
            desc=False,
            limit=1000,
        )
        for key in values:
            key_text = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            if key_text.endswith(str(event_id)):
                return self._read_event(key_text)
        return None

    def list_all(self, *, page: int = 1, page_size: int = 50) -> AuditPage:
        entries = self._scan(prefix="audit:event:", page=page, page_size=page_size)
        records = [
            self._record_from_payload(value, event_key_value=key)
            for key, value in entries
        ]
        records = records[(page - 1) * page_size :]
        return (
            _page_records(records, page=1, page_size=page_size)
            if page == 1
            else AuditPage(
                tuple(records[:page_size]),
                page,
                page_size,
                page + 1 if len(records) > page_size else None,
            )
        )

    def list_for_user(
        self, owner_id: UUID, *, page: int = 1, page_size: int = 50
    ) -> AuditPage:
        if not isinstance(owner_id, UUID):
            raise TypeError("audit owner id is invalid")
        prefix = f"audit:user:{owner_id}:"
        entries = self._scan(prefix=prefix, page=page, page_size=page_size)
        start = (page - 1) * page_size
        selected = entries[start : start + page_size]
        records = [self._read_event(value.decode("utf-8")) for _, value in selected]
        return AuditPage(
            tuple(records),
            page,
            page_size,
            page + 1 if len(entries) > start + page_size else None,
        )
