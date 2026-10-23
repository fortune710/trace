from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from auth.config import AuthSettings


class InvalidAccessToken(ValueError):
    """Raised without exposing JWT verification details to callers."""


class TokenPurpose(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RECOVERY = "password_recovery"
    REFRESH = "refresh"


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    token_id: str
    issued_at: datetime
    expires_at: datetime


def decode_base64url_key(value: str, *, name: str, expected_length: int = 32) -> bytes:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"{name} must be base64url-encoded") from error

    if len(decoded) != expected_length:
        raise ValueError(f"{name} must contain exactly {expected_length} bytes")

    return decoded


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def digest_opaque_token(token: str, *, key: bytes, purpose: TokenPurpose) -> bytes:
    if not token or len(token) > 512:
        raise ValueError("Token is malformed")

    message = (
        b"trace-auth:v1:" + purpose.value.encode("ascii") + b":" + token.encode("ascii")
    )
    return hmac.new(key, message, hashlib.sha256).digest()


class JWTService:
    """Issues and verifies the fixed EdDSA access-token contract."""

    def __init__(
        self,
        *,
        signing_key: Ed25519PrivateKey,
        key_id: str,
        issuer: str,
        audience: str,
        verification_keys: Mapping[str, Ed25519PublicKey] | None = None,
    ) -> None:
        if not key_id or not issuer or not audience:
            raise ValueError("JWT issuer, audience, and key ID are required")

        self._signing_key = signing_key
        self._key_id = key_id
        self._issuer = issuer
        self._audience = audience
        self._verification_keys = {
            key_id: signing_key.public_key(),
            **(verification_keys or {}),
        }

    @classmethod
    def from_private_key_bytes(
        cls,
        key: bytes,
        *,
        key_id: str,
        issuer: str,
        audience: str,
        verification_keys: Mapping[str, bytes] | None = None,
    ) -> JWTService:
        if len(key) != 32:
            raise ValueError("Ed25519 private keys must contain exactly 32 bytes")

        public_keys = {
            existing_key_id: Ed25519PublicKey.from_public_bytes(existing_key)
            for existing_key_id, existing_key in (verification_keys or {}).items()
        }
        return cls(
            signing_key=Ed25519PrivateKey.from_private_bytes(key),
            key_id=key_id,
            issuer=issuer,
            audience=audience,
            verification_keys=public_keys,
        )

    def issue(
        self, *, user_id: UUID, session_id: UUID, now: datetime | None = None
    ) -> str:
        issued_at = (now or datetime.now(UTC)).replace(microsecond=0)
        expires_at = issued_at + timedelta(minutes=60)
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(user_id),
            "sid": str(session_id),
            "jti": generate_opaque_token(),
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
            "token_use": "access",
        }
        return jwt.encode(
            payload,
            self._signing_key,
            algorithm="EdDSA",
            headers={"kid": self._key_id, "typ": "at+jwt"},
        )

    def verify(self, token: str) -> AccessTokenClaims:
        if not token or len(token) > 8192:
            raise InvalidAccessToken("Invalid access token")

        try:
            header = jwt.get_unverified_header(token)
            key_id = header.get("kid")
            if header.get("alg") != "EdDSA" or not isinstance(key_id, str):
                raise InvalidAccessToken("Invalid access token")
            verification_key = self._verification_keys.get(key_id)
            if verification_key is None:
                raise InvalidAccessToken("Invalid access token")
            payload = jwt.decode(
                token,
                verification_key,
                algorithms=["EdDSA"],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": ["aud", "exp", "iat", "iss", "jti", "nbf", "sid", "sub"]
                },
            )
            if payload.get("token_use") != "access" or header.get("typ") != "at+jwt":
                raise InvalidAccessToken("Invalid access token")
            issued_at = datetime.fromtimestamp(int(payload["iat"]), UTC)
            expires_at = datetime.fromtimestamp(int(payload["exp"]), UTC)
            if expires_at <= issued_at:
                raise InvalidAccessToken("Invalid access token")
            return AccessTokenClaims(
                user_id=UUID(payload["sub"]),
                session_id=UUID(payload["sid"]),
                token_id=str(payload["jti"]),
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
            if isinstance(error, InvalidAccessToken):
                raise
            raise InvalidAccessToken("Invalid access token") from error


def jwt_service_from_settings(settings: AuthSettings) -> JWTService:
    settings.validate_for_authentication()
    assert settings.jwt_private_key is not None
    private_key = decode_base64url_key(
        settings.jwt_private_key.get_secret_value(), name="AUTH_JWT_PRIVATE_KEY"
    )
    verification_keys = {
        key_id: decode_base64url_key(
            encoded_key, name=f"AUTH_JWT_VERIFICATION_KEYS[{key_id}]"
        )
        for key_id, encoded_key in settings.jwt_verification_keys.items()
    }
    return JWTService.from_private_key_bytes(
        private_key,
        key_id=settings.jwt_key_id,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        verification_keys=verification_keys,
    )
