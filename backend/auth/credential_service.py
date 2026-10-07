"""Owner-scoped storage and use of encrypted provider credentials."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from auth.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    CredentialEncryptionUnavailable,
    EncryptedCredential,
    VaultTransitCredentialCipher,
)
from auth.errors import AuthorizationDenied
from auth.uuids import uuid7
from db.models import (
    Credential,
    CredentialEncryptionProvider,
    CredentialKind,
    CredentialProvider,
)
from db.rls import principal_transaction

logger = logging.getLogger("trace.credentials")

CredentialCipherProtocol = CredentialCipher | VaultTransitCredentialCipher


class CredentialServiceError(RuntimeError):
    """Base class for safe credential-service failures."""


class CredentialNotFound(CredentialServiceError):
    """Raised without disclosing whether another owner's credential exists."""


class CredentialConflict(CredentialServiceError):
    """Raised when an owner already has an active credential of the same type."""


class CredentialPayloadError(ValueError):
    """Raised when a credential payload is not a bounded JSON object."""


@dataclass(frozen=True)
class CredentialMetadata:
    id: UUID
    owner_id: UUID
    provider: CredentialProvider
    kind: CredentialKind
    encryption_provider: CredentialEncryptionProvider
    key_version: str
    aad_version: str
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


class CredentialCipherFactory(Protocol):
    def __call__(self) -> CredentialCipherProtocol: ...


