"""Durable credential re-encryption and key-rotation worker."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa

from auth.config import AuthSettings
from auth.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    CredentialEncryptionUnavailable,
    EncryptedCredential,
    VaultTransitCredentialCipher,
    credential_cipher_from_settings,
)
from auth.uuids import uuid7
from credentials.models import (
    Credential,
    CredentialEncryptionProvider,
    CredentialReencryptionItem,
    CredentialReencryptionItemStatus,
    CredentialReencryptionRun,
    CredentialReencryptionStatus,
)
from db.session import get_maintenance_engine

logger = logging.getLogger("trace.credential_rotation")
_GENERIC_FAILURE: Final = "credential_rewrap_failed"


@dataclass(frozen=True)
class RotationSummary:
    run_id: UUID
    status: CredentialReencryptionStatus
    scanned_count: int
    rewrapped_count: int
    skipped_count: int
    failed_count: int


class CredentialRotationJob:
    """Run a resumable, owner-independent re-encryption pass.

    The maintenance database role is deliberately separate from the API role and
    has BYPASSRLS because this job is an explicitly trusted operational process.
    It reads ciphertext only and never writes plaintext to the database or logs.
    """

    def __init__(
        self,
        *,
        engine: sa.Engine,
        cipher: CredentialCipher | VaultTransitCredentialCipher,
        encryption_provider: CredentialEncryptionProvider,
        target_key_reference: str,
        target_key_version: str,
        batch_size: int = 100,
        max_attempts: int = 5,
    ) -> None:
        if batch_size < 1 or batch_size > 10_000:
            raise ValueError("batch_size must be between 1 and 10000")
        if max_attempts < 1 or max_attempts > 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if not target_key_reference or not target_key_version:
            raise ValueError("rotation target is incomplete")
        self._engine = engine
        self._cipher = cipher
        self._encryption_provider = encryption_provider
        self._target_key_reference = target_key_reference
        self._target_key_version = target_key_version
        self._batch_size = batch_size
        self._max_attempts = max_attempts

    def run(self, *, run_id: UUID | None = None) -> RotationSummary:
        run_id = self._load_or_create_run(run_id)
        if self._is_completed(run_id):
            return self.summary(run_id)

        with self._engine.begin() as connection:
            connection.execute(
                sa.update(CredentialReencryptionRun)
                .where(CredentialReencryptionRun.id == run_id)
                .values(
                    status=CredentialReencryptionStatus.RUNNING,
                    completed_at=None,
                    updated_at=sa.func.now(),
                )
            )

        while True:
            if self._process_claimed_items(run_id):
                continue
            if self._scan_next_batch(run_id):
                continue
            break

        with self._engine.begin() as connection:
            unresolved = connection.execute(
                sa.select(sa.func.count())
                .select_from(CredentialReencryptionItem)
                .where(
                    CredentialReencryptionItem.run_id == run_id,
                    CredentialReencryptionItem.status.in_(
                        [
                            CredentialReencryptionItemStatus.PENDING,
                            CredentialReencryptionItemStatus.RETRYABLE,
                        ]
                    ),
                )
            ).scalar_one()
            run = (
                connection.execute(
                    sa.select(CredentialReencryptionRun.__table__)
                    .where(CredentialReencryptionRun.id == run_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            final_status = (
                CredentialReencryptionStatus.FAILED
                if unresolved or run["failed_count"]
                else CredentialReencryptionStatus.COMPLETED
            )
            connection.execute(
                sa.update(CredentialReencryptionRun)
                .where(CredentialReencryptionRun.id == run_id)
                .values(
                    status=final_status,
                    completed_at=sa.func.now(),
                    updated_at=sa.func.now(),
                )
            )
        result = self.summary(run_id)
        logger.info(
            "credential_reencryption_finished",
            extra={
                "run_id": str(result.run_id),
                "status": result.status.value,
                "scanned_count": result.scanned_count,
                "rewrapped_count": result.rewrapped_count,
                "skipped_count": result.skipped_count,
                "failed_count": result.failed_count,
            },
        )
        return result

    def summary(self, run_id: UUID) -> RotationSummary:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(CredentialReencryptionRun.__table__).where(
                        CredentialReencryptionRun.id == run_id
                    )
                )
                .mappings()
                .one()
            )
        return RotationSummary(
            run_id=row["id"],
            status=row["status"],
            scanned_count=row["scanned_count"],
            rewrapped_count=row["rewrapped_count"],
            skipped_count=row["skipped_count"],
            failed_count=row["failed_count"],
        )

    def _load_or_create_run(self, run_id: UUID | None) -> UUID:
        if run_id is None:
            run_id = uuid7()
            with self._engine.begin() as connection:
                connection.execute(
                    sa.insert(CredentialReencryptionRun).values(
                        id=run_id,
                        status=CredentialReencryptionStatus.RUNNING,
                        encryption_provider=self._encryption_provider,
                        target_key_reference=self._target_key_reference,
                        target_key_version=self._target_key_version,
                    )
                )
            return run_id

        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(CredentialReencryptionRun.__table__)
                    .where(CredentialReencryptionRun.id == run_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if (
                row["encryption_provider"] != self._encryption_provider
                or row["target_key_reference"] != self._target_key_reference
                or row["target_key_version"] != self._target_key_version
            ):
                raise ValueError("rotation target does not match the existing run")
        return run_id

    def _is_completed(self, run_id: UUID) -> bool:
        with self._engine.connect() as connection:
            status = connection.execute(
                sa.select(CredentialReencryptionRun.status).where(
                    CredentialReencryptionRun.id == run_id
                )
            ).scalar_one()
        return status == CredentialReencryptionStatus.COMPLETED

    def _process_claimed_items(self, run_id: UUID) -> bool:
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    sa.select(CredentialReencryptionItem.__table__)
                    .where(
                        CredentialReencryptionItem.run_id == run_id,
                        sa.or_(
                            CredentialReencryptionItem.status
                            == CredentialReencryptionItemStatus.PENDING,
                            sa.and_(
                                CredentialReencryptionItem.status
                                == CredentialReencryptionItemStatus.RETRYABLE,
                                sa.or_(
                                    CredentialReencryptionItem.next_attempt_at.is_(
                                        None
                                    ),
                                    CredentialReencryptionItem.next_attempt_at
                                    <= sa.func.now(),
                                ),
                            ),
                        ),
                    )
                    .order_by(CredentialReencryptionItem.credential_id)
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            for item in rows:
                credential = (
                    connection.execute(
                        sa.select(Credential.__table__)
                        .where(Credential.id == item["credential_id"])
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                self._process_item(connection, run_id, item, credential)
        return bool(rows)

    def _scan_next_batch(self, run_id: UUID) -> bool:
        with self._engine.begin() as connection:
            run = (
                connection.execute(
                    sa.select(CredentialReencryptionRun.__table__)
                    .where(CredentialReencryptionRun.id == run_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            query = sa.select(Credential.__table__)
            if run["last_credential_id"] is not None:
                query = query.where(Credential.id > run["last_credential_id"])
            credentials = (
                connection.execute(
                    query.order_by(Credential.id)
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            for credential in credentials:
                connection.execute(
                    sa.insert(CredentialReencryptionItem).values(
                        run_id=run_id,
                        credential_id=credential["id"],
                        status=CredentialReencryptionItemStatus.PENDING,
                    )
                )
                item = {
                    "run_id": run_id,
                    "credential_id": credential["id"],
                    "status": CredentialReencryptionItemStatus.PENDING,
                    "attempt_count": 0,
                }
                self._process_item(connection, run_id, item, credential)
                connection.execute(
                    sa.update(CredentialReencryptionRun)
                    .where(CredentialReencryptionRun.id == run_id)
                    .values(
                        last_credential_id=credential["id"], updated_at=sa.func.now()
                    )
                )
        return bool(credentials)

    def _process_item(
        self,
        connection: sa.Connection,
        run_id: UUID,
        item: Mapping[str, Any],
        credential: Mapping[str, Any],
    ) -> None:
        attempt = item["attempt_count"] + 1
        first_attempt = item["attempt_count"] == 0
        connection.execute(
            sa.update(CredentialReencryptionItem)
            .where(
                CredentialReencryptionItem.run_id == run_id,
                CredentialReencryptionItem.credential_id == credential["id"],
            )
            .values(
                attempt_count=attempt,
                next_attempt_at=None,
                updated_at=sa.func.now(),
            )
        )
        if first_attempt:
            self._increment_run(connection, run_id, scanned_count=1)

        encrypted = EncryptedCredential(
            ciphertext=credential["ciphertext"],
            nonce=credential["nonce"],
            key_version=credential["key_version"],
            aad_version=credential["aad_version"],
            encryption_provider=_enum_value(credential["encryption_provider"]),
            key_reference=credential["key_reference"],
        )
        if (
            encrypted.key_version == self._target_key_version
            and encrypted.key_reference == self._target_key_reference
        ):
            self._finish_item(
                connection,
                run_id,
                credential["id"],
                CredentialReencryptionItemStatus.SKIPPED,
            )
            self._increment_run(connection, run_id, skipped_count=1)
            return

        try:
            updated = self._cipher.rewrap_json(
                encrypted,
                credential_id=credential["id"],
                owner_id=credential["owner_id"],
                provider=_enum_value(credential["provider"]),
                credential_kind=_enum_value(credential["credential_kind"]),
            )
            if (
                updated.key_version != self._target_key_version
                or updated.key_reference != self._target_key_reference
            ):
                raise CredentialEncryptionUnavailable(
                    "Credential encryption target is unavailable"
                )
            changed = connection.execute(
                sa.update(Credential)
                .where(
                    Credential.id == credential["id"],
                    Credential.key_version == credential["key_version"],
                    Credential.ciphertext == credential["ciphertext"],
                    Credential.key_reference == credential["key_reference"],
                )
                .values(
                    ciphertext=updated.ciphertext,
                    nonce=updated.nonce,
                    key_version=updated.key_version,
                    aad_version=updated.aad_version,
                    encryption_provider=updated.encryption_provider,
                    key_reference=updated.key_reference,
                    mutation_version=Credential.mutation_version + 1,
                    updated_at=sa.func.now(),
                )
            )
            status = (
                CredentialReencryptionItemStatus.REWRAPPED
                if changed.rowcount == 1
                else CredentialReencryptionItemStatus.SKIPPED
            )
            self._finish_item(connection, run_id, credential["id"], status)
            self._increment_run(
                connection,
                run_id,
                rewrapped_count=1
                if status == CredentialReencryptionItemStatus.REWRAPPED
                else 0,
                skipped_count=1
                if status == CredentialReencryptionItemStatus.SKIPPED
                else 0,
            )
        except (CredentialDecryptionError, CredentialEncryptionUnavailable, ValueError):
            retryable = attempt < self._max_attempts
            self._finish_item(
                connection,
                run_id,
                credential["id"],
                CredentialReencryptionItemStatus.RETRYABLE
                if retryable
                else CredentialReencryptionItemStatus.FAILED,
                next_attempt_at=(
                    datetime.now(UTC)
                    + timedelta(seconds=min(3600, 60 * (2 ** (attempt - 1))))
                    if retryable
                    else None
                ),
            )
            self._increment_run(
                connection,
                run_id,
                failed_count=0 if retryable else 1,
            )
            connection.execute(
                sa.update(CredentialReencryptionRun)
                .where(CredentialReencryptionRun.id == run_id)
                .values(last_error=_GENERIC_FAILURE, updated_at=sa.func.now())
            )

    @staticmethod
    def _finish_item(
        connection: sa.Connection,
        run_id: UUID,
        credential_id: UUID,
        status: CredentialReencryptionItemStatus,
        *,
        next_attempt_at: datetime | None = None,
    ) -> None:
        connection.execute(
            sa.update(CredentialReencryptionItem)
            .where(
                CredentialReencryptionItem.run_id == run_id,
                CredentialReencryptionItem.credential_id == credential_id,
            )
            .values(
                status=status,
                next_attempt_at=next_attempt_at,
                last_error=_GENERIC_FAILURE
                if status == CredentialReencryptionItemStatus.FAILED
                else None,
                updated_at=sa.func.now(),
            )
        )

    @staticmethod
    def _increment_run(
        connection: sa.Connection,
        run_id: UUID,
        *,
        scanned_count: int = 0,
        rewrapped_count: int = 0,
        skipped_count: int = 0,
        failed_count: int = 0,
    ) -> None:
        connection.execute(
            sa.update(CredentialReencryptionRun)
            .where(CredentialReencryptionRun.id == run_id)
            .values(
                scanned_count=CredentialReencryptionRun.scanned_count + scanned_count,
                rewrapped_count=CredentialReencryptionRun.rewrapped_count
                + rewrapped_count,
                skipped_count=CredentialReencryptionRun.skipped_count + skipped_count,
                failed_count=CredentialReencryptionRun.failed_count + failed_count,
                updated_at=sa.func.now(),
            )
        )


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _target_for_settings(
    settings: AuthSettings,
    cipher: CredentialCipher | VaultTransitCredentialCipher,
    requested_version: str | None,
) -> tuple[CredentialEncryptionProvider, str, str]:
    active_version = cipher.active_key_version
    target_version = requested_version or active_version
    if target_version != active_version:
        raise ValueError("target key version must be the configured active version")
    if settings.credential_encryption_provider == "vault":
        return (
            CredentialEncryptionProvider.VAULT,
            f"{settings.vault_transit_mount}/{settings.vault_transit_key}",
            target_version,
        )
    return CredentialEncryptionProvider.LOCAL, target_version, target_version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=UUID)
    parser.add_argument("--target-key-version")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args()

    settings = AuthSettings()
    cipher = credential_cipher_from_settings(settings, validate_authentication=False)
    provider, key_reference, key_version = _target_for_settings(
        settings, cipher, args.target_key_version
    )
    result = CredentialRotationJob(
        engine=get_maintenance_engine(),
        cipher=cipher,
        encryption_provider=provider,
        target_key_reference=key_reference,
        target_key_version=key_version,
        batch_size=args.batch_size,
        max_attempts=args.max_attempts,
    ).run(run_id=args.run_id)
    print(
        json.dumps(
            {
                "run_id": str(result.run_id),
                "status": result.status.value,
                "scanned_count": result.scanned_count,
                "rewrapped_count": result.rewrapped_count,
                "skipped_count": result.skipped_count,
                "failed_count": result.failed_count,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
