"""Exact encrypted patch persistence, separate from redacted display previews."""

from __future__ import annotations

import hashlib
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agents.execution.diagnostics import PatchGenerationError
from agents.execution.patches import GeneratedPatch
from agents.execution.redaction import redact_text
from auth.config import AuthSettings
from auth.credentials import EncryptedCredential, credential_cipher_from_settings
from auth.errors import ResourceConflict, ResourceUnavailable
from auth.uuids import uuid7
from db.rls import principal_transaction
from remediations.models import Remediation
from remediations.patch_models import generation_attempts, patch_artifacts


class PatchStore:
    def __init__(self, engine, cipher=None):
        self.engine = engine
        self._cipher = cipher

    @property
    def cipher(self):
        if callable(self._cipher):
            self._cipher = self._cipher()
        if self._cipher is None:
            self._cipher = credential_cipher_from_settings(
                AuthSettings(), validate_authentication=False
            )
        return self._cipher

    def start(self, *, owner_id: UUID, remediation_id: UUID):
        with principal_transaction(self.engine, owner_id) as connection:
            connection.execute(
                sa.update(Remediation)
                .where(
                    Remediation.owner_id == owner_id,
                    Remediation.id == remediation_id,
                    Remediation.generation_status == "pending",
                )
                .values(generation_status="running")
            )

    def record_submission(
        self,
        *,
        owner_id,
        remediation_id,
        review_attempt_id,
        submission_number,
        diagnostic,
        elapsed_ms,
        source_read_count,
        model_call_count,
    ):
        with principal_transaction(self.engine, owner_id) as connection:
            connection.execute(
                pg_insert(generation_attempts)
                .values(
                    owner_id=owner_id,
                    remediation_id=remediation_id,
                    review_attempt_id=review_attempt_id,
                    submission_number=submission_number,
                    outcome="failed" if diagnostic else "valid",
                    diagnostics_json=diagnostic,
                    elapsed_ms=elapsed_ms,
                    source_read_count=source_read_count,
                    model_call_count=model_call_count,
                )
                .on_conflict_do_nothing(constraint="generation_attempt_submission_key")
            )

    def fail(self, *, owner_id, remediation_id, diagnostic):
        with principal_transaction(self.engine, owner_id) as connection:
            connection.execute(
                sa.update(Remediation)
                .where(
                    Remediation.owner_id == owner_id,
                    Remediation.id == remediation_id,
                    Remediation.generation_status != "ready",
                )
                .values(generation_status="failed", generation_failure=diagnostic)
            )

    def save(self, *, owner_id: UUID, remediation_id: UUID, patch: GeneratedPatch):
        artifact_id = uuid7()
        try:
            encrypted = self.cipher.encrypt_json(
                patch.model_dump(mode="json"),
                credential_id=artifact_id,
                owner_id=owner_id,
                provider="trace",
                credential_kind="remediation_patch",
            )
        except Exception as exc:
            raise PatchGenerationError(
                "patch_encryption_unavailable", stage="storage", retryable=False
            ) from exc
        with principal_transaction(self.engine, owner_id) as connection:
            row = connection.execute(
                sa.select(Remediation.generation_status)
                .where(
                    Remediation.owner_id == owner_id, Remediation.id == remediation_id
                )
                .with_for_update()
            ).one()
            if row.generation_status == "ready":
                return
            connection.execute(
                sa.insert(patch_artifacts).values(
                    id=artifact_id,
                    owner_id=owner_id,
                    remediation_id=remediation_id,
                    source_snapshot=patch.source_snapshot,
                    ciphertext=encrypted.ciphertext,
                    nonce=encrypted.nonce,
                    key_version=encrypted.key_version,
                    aad_version=encrypted.aad_version,
                    encryption_provider=encrypted.encryption_provider,
                    key_reference=encrypted.key_reference,
                    sha256=patch.sha256,
                )
            )
            connection.execute(
                sa.update(Remediation)
                .where(
                    Remediation.owner_id == owner_id, Remediation.id == remediation_id
                )
                .values(
                    generation_status="ready",
                    generation_failure=None,
                    patch_artifact_id=artifact_id,
                    proposed_diff=redact_text(patch.diff),
                    validated_at=sa.func.now(),
                )
            )

    def load(self, *, owner_id: UUID, remediation_id: UUID) -> GeneratedPatch:
        patch = self.load_if_ready(owner_id=owner_id, remediation_id=remediation_id)
        if patch is None:
            raise ResourceConflict("remediation_patch_unavailable")
        return patch

    def load_if_ready(
        self, *, owner_id: UUID, remediation_id: UUID
    ) -> GeneratedPatch | None:
        """Return the verified artifact, or None when no ready artifact exists.

        This decrypts through the key provider and may record an integrity failure
        on the remediation, so callers must not hold a lock on that row.
        """
        with principal_transaction(self.engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.select(patch_artifacts)
                    .join(
                        Remediation,
                        sa.and_(
                            Remediation.owner_id == patch_artifacts.c.owner_id,
                            Remediation.patch_artifact_id == patch_artifacts.c.id,
                            Remediation.id == patch_artifacts.c.remediation_id,
                        ),
                    )
                    .where(
                        patch_artifacts.c.owner_id == owner_id,
                        Remediation.id == remediation_id,
                        Remediation.generation_status == "ready",
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        try:
            payload = self.cipher.decrypt_json(
                EncryptedCredential(
                    ciphertext=row["ciphertext"],
                    nonce=row["nonce"],
                    key_version=row["key_version"],
                    aad_version=row["aad_version"],
                    encryption_provider=row["encryption_provider"],
                    key_reference=row["key_reference"],
                ),
                credential_id=row["id"],
                owner_id=owner_id,
                provider="trace",
                credential_kind="remediation_patch",
            )
        except Exception as exc:
            # A cipher or key-provider failure says nothing about the stored
            # artifact, so it must not permanently mark the patch unusable.
            raise ResourceUnavailable() from exc
        try:
            patch = GeneratedPatch.model_validate(payload)
            if (
                hashlib.sha256(patch.diff.encode()).hexdigest() != row["sha256"]
                or patch.sha256 != row["sha256"]
                or patch.source_snapshot != row["source_snapshot"]
            ):
                raise ValueError("artifact_integrity")
        except ValueError as exc:
            # Only a decrypted payload that fails validation proves an integrity
            # mismatch worth recording.
            with principal_transaction(self.engine, owner_id) as connection:
                connection.execute(
                    sa.update(Remediation)
                    .where(
                        Remediation.owner_id == owner_id,
                        Remediation.id == remediation_id,
                    )
                    .values(
                        generation_failure={
                            "code": "patch_decryption_or_integrity_failed",
                            "message": "The executable patch could not be verified.",
                        }
                    )
                )
            raise ResourceConflict("remediation_patch_integrity_failed") from exc
        return patch