class CredentialService:
    """The only application boundary allowed to persist or decrypt credentials."""

    def __init__(
        self,
        *,
        engine: Engine,
        cipher: CredentialCipherProtocol | CredentialCipherFactory,
    ) -> None:
        self._engine = engine
        self._cipher = cipher

    def _get_cipher(self) -> CredentialCipherProtocol:
        return self._cipher() if callable(self._cipher) else self._cipher

    def create_or_replace(
        self,
        *,
        owner_id: UUID,
        provider: CredentialProvider,
        kind: CredentialKind,
        payload: dict[str, object],
    ) -> CredentialMetadata:
        _validate_payload(payload)
        cipher = self._get_cipher()
        with principal_transaction(self._engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.select(Credential)
                    .where(
                        Credential.owner_id == owner_id,
                        Credential.provider == provider,
                        Credential.credential_kind == kind,
                        Credential.revoked_at.is_(None),
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            credential_id = row["id"] if row is not None else uuid7()
            encrypted = _encrypt(
                cipher,
                payload,
                credential_id=credential_id,
                owner_id=owner_id,
                provider=provider,
                kind=kind,
            )
            values = _encrypted_values(encrypted)
            if row is None:
                connection.execute(
                    sa.insert(Credential).values(
                        id=credential_id,
                        owner_id=owner_id,
                        provider=provider,
                        credential_kind=kind,
                        **values,
                    )
                )
            else:
                connection.execute(
                    sa.update(Credential)
                    .where(
                        Credential.id == credential_id,
                        Credential.owner_id == owner_id,
                        Credential.provider == provider,
                        Credential.credential_kind == kind,
                        Credential.revoked_at.is_(None),
                    )
                    .values(**values, updated_at=sa.func.now())
                )
            refreshed = (
                connection.execute(
                    sa.select(Credential).where(
                        Credential.id == credential_id,
                        Credential.owner_id == owner_id,
                    )
                )
                .mappings()
                .one()
            )
        return _metadata(refreshed)

    def metadata(self, *, owner_id: UUID, credential_id: UUID) -> CredentialMetadata:
        row = self._owned_row(owner_id=owner_id, credential_id=credential_id)
        return _metadata(row)

    def replace_payload(
        self,
        *,
        owner_id: UUID,
        credential_id: UUID,
        payload: dict[str, object],
    ) -> CredentialMetadata:
        _validate_payload(payload)
        cipher = self._get_cipher()
        with principal_transaction(self._engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.select(Credential)
                    .where(
                        Credential.id == credential_id,
                        Credential.owner_id == owner_id,
                        Credential.revoked_at.is_(None),
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                _raise_credential_access_error(connection, credential_id)
            encrypted = _encrypt(
                cipher,
                payload,
                credential_id=row["id"],
                owner_id=row["owner_id"],
                provider=_provider_enum(row["provider"]),
                kind=_kind_enum(row["credential_kind"]),
            )
            connection.execute(
                sa.update(Credential)
                .where(
                    Credential.id == credential_id,
                    Credential.owner_id == owner_id,
                    Credential.revoked_at.is_(None),
                )
                .values(**_encrypted_values(encrypted), updated_at=sa.func.now())
            )
            refreshed = (
                connection.execute(
                    sa.select(Credential).where(
                        Credential.id == credential_id,
                        Credential.owner_id == owner_id,
                    )
                )
                .mappings()
                .one()
            )
        return _metadata(refreshed)

    def decrypt_for_provider_call(
        self, *, owner_id: UUID, credential_id: UUID
    ) -> dict[str, object]:
        row = self._owned_row(owner_id=owner_id, credential_id=credential_id)
        encrypted = _encrypted_credential(row)
        cipher = self._get_cipher()
        encrypted = self._repair_stale_ciphertext(
            cipher=cipher,
            row=row,
            encrypted=encrypted,
            owner_id=owner_id,
        )
        try:
            return cipher.decrypt_json(
                encrypted,
                credential_id=row["id"],
                owner_id=row["owner_id"],
                provider=row["provider"].value
                if isinstance(row["provider"], CredentialProvider)
                else str(row["provider"]),
                credential_kind=row["credential_kind"].value
                if isinstance(row["credential_kind"], CredentialKind)
                else str(row["credential_kind"]),
            )
        except (CredentialDecryptionError, CredentialEncryptionUnavailable) as error:
            raise CredentialServiceError("Credential is unavailable") from error

    def _repair_stale_ciphertext(
        self,
        *,
        cipher: CredentialCipherProtocol,
        row: sa.RowMapping,
        encrypted: EncryptedCredential,
        owner_id: UUID,
    ) -> EncryptedCredential:
        try:
            if encrypted.key_version == cipher.active_key_version:
                return encrypted
            updated = cipher.rewrap_json(
                encrypted,
                credential_id=row["id"],
                owner_id=owner_id,
                provider=_enum_value(row["provider"]),
                credential_kind=_enum_value(row["credential_kind"]),
            )
            with principal_transaction(self._engine, owner_id) as connection:
                result = connection.execute(
                    sa.update(Credential)
                    .where(
                        Credential.id == row["id"],
                        Credential.owner_id == owner_id,
                        Credential.key_version == encrypted.key_version,
                        Credential.ciphertext == encrypted.ciphertext,
                        Credential.revoked_at.is_(None),
                    )
                    .values(**_encrypted_values(updated), updated_at=sa.func.now())
                )
            return updated if result.rowcount == 1 else encrypted
        except (CredentialDecryptionError, CredentialEncryptionUnavailable):
            # Read repair is best effort while the old key remains usable. The
            # provider call below still determines whether the old key is valid.
            logger.warning(
                "credential_read_rewrap_unavailable",
                extra={"credential_key_version": encrypted.key_version},
            )
            return encrypted

    def rewrap(self, *, owner_id: UUID, credential_id: UUID) -> CredentialMetadata:
        row = self._owned_row(owner_id=owner_id, credential_id=credential_id)
        encrypted = _encrypted_credential(row)
        provider = _enum_value(row["provider"])
        kind = _enum_value(row["credential_kind"])
        cipher = self._get_cipher()
        try:
            updated = cipher.rewrap_json(
                encrypted,
                credential_id=row["id"],
                owner_id=row["owner_id"],
                provider=provider,
                credential_kind=kind,
            )
        except (CredentialDecryptionError, CredentialEncryptionUnavailable) as error:
            raise CredentialServiceError("Credential is unavailable") from error
        with principal_transaction(self._engine, owner_id) as connection:
            connection.execute(
                sa.update(Credential)
                .where(
                    Credential.id == credential_id,
                    Credential.owner_id == owner_id,
                    Credential.revoked_at.is_(None),
                )
                .values(**_encrypted_values(updated), updated_at=sa.func.now())
            )
            refreshed = (
                connection.execute(
                    sa.select(Credential).where(
                        Credential.id == credential_id,
                        Credential.owner_id == owner_id,
                    )
                )
                .mappings()
                .one()
            )
        return _metadata(refreshed)

    def revoke(self, *, owner_id: UUID, credential_id: UUID) -> None:
        with principal_transaction(self._engine, owner_id) as connection:
            result = connection.execute(
                sa.update(Credential)
                .where(
                    Credential.id == credential_id,
                    Credential.owner_id == owner_id,
                    Credential.revoked_at.is_(None),
                )
                .values(revoked_at=sa.func.now(), updated_at=sa.func.now())
            )
        if result.rowcount != 1:
            with self._engine.connect() as connection:
                _raise_credential_access_error(connection, credential_id)

    def _owned_row(self, *, owner_id: UUID, credential_id: UUID) -> sa.RowMapping:
        with principal_transaction(self._engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.select(Credential).where(
                        Credential.id == credential_id,
                        Credential.owner_id == owner_id,
                        Credential.revoked_at.is_(None),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                _raise_credential_access_error(connection, credential_id)
        return row


def _raise_credential_access_error(
    connection: sa.Connection, credential_id: UUID
) -> NoReturn:
    exists = connection.execute(
        sa.text("SELECT public.trace_credential_exists(:credential_id)"),
        {"credential_id": credential_id},
    ).scalar_one()
    if bool(exists):
        raise AuthorizationDenied()
    raise CredentialNotFound("Credential is unavailable")


def _validate_payload(payload: dict[str, object]) -> None:
    if not isinstance(payload, dict) or not payload:
        raise CredentialPayloadError("Credential payload is invalid")
    try:
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as error:
        raise CredentialPayloadError("Credential payload is invalid") from error
    if len(encoded.encode("utf-8")) > 64 * 1024:
        raise CredentialPayloadError("Credential payload is invalid")


def _encrypt(
    cipher: CredentialCipherProtocol,
    payload: dict[str, object],
    *,
    credential_id: UUID,
    owner_id: UUID,
    provider: CredentialProvider,
    kind: CredentialKind,
) -> EncryptedCredential:
    try:
        return cipher.encrypt_json(
            payload,
            credential_id=credential_id,
            owner_id=owner_id,
            provider=provider.value,
            credential_kind=kind.value,
        )
    except CredentialEncryptionUnavailable as error:
        raise CredentialServiceError("Credential encryption is unavailable") from error


def _encrypted_values(encrypted: EncryptedCredential) -> dict[str, object]:
    return {
        "ciphertext": encrypted.ciphertext,
        "nonce": encrypted.nonce,
        "key_version": encrypted.key_version,
        "aad_version": encrypted.aad_version,
        "encryption_provider": encrypted.encryption_provider,
        "key_reference": encrypted.key_reference,
    }


def _encrypted_credential(row: sa.RowMapping) -> EncryptedCredential:
    return EncryptedCredential(
        ciphertext=row["ciphertext"],
        nonce=row["nonce"],
        key_version=row["key_version"],
        aad_version=row["aad_version"],
        encryption_provider=_enum_value(row["encryption_provider"]),
        key_reference=row["key_reference"],
    )


def _metadata(row: sa.RowMapping) -> CredentialMetadata:
    return CredentialMetadata(
        id=row["id"],
        owner_id=row["owner_id"],
        provider=row["provider"],
        kind=row["credential_kind"],
        encryption_provider=row["encryption_provider"],
        key_version=row["key_version"],
        aad_version=row["aad_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revoked_at=row["revoked_at"],
    )


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _provider_enum(value: object) -> CredentialProvider:
    return (
        value
        if isinstance(value, CredentialProvider)
        else CredentialProvider(str(value))
    )


def _kind_enum(value: object) -> CredentialKind:
    return value if isinstance(value, CredentialKind) else CredentialKind(str(value))
