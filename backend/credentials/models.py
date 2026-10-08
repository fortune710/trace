"""Credential and credential re-encryption database models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import CredentialEncryptionProvider, native_enum


class CredentialProvider(str, Enum):
    GITHUB = "github"
    GOOGLE = "google"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class CredentialKind(str, Enum):
    OAUTH = "oauth"
    API_KEY = "api_key"


class CredentialReencryptionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CredentialReencryptionItemStatus(str, Enum):
    PENDING = "pending"
    REWRAPPED = "rewrapped"
    SKIPPED = "skipped"
    RETRYABLE = "retryable"
    FAILED = "failed"


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="credentials_owner_id_id_key"),
        {"schema": "private"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[CredentialProvider] = mapped_column(
        native_enum(CredentialProvider, "credential_provider", "private"),
        nullable=False,
    )
    credential_kind: Mapped[CredentialKind] = mapped_column(
        native_enum(CredentialKind, "credential_kind", "private"), nullable=False
    )
    ciphertext: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
    nonce: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
    key_version: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    aad_version: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    encryption_provider: Mapped[CredentialEncryptionProvider] = mapped_column(
        native_enum(
            CredentialEncryptionProvider, "credential_encryption_provider", "private"
        ),
        nullable=False,
    )
    key_reference: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    mutation_version: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class CredentialReencryptionRun(Base):
    __tablename__ = "credential_reencryption_runs"
    __table_args__ = {"schema": "private"}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    status: Mapped[CredentialReencryptionStatus] = mapped_column(
        native_enum(
            CredentialReencryptionStatus, "credential_reencryption_status", "private"
        ),
        nullable=False,
        server_default=sa.text("'running'::private.credential_reencryption_status"),
    )
    encryption_provider: Mapped[CredentialEncryptionProvider] = mapped_column(
        native_enum(
            CredentialEncryptionProvider, "credential_encryption_provider", "private"
        ),
        nullable=False,
    )
    target_key_reference: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    target_key_version: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    last_credential_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    scanned_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    rewrapped_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    skipped_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    failed_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    last_error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class CredentialReencryptionItem(Base):
    __tablename__ = "credential_reencryption_items"
    __table_args__ = (
        sa.Index(
            "credential_reencryption_items_retry_idx",
            "run_id",
            "status",
            "next_attempt_at",
        ),
        {"schema": "private"},
    )

    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("private.credential_reencryption_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    credential_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("private.credentials.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[CredentialReencryptionItemStatus] = mapped_column(
        native_enum(
            CredentialReencryptionItemStatus,
            "credential_reencryption_item_status",
            "private",
        ),
        nullable=False,
        server_default=sa.text(
            "'pending'::private.credential_reencryption_item_status"
        ),
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    last_error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


sa.Index(
    "credentials_active_owner_provider_kind_key",
    Credential.owner_id,
    Credential.provider,
    Credential.credential_kind,
    unique=True,
    postgresql_where=Credential.revoked_at.is_(None),
)


__all__ = [
    "Credential",
    "CredentialEncryptionProvider",
    "CredentialKind",
    "CredentialProvider",
    "CredentialReencryptionItem",
    "CredentialReencryptionItemStatus",
    "CredentialReencryptionRun",
    "CredentialReencryptionStatus",
]
