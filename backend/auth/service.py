"""Transactional email/password account and browser-session operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import Engine

from auth.config import AuthSettings
from auth.credentials import (
    CredentialCipher,
    CredentialEncryptionUnavailable,
    VaultTransitCredentialCipher,
    email_payload_cipher_from_settings,
)
from auth.email_delivery import EmailJobDispatcher, EmailJobStore
from auth.passwords import hash_password, password_needs_rehash, verify_password
from auth.queueing import RabbitMQEmailPublisher
from auth.tokens import (
    AccessTokenClaims,
    JWTService,
    TokenPurpose,
    decode_base64url_key,
    digest_opaque_token,
    generate_opaque_token,
    jwt_service_from_settings,
)
from auth.uuids import uuid7
from db.models import (
    AuthIdentity,
    AuthSession,
    AuthUser,
    EmailDeliveryKind,
    EmailVerificationToken,
    IdentityProvider,
    PasswordCredential,
    PasswordRecoveryToken,
    RefreshToken,
    User,
    UserStatus,
)


class AuthenticationUnavailable(RuntimeError):
    """Raised when a required local dependency cannot safely complete auth."""


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    session_id: UUID


@dataclass(frozen=True)
class LoginResult:
    outcome: Literal["authenticated", "rejected"]
    tokens: SessionTokens | None = None


class AuthService:
    def __init__(
        self,
        *,
        engine: Engine,
        settings: AuthSettings,
        jwt_service: JWTService,
        token_hash_key: bytes,
        email_cipher: CredentialCipher | VaultTransitCredentialCipher,
        dispatcher: EmailJobDispatcher | None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._jwt = jwt_service
        self._token_hash_key = token_hash_key
        self._email_cipher = email_cipher
        self._jobs = EmailJobStore(engine)
        self._dispatcher = dispatcher

    @classmethod
    def from_settings(cls, *, engine: Engine, settings: AuthSettings) -> AuthService:
        settings.validate_for_authentication()
        assert settings.token_hash_key is not None
        dispatcher = None
        if settings.rabbitmq_url:
            publisher = RabbitMQEmailPublisher(
                url=settings.rabbitmq_url,
                retry_delays_seconds=settings.email_retry_delays_seconds,
            )
            dispatcher = EmailJobDispatcher(EmailJobStore(engine), publisher)
        return cls(
            engine=engine,
            settings=settings,
            jwt_service=jwt_service_from_settings(settings),
            token_hash_key=decode_base64url_key(
                settings.token_hash_key.get_secret_value(), name="AUTH_TOKEN_HASH_KEY"
            ),
            email_cipher=email_payload_cipher_from_settings(settings),
            dispatcher=dispatcher,
        )

    def register(
        self, *, email: str, password: str, display_name: str | None, destination: str
    ) -> None:
        normalized_email = _normalize_email(email)
        user_id = uuid7()
        token = generate_opaque_token()
        job_id: UUID | None = None
        try:
            with self._engine.begin() as connection:
                inserted = connection.execute(
                    postgres_insert(AuthUser)
                    .values(
                        id=user_id, email=normalized_email, status=UserStatus.ACTIVE
                    )
                    .on_conflict_do_nothing(
                        index_elements=[sa.func.lower(AuthUser.email)],
                        index_where=AuthUser.email.is_not(None),
                    )
                    .returning(AuthUser.id)
                ).scalar_one_or_none()
                if inserted is None:
                    return
                connection.execute(
                    sa.insert(User).values(id=user_id, display_name=display_name)
                )
                connection.execute(
                    sa.insert(AuthIdentity).values(
                        id=uuid7(),
                        user_id=user_id,
                        provider=IdentityProvider.EMAIL,
                        provider_subject=normalized_email,
                    )
                )
                connection.execute(
                    sa.insert(PasswordCredential).values(
                        user_id=user_id, password_hash=hash_password(password)
                    )
                )
                connection.execute(
                    sa.insert(EmailVerificationToken).values(
                        id=uuid7(),
                        user_id=user_id,
                        token_hash=self._digest(token, TokenPurpose.EMAIL_VERIFICATION),
                        expires_at=_now()
                        + timedelta(hours=self._settings.email_verification_hours),
                    )
                )
                job_id = self._jobs.create(
                    connection,
                    user_id=user_id,
                    kind=EmailDeliveryKind.VERIFICATION,
                    payload={
                        "email": normalized_email,
                        "token": token,
                        "destination": destination,
                    },
                    cipher=self._email_cipher,
                )
        except (sa.exc.SQLAlchemyError, CredentialEncryptionUnavailable) as error:
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error
        self._dispatch(job_id)

    def verify_email(self, *, token: str) -> bool:
        try:
            with self._engine.begin() as connection:
                token_row = (
                    connection.execute(
                        sa.select(EmailVerificationToken)
                        .where(
                            EmailVerificationToken.token_hash
                            == self._digest(token, TokenPurpose.EMAIL_VERIFICATION),
                            EmailVerificationToken.used_at.is_(None),
                            EmailVerificationToken.expires_at > _now(),
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if token_row is None:
                    return False
                connection.execute(
                    sa.update(EmailVerificationToken)
                    .where(
                        EmailVerificationToken.id == token_row["id"],
                        EmailVerificationToken.used_at.is_(None),
                    )
                    .values(used_at=sa.func.now())
                )
                connection.execute(
                    sa.update(AuthUser)
                    .where(
                        AuthUser.id == token_row["user_id"],
                        AuthUser.email_confirmed_at.is_(None),
                    )
                    .values(email_confirmed_at=sa.func.now(), updated_at=sa.func.now())
                )
                return True
        except (ValueError, sa.exc.SQLAlchemyError) as error:
            if isinstance(error, ValueError):
                return False
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error

    def login(self, *, email: str, password: str) -> LoginResult:
        try:
            normalized_email = _normalize_email(email)
        except ValueError:
            return LoginResult("rejected")
        try:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        sa.select(
                            AuthUser.id,
                            AuthUser.status,
                            AuthUser.email_confirmed_at,
                            PasswordCredential.password_hash,
                        )
                        .join(
                            PasswordCredential,
                            PasswordCredential.user_id == AuthUser.id,
                        )
                        .where(sa.func.lower(AuthUser.email) == normalized_email)
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    row is None
                    or row["status"] != UserStatus.ACTIVE
                    or row["email_confirmed_at"] is None
                    or not verify_password(row["password_hash"], password)
                ):
                    return LoginResult("rejected")
                if password_needs_rehash(row["password_hash"]):
                    connection.execute(
                        sa.update(PasswordCredential)
                        .where(PasswordCredential.user_id == row["id"])
                        .values(
                            password_hash=hash_password(password),
                            password_changed_at=sa.func.now(),
                        )
                    )
                return LoginResult(
                    "authenticated", self._create_session(connection, user_id=row["id"])
                )
        except sa.exc.SQLAlchemyError as error:
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error

    def oauth_login(
        self, *, provider: IdentityProvider, subject: str, email: str
    ) -> LoginResult:
        """Find an exact provider identity or atomically create a new OAuth account.

        A collision with an existing email account is intentionally rejected; linking
        requires an authenticated account owner and is not inferred from email.
        """
        if (
            provider not in {IdentityProvider.GITHUB, IdentityProvider.GOOGLE}
            or not subject
        ):
            return LoginResult("rejected")
        try:
            normalized_email = _normalize_email(email)
        except ValueError:
            return LoginResult("rejected")
        try:
            with self._engine.begin() as connection:
                existing = (
                    connection.execute(
                        sa.select(AuthIdentity.user_id, AuthUser.status)
                        .join(AuthUser, AuthUser.id == AuthIdentity.user_id)
                        .where(
                            AuthIdentity.provider == provider,
                            AuthIdentity.provider_subject == subject,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if existing["status"] != UserStatus.ACTIVE:
                        return LoginResult("rejected")
                    return LoginResult(
                        "authenticated",
                        self._create_session(connection, user_id=existing["user_id"]),
                    )

                user_id = uuid7()
                inserted = connection.execute(
                    postgres_insert(AuthUser)
                    .values(
                        id=user_id,
                        email=normalized_email,
                        status=UserStatus.ACTIVE,
                        email_confirmed_at=sa.func.now(),
                    )
                    .on_conflict_do_nothing(
                        index_elements=[sa.func.lower(AuthUser.email)],
                        index_where=AuthUser.email.is_not(None),
                    )
                    .returning(AuthUser.id)
                ).scalar_one_or_none()
                if inserted is None:
                    return LoginResult("rejected")
                connection.execute(sa.insert(User).values(id=user_id))
                connection.execute(
                    sa.insert(AuthIdentity).values(
                        id=uuid7(),
                        user_id=user_id,
                        provider=provider,
                        provider_subject=subject,
                    )
                )
                return LoginResult(
                    "authenticated", self._create_session(connection, user_id=user_id)
                )
        except sa.exc.SQLAlchemyError as error:
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error

    def refresh(self, *, refresh_token: str) -> LoginResult:
        try:
            token_hash = self._digest(refresh_token, TokenPurpose.REFRESH)
        except ValueError:
            return LoginResult("rejected")
        try:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        sa.select(
                            RefreshToken,
                            AuthSession.user_id,
                            AuthSession.revoked_at.label("session_revoked_at"),
                        )
                        .join(AuthSession, AuthSession.id == RefreshToken.session_id)
                        .where(RefreshToken.token_hash == token_hash)
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return LoginResult("rejected")
                invalid = (
                    row["consumed_at"] is not None
                    or row["revoked_at"] is not None
                    or row["session_revoked_at"] is not None
                    or row["expires_at"] <= _now()
                )
                if invalid:
                    self._revoke_session(connection, row["session_id"])
                    return LoginResult("rejected")
                replacement = self._create_session_token(
                    connection, session_id=row["session_id"]
                )
                connection.execute(
                    sa.update(RefreshToken)
                    .where(
                        RefreshToken.id == row["id"], RefreshToken.consumed_at.is_(None)
                    )
                    .values(consumed_at=sa.func.now(), replaced_by_id=replacement[0])
                )
                connection.execute(
                    sa.update(AuthSession)
                    .where(AuthSession.id == row["session_id"])
                    .values(last_seen_at=sa.func.now())
                )
                return LoginResult(
                    "authenticated",
                    SessionTokens(
                        access_token=self._jwt.issue(
                            user_id=row["user_id"], session_id=row["session_id"]
                        ),
                        refresh_token=replacement[1],
                        session_id=row["session_id"],
                    ),
                )
        except sa.exc.SQLAlchemyError as error:
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error

    def recover_password(self, *, email: str, destination: str) -> None:
        try:
            normalized_email = _normalize_email(email)
        except ValueError:
            return
        token = generate_opaque_token()
        job_id: UUID | None = None
        try:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        sa.select(AuthUser.id, AuthUser.email)
                        .join(
                            PasswordCredential,
                            PasswordCredential.user_id == AuthUser.id,
                        )
                        .where(
                            sa.func.lower(AuthUser.email) == normalized_email,
                            AuthUser.status == UserStatus.ACTIVE,
                            AuthUser.email_confirmed_at.is_not(None),
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return
                connection.execute(
                    sa.update(PasswordRecoveryToken)
                    .where(
                        PasswordRecoveryToken.user_id == row["id"],
                        PasswordRecoveryToken.used_at.is_(None),
                    )
                    .values(used_at=sa.func.now())
                )
                connection.execute(
                    sa.insert(PasswordRecoveryToken).values(
                        id=uuid7(),
                        user_id=row["id"],
                        token_hash=self._digest(token, TokenPurpose.PASSWORD_RECOVERY),
                        expires_at=_now()
                        + timedelta(minutes=self._settings.password_recovery_minutes),
                    )
                )
                job_id = self._jobs.create(
                    connection,
                    user_id=row["id"],
                    kind=EmailDeliveryKind.PASSWORD_RECOVERY,
                    payload={
                        "email": row["email"],
                        "token": token,
                        "destination": destination,
                    },
                    cipher=self._email_cipher,
                )
        except (sa.exc.SQLAlchemyError, CredentialEncryptionUnavailable) as error:
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error
        self._dispatch(job_id)

    def reset_password(self, *, token: str, password: str) -> bool:
        try:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        sa.select(PasswordRecoveryToken)
                        .where(
                            PasswordRecoveryToken.token_hash
                            == self._digest(token, TokenPurpose.PASSWORD_RECOVERY),
                            PasswordRecoveryToken.used_at.is_(None),
                            PasswordRecoveryToken.expires_at > _now(),
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return False
                connection.execute(
                    sa.update(PasswordCredential)
                    .where(PasswordCredential.user_id == row["user_id"])
                    .values(
                        password_hash=hash_password(password),
                        password_changed_at=sa.func.now(),
                    )
                )
                connection.execute(
                    sa.update(PasswordRecoveryToken)
                    .where(
                        PasswordRecoveryToken.user_id == row["user_id"],
                        PasswordRecoveryToken.used_at.is_(None),
                    )
                    .values(used_at=sa.func.now())
                )
                connection.execute(
                    sa.update(AuthSession)
                    .where(
                        AuthSession.user_id == row["user_id"],
                        AuthSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=sa.func.now())
                )
                connection.execute(
                    sa.update(RefreshToken)
                    .where(
                        RefreshToken.session_id.in_(
                            sa.select(AuthSession.id).where(
                                AuthSession.user_id == row["user_id"]
                            )
                        ),
                        RefreshToken.revoked_at.is_(None),
                    )
                    .values(revoked_at=sa.func.now())
                )
                return True
        except (ValueError, sa.exc.SQLAlchemyError) as error:
            if isinstance(error, ValueError):
                return False
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error

    def logout(self, *, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        try:
            token_hash = self._digest(refresh_token, TokenPurpose.REFRESH)
        except ValueError:
            return
        try:
            with self._engine.begin() as connection:
                session_id = connection.execute(
                    sa.select(RefreshToken.session_id)
                    .where(RefreshToken.token_hash == token_hash)
                    .with_for_update()
                ).scalar_one_or_none()
                if session_id is not None:
                    self._revoke_session(connection, session_id)
        except sa.exc.SQLAlchemyError as error:
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error

    def session_id_for_refresh(self, refresh_token: str | None) -> UUID | None:
        if not refresh_token:
            return None
        try:
            token_hash = self._digest(refresh_token, TokenPurpose.REFRESH)
            with self._engine.connect() as connection:
                return connection.execute(
                    sa.select(RefreshToken.session_id).where(
                        RefreshToken.token_hash == token_hash
                    )
                ).scalar_one_or_none()
        except (ValueError, sa.exc.SQLAlchemyError):
            return None

    def is_session_active(self, *, user_id: UUID, session_id: UUID) -> bool:
        try:
            with self._engine.connect() as connection:
                return (
                    connection.execute(
                        sa.select(AuthSession.id)
                        .join(AuthUser, AuthUser.id == AuthSession.user_id)
                        .where(
                            AuthSession.id == session_id,
                            AuthSession.user_id == user_id,
                            AuthSession.revoked_at.is_(None),
                            AuthSession.expires_at > _now(),
                            AuthUser.status == UserStatus.ACTIVE,
                        )
                    ).scalar_one_or_none()
                    is not None
                )
        except sa.exc.SQLAlchemyError as error:
            raise AuthenticationUnavailable(
                "Authentication database is unavailable"
            ) from error

    def access_claims(self, access_token: str | None) -> AccessTokenClaims | None:
        if not access_token:
            return None
        try:
            claims = self._jwt.verify(access_token)
        except ValueError:
            return None
        return (
            claims
            if self.is_session_active(
                user_id=claims.user_id, session_id=claims.session_id
            )
            else None
        )

    def _create_session(
        self, connection: sa.Connection, *, user_id: UUID
    ) -> SessionTokens:
        session_id = uuid7()
        connection.execute(
            sa.insert(AuthSession).values(
                id=session_id,
                user_id=user_id,
                expires_at=_now() + timedelta(days=self._settings.refresh_token_days),
            )
        )
        _, refresh_token = self._create_session_token(connection, session_id=session_id)
        return SessionTokens(
            access_token=self._jwt.issue(user_id=user_id, session_id=session_id),
            refresh_token=refresh_token,
            session_id=session_id,
        )

    def _create_session_token(
        self, connection: sa.Connection, *, session_id: UUID
    ) -> tuple[UUID, str]:
        token_id = uuid7()
        raw_token = generate_opaque_token()
        connection.execute(
            sa.insert(RefreshToken).values(
                id=token_id,
                session_id=session_id,
                token_hash=self._digest(raw_token, TokenPurpose.REFRESH),
                expires_at=_now() + timedelta(days=self._settings.refresh_token_days),
            )
        )
        return token_id, raw_token

    def _revoke_session(self, connection: sa.Connection, session_id: UUID) -> None:
        connection.execute(
            sa.update(AuthSession)
            .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=sa.func.now())
        )
        connection.execute(
            sa.update(RefreshToken)
            .where(
                RefreshToken.session_id == session_id, RefreshToken.revoked_at.is_(None)
            )
            .values(revoked_at=sa.func.now())
        )

    def _dispatch(self, job_id: UUID | None) -> None:
        if job_id is not None and self._dispatcher is not None:
            self._dispatcher.dispatch(job_id)

    def _digest(self, token: str, purpose: TokenPurpose) -> bytes:
        return digest_opaque_token(token, key=self._token_hash_key, purpose=purpose)


def _normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 320 or "@" not in email or email.count("@") != 1:
        raise ValueError("Email is invalid")
    local, domain = email.split("@", 1)
    if not local or not domain or any(character.isspace() for character in email):
        raise ValueError("Email is invalid")
    return email


def _now() -> datetime:
    return datetime.now(UTC)
