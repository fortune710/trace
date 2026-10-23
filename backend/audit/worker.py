"""At-least-once audit outbox worker."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from audit.models import AuditDeliveryJob, AuditDeliveryStatus
from audit.store import (
    AppendOnlyAuditStore,
    AuditIntegrityConflict,
    AuditIntegrityError,
    event_from_canonical_json,
    event_hash,
)

logger = logging.getLogger("trace.audit.worker")


@dataclass(frozen=True, slots=True)
class _Claim:
    event_id: Any
    owner_id: Any
    canonical_json: str
    event_hash: str
    attempt_count: int


class AuditDeliveryWorker:
    def __init__(
        self,
        *,
        engine: Engine,
        store: AppendOnlyAuditStore,
        max_attempts: int = 8,
        retry_base_seconds: int = 5,
        retry_max_seconds: int = 900,
        outbox_retention_days: int = 30,
        dead_letter_retention_days: int = 90,
    ) -> None:
        if (
            max_attempts < 1
            or retry_base_seconds < 1
            or retry_max_seconds < retry_base_seconds
        ):
            raise ValueError("audit worker retry configuration is invalid")
        if outbox_retention_days < 1 or dead_letter_retention_days < 1:
            raise ValueError("audit worker retention configuration is invalid")
        self._engine = engine
        self._store = store
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._outbox_retention_days = outbox_retention_days
        self._dead_letter_retention_days = dead_letter_retention_days

    def _claim(self) -> _Claim | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(minutes=5)
        with self._engine.begin() as connection:
            job = (
                connection.execute(
                    sa.select(AuditDeliveryJob.__table__)
                    .where(
                        sa.or_(
                            sa.and_(
                                AuditDeliveryJob.status == AuditDeliveryStatus.PENDING,
                                sa.or_(
                                    AuditDeliveryJob.next_attempt_at.is_(None),
                                    AuditDeliveryJob.next_attempt_at <= now,
                                ),
                            ),
                            sa.and_(
                                AuditDeliveryJob.status
                                == AuditDeliveryStatus.PROCESSING,
                                AuditDeliveryJob.updated_at <= stale_before,
                            ),
                        )
                    )
                    .order_by(AuditDeliveryJob.created_at, AuditDeliveryJob.event_id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                return None
            attempt_count = job["attempt_count"] + 1
            connection.execute(
                sa.update(AuditDeliveryJob)
                .where(AuditDeliveryJob.event_id == job["event_id"])
                .values(
                    status=AuditDeliveryStatus.PROCESSING,
                    attempt_count=attempt_count,
                    next_attempt_at=None,
                    updated_at=now,
                )
            )
            return _Claim(
                event_id=job["event_id"],
                owner_id=job["owner_id"],
                canonical_json=job["canonical_json"],
                event_hash=job["event_hash"],
                attempt_count=attempt_count,
            )

    def run_once(self) -> bool:
        claim = self._claim()
        if claim is None:
            return False
        try:
            event = event_from_canonical_json(claim.canonical_json)
            if event_hash(event) != claim.event_hash:
                raise AuditIntegrityError("audit outbox integrity validation failed")
            record = self._store.append(event)
            if record.event_hash != claim.event_hash:
                raise AuditIntegrityError("audit delivery hash validation failed")
            with self._engine.begin() as connection:
                connection.execute(
                    sa.update(AuditDeliveryJob)
                    .where(AuditDeliveryJob.event_id == claim.event_id)
                    .values(
                        status=AuditDeliveryStatus.DELIVERED,
                        transaction_id=record.transaction_id,
                        transaction_hash=record.transaction_hash,
                        failure_reason=None,
                        updated_at=datetime.now(UTC),
                    )
                )
            logger.info(
                "audit_delivery_succeeded", extra={"attempt": claim.attempt_count}
            )
            return True
        except (AuditIntegrityConflict, AuditIntegrityError):
            self._dead_letter(claim, "integrity_conflict")
            return True
        except Exception:  # noqa: BLE001 - provider errors are never logged
            if claim.attempt_count >= self._max_attempts:
                self._dead_letter(claim, "delivery_exhausted")
            else:
                delay = min(
                    self._retry_max_seconds,
                    self._retry_base_seconds * (2 ** max(claim.attempt_count - 1, 0)),
                )
                self._retry(claim, delay)
            return True

    def _retry(self, claim: _Claim, delay_seconds: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(AuditDeliveryJob)
                .where(AuditDeliveryJob.event_id == claim.event_id)
                .values(
                    status=AuditDeliveryStatus.PENDING,
                    next_attempt_at=datetime.now(UTC)
                    + timedelta(seconds=delay_seconds),
                    failure_reason="delivery_failed",
                    updated_at=datetime.now(UTC),
                )
            )
        logger.warning(
            "audit_delivery_retry_scheduled",
            extra={"attempt": claim.attempt_count, "delay_seconds": delay_seconds},
        )

    def _dead_letter(self, claim: _Claim, reason: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(AuditDeliveryJob)
                .where(AuditDeliveryJob.event_id == claim.event_id)
                .values(
                    status=AuditDeliveryStatus.DEAD_LETTER,
                    failure_reason=reason,
                    updated_at=datetime.now(UTC),
                )
            )
        logger.error("audit_delivery_dead_letter", extra={"reason": reason})

    def compact(self) -> int:
        """Remove only transient delivery rows after their retention period."""

        now = datetime.now(UTC)
        delivered_before = now - timedelta(days=self._outbox_retention_days)
        dead_letter_before = now - timedelta(days=self._dead_letter_retention_days)
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.delete(AuditDeliveryJob).where(
                    sa.or_(
                        sa.and_(
                            AuditDeliveryJob.status == AuditDeliveryStatus.DELIVERED,
                            AuditDeliveryJob.updated_at < delivered_before,
                        ),
                        sa.and_(
                            AuditDeliveryJob.status == AuditDeliveryStatus.DEAD_LETTER,
                            AuditDeliveryJob.updated_at < dead_letter_before,
                        ),
                    )
                )
            )
            return result.rowcount or 0

    def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        last_compaction = 0.0
        while True:
            processed = self.run_once()
            now = time.monotonic()
            if now - last_compaction >= 60:
                self.compact()
                last_compaction = now
            if not processed:
                time.sleep(poll_seconds)
