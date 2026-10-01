from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class IdentityProvider(str, Enum):
    GITHUB = "github"
    GOOGLE = "google"
    EMAIL = "email"


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"


class ProjectSourceType(str, Enum):
    GITHUB = "github"
    LOCAL = "local"


class CredentialProvider(str, Enum):
    GITHUB = "github"
    GOOGLE = "google"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class CredentialKind(str, Enum):
    OAUTH = "oauth"
    API_KEY = "api_key"


class CredentialEncryptionProvider(str, Enum):
    LOCAL = "local"
    VAULT = "vault"


def native_enum(enum_class: type[Enum], name: str, schema: str) -> sa.Enum:
    return sa.Enum(
        enum_class,
        name=name,
        schema=schema,
        native_enum=True,
        values_callable=lambda enum_type: [member.value for member in enum_type],
    )


class AuthUser(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa.text("public.uuidv7()")
    )
    email: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        native_enum(UserStatus, "user_status", "auth"),
        nullable=False,
        server_default=sa.text("'active'::auth.user_status"),
    )
    email_confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class AuthIdentity(Base):
    __tablename__ = "identities"
    __table_args__ = (
        sa.UniqueConstraint("provider", "provider_subject", name="auth_identities_provider_subject_key"),
        {"schema": "auth"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa.text("public.uuidv7()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), sa.ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[IdentityProvider] = mapped_column(
        native_enum(IdentityProvider, "identity_provider", "auth"), nullable=False
    )
    provider_subject: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    provider_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )


class PasswordCredential(Base):
    __tablename__ = "password_credentials"
    __table_args__ = {"schema": "auth"}

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    password_hash: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    failed_attempt_count: Mapped[int] = mapped_column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class AuthSession(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "auth"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa.text("public.uuidv7()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), sa.ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": "auth"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa.text("public.uuidv7()")
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"
    __table_args__ = {"schema": "auth"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa.text("public.uuidv7()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), sa.ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )


class PasswordRecoveryToken(Base):
    __tablename__ = "password_recovery_tokens"
    __table_args__ = {"schema": "auth"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa.text("public.uuidv7()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), sa.ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        sa.CheckConstraint(
            "(source_type = 'github' AND github_repository_id IS NOT NULL AND local_path_hash IS NULL) "
            "OR (source_type = 'local' AND local_path_hash IS NOT NULL AND github_repository_id IS NULL)",
            name="projects_source_reference_check",
        ),
        {"schema": "public"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa.text("public.uuidv7()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), sa.ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_type: Mapped[ProjectSourceType] = mapped_column(
        native_enum(ProjectSourceType, "project_source_type", "public"), nullable=False
    )
    github_repository_id: Mapped[int | None] = mapped_column(sa.BigInteger(), nullable=True)
    local_path_hash: Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True)
    source_hash: Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True)
    current_revision: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    archived_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = {"schema": "private"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa.text("public.uuidv7()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), sa.ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[CredentialProvider] = mapped_column(
        native_enum(CredentialProvider, "credential_provider", "private"), nullable=False
    )
    credential_kind: Mapped[CredentialKind] = mapped_column(
        native_enum(CredentialKind, "credential_kind", "private"), nullable=False
    )
    ciphertext: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
    nonce: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
    key_version: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    aad_version: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    encryption_provider: Mapped[CredentialEncryptionProvider] = mapped_column(
        native_enum(CredentialEncryptionProvider, "credential_encryption_provider", "private"),
        nullable=False,
    )
    key_reference: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


sa.Index(
    "auth_users_email_lower_key",
    sa.func.lower(AuthUser.email),
    unique=True,
    postgresql_where=AuthUser.email.is_not(None),
)
sa.Index("auth_identities_user_created_idx", AuthIdentity.user_id, AuthIdentity.created_at.desc())
sa.Index("auth_sessions_user_expires_idx", AuthSession.user_id, AuthSession.expires_at.desc())
sa.Index(
    "auth_sessions_active_user_expires_idx",
    AuthSession.user_id,
    AuthSession.expires_at.desc(),
    postgresql_where=AuthSession.revoked_at.is_(None),
)
sa.Index("auth_refresh_tokens_session_expires_idx", RefreshToken.session_id, RefreshToken.expires_at.desc())
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
sa.Index("projects_owner_created_idx", Project.owner_id, Project.created_at.desc())
sa.Index(
    "projects_owner_github_repository_key",
    Project.owner_id,
    Project.github_repository_id,
    unique=True,
    postgresql_where=sa.text("source_type = 'github' AND archived_at IS NULL"),
)
sa.Index(
    "projects_owner_local_path_key",
    Project.owner_id,
    Project.local_path_hash,
    unique=True,
    postgresql_where=sa.text("source_type = 'local' AND archived_at IS NULL"),
)
sa.Index(
    "credentials_active_owner_provider_kind_key",
    Credential.owner_id,
    Credential.provider,
    Credential.credential_kind,
    unique=True,
    postgresql_where=Credential.revoked_at.is_(None),
)
