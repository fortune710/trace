"""Authentication and email-delivery database models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import CredentialEncryptionProvider, native_enum


class IdentityProvider(str, Enum):
    GITHUB = "github"
    GOOGLE = "google"
    EMAIL = "email"


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"


class EmailDeliveryKind(str, Enum):
    VERIFICATION = "verification"
    PASSWORD_RECOVERY = "password_recovery"


class EmailDeliveryStatus(str, Enum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class AuthUser(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    email: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        native_enum(UserStatus, "user_status", "auth"),
        nullable=False,
        server_default=sa.text("'active'::auth.user_status"),
    )
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class AuthIdentity(Base):
    __tablename__ = "identities"
    __table_args__ = (
        sa.UniqueConstraint(
            "provider", "provider_subject", name="auth_identities_provider_subject_key"
        ),
        {"schema": "auth"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[IdentityProvider] = mapped_column(
        native_enum(IdentityProvider, "identity_provider", "auth"), nullable=False
    )
    provider_subject: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    provider_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
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


class PasswordCredential(Base):
    __tablename__ = "password_credentials"
    __table_args__ = {"schema": "auth"}  # noqa: RUF012

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    password_hash: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    failed_attempt_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class AuthSession(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "auth"}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": "auth"}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(
        sa.LargeBinary(), nullable=False, unique=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"
    __table_args__ = {"schema": "auth"}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(
        sa.LargeBinary(), nullable=False, unique=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class PasswordRecoveryToken(Base):
    __tablename__ = "password_recovery_tokens"
    __table_args__ = {"schema": "auth"}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(
        sa.LargeBinary(), nullable=False, unique=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class EmailDeliveryJob(Base):
    __tablename__ = "email_delivery_jobs"
    __table_args__ = {"schema": "auth"}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[EmailDeliveryKind] = mapped_column(
        native_enum(EmailDeliveryKind, "email_delivery_kind", "auth"), nullable=False
    )
    status: Mapped[EmailDeliveryStatus] = mapped_column(
        native_enum(EmailDeliveryStatus, "email_delivery_status", "auth"),
        nullable=False,
        server_default=sa.text("'pending'::auth.email_delivery_status"),
    )
    payload_ciphertext: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
    payload_nonce: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
    payload_key_version: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    payload_aad_version: Mapped[str] = mapped_column(
        sa.Text(), nullable=False, server_default=sa.text("'v1'")
    )
    payload_encryption_provider: Mapped[CredentialEncryptionProvider] = mapped_column(
        native_enum(
            CredentialEncryptionProvider, "email_payload_encryption_provider", "auth"
        ),
        nullable=False,
    )
    payload_key_reference: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    published_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
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


sa.Index(
    "auth_users_email_lower_key",
    sa.func.lower(AuthUser.email),
    unique=True,
    postgresql_where=AuthUser.email.is_not(None),
)
sa.Index(
    "auth_email_delivery_jobs_pending_created_idx",
    EmailDeliveryJob.status,
    EmailDeliveryJob.created_at,
    postgresql_where=EmailDeliveryJob.status == EmailDeliveryStatus.PENDING,
)
sa.Index(
    "auth_identities_user_created_idx",
    AuthIdentity.user_id,
    AuthIdentity.created_at.desc(),
)
sa.Index(
    "auth_sessions_user_expires_idx", AuthSession.user_id, AuthSession.expires_at.desc()
)
sa.Index(
    "auth_sessions_active_user_expires_idx",
    AuthSession.user_id,
    AuthSession.expires_at.desc(),
    postgresql_where=AuthSession.revoked_at.is_(None),
)
sa.Index(
    "auth_refresh_tokens_session_expires_idx",
    RefreshToken.session_id,
    RefreshToken.expires_at.desc(),
)
sa.Index(
    "auth_refresh_tokens_active_session_expires_idx",
    RefreshToken.session_id,
    RefreshToken.expires_at.desc(),
    postgresql_where=RefreshToken.revoked_at.is_(None),
)
sa.Index(
    "auth_email_verification_tokens_active_user_expires_idx",
    EmailVerificationToken.user_id,
    EmailVerificationToken.expires_at.desc(),
    postgresql_where=EmailVerificationToken.used_at.is_(None),
)
sa.Index(
    "auth_password_recovery_tokens_active_user_expires_idx",
    PasswordRecoveryToken.user_id,
    PasswordRecoveryToken.expires_at.desc(),
    postgresql_where=PasswordRecoveryToken.used_at.is_(None),
)


__all__ = [
    "AuthIdentity",
    "AuthSession",
    "AuthUser",
    "EmailDeliveryJob",
    "EmailDeliveryKind",
    "EmailDeliveryStatus",
    "EmailVerificationToken",
    "IdentityProvider",
    "PasswordCredential",
    "PasswordRecoveryToken",
    "RefreshToken",
    "UserStatus",
]
