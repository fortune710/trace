from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthenticationConfigurationError(RuntimeError):
    """Raised when authentication is enabled without required secure configuration."""


PRODUCTION_FRONTEND_ORIGINS = frozenset(
    {"https://trace.fortunealebiosu.dev", "https://traceai.vercel.app"}
)


class AuthSettings(BaseSettings):
    environment: Literal["development", "test", "production"] = "development"
    jwt_issuer: str = "trace-api"
    jwt_audience: str = "trace-api"
    jwt_key_id: str = "local-v1"
    jwt_private_key: SecretStr | None = None
    jwt_verification_keys: dict[str, str] = Field(default_factory=dict)
    token_hash_key: SecretStr | None = None
    credential_encryption_provider: Literal["local", "vault"] = "local"
    credential_encryption_key: SecretStr | None = None
    credential_encryption_key_version: str = "local-v1"
    vault_addr: str | None = None
    vault_token: SecretStr | None = None
    vault_transit_mount: str = "transit"
    vault_transit_key: str = "trace-provider-credentials"
    vault_email_transit_key: str = "trace-email-delivery"
    vault_request_timeout_seconds: float = 3.0
    vault_token_renewal_seconds: int = 300
    csrf_hmac_key: SecretStr | None = None
    audit_hash_key: SecretStr | None = None
    access_token_minutes: int = 60
    refresh_token_days: int = 7
    email_verification_hours: int = 24
    password_recovery_minutes: int = 15
    email_max_retries: int = 3
    email_retry_delays_seconds: tuple[int, int, int] = (30, 300, 1800)
    email_from: str = "Trace <no-reply@trace.local>"
    frontend_url: str = "http://localhost:5173"
    smtp_host: str | None = Field(default=None, validation_alias=AliasChoices("AUTH_SMTP_HOST", "SMTP_HOST"))
    smtp_port: int = Field(default=1025, validation_alias=AliasChoices("AUTH_SMTP_PORT", "SMTP_PORT"))
    smtp_username: str | None = Field(default=None, validation_alias=AliasChoices("AUTH_SMTP_USERNAME", "SMTP_USERNAME"))
    smtp_password: SecretStr | None = Field(default=None, validation_alias=AliasChoices("AUTH_SMTP_PASSWORD", "SMTP_PASSWORD"))
    smtp_use_starttls: bool = False
    rabbitmq_url: str | None = None
    cookie_secure: bool = True
    access_cookie_name: str = "__Host-trace_access"
    refresh_cookie_name: str = "__Secure-trace_refresh"
    csrf_cookie_name: str = "trace_csrf"
    cookie_same_site: Literal["lax", "none", "strict"] = "lax"
    allowed_origins: list[str] = Field(default_factory=list)
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None
    github_redirect_uri: str | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None

    model_config = SettingsConfigDict(env_prefix="AUTH_", extra="ignore")

    def validate_for_authentication(self) -> None:
        required_secrets = {
            "AUTH_JWT_PRIVATE_KEY": self.jwt_private_key,
            "AUTH_TOKEN_HASH_KEY": self.token_hash_key,
            "AUTH_CSRF_HMAC_KEY": self.csrf_hmac_key,
            "AUTH_AUDIT_HASH_KEY": self.audit_hash_key,
        }
        if self.credential_encryption_provider == "local":
            required_secrets["AUTH_CREDENTIAL_ENCRYPTION_KEY"] = self.credential_encryption_key
        missing = [name for name, value in required_secrets.items() if value is None or not value.get_secret_value()]
        if missing:
            raise AuthenticationConfigurationError("Authentication security configuration is incomplete")

        for value in required_secrets.values():
            assert value is not None
            try:
                encoded = value.get_secret_value()
                padded = encoded + "=" * (-len(encoded) % 4)
                decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
            except (ValueError, binascii.Error) as error:
                raise AuthenticationConfigurationError("Authentication security configuration is invalid") from error
            if len(decoded) != 32:
                raise AuthenticationConfigurationError("Authentication security configuration is invalid")

        if self.access_token_minutes != 60 or self.refresh_token_days != 7:
            raise AuthenticationConfigurationError("Configured token lifetimes do not match the approved security policy")

        if self.email_max_retries < 1 or len(self.email_retry_delays_seconds) != self.email_max_retries:
            raise AuthenticationConfigurationError("Email retry configuration is invalid")
        if any(delay <= 0 or delay > 86_400 for delay in self.email_retry_delays_seconds):
            raise AuthenticationConfigurationError("Email retry configuration is invalid")
        if not self.email_from or len(self.email_from) > 320:
            raise AuthenticationConfigurationError("Email sender configuration is invalid")
        frontend = urlparse(self.frontend_url)
        if frontend.scheme not in {"http", "https"} or not frontend.netloc or frontend.username or frontend.password:
            raise AuthenticationConfigurationError("Frontend URL configuration is invalid")

        if self.credential_encryption_provider == "vault":
            self._validate_vault_settings()

        if self.environment == "production":
            if not self.cookie_secure:
                raise AuthenticationConfigurationError("Secure cookies are required in production")
            if not self.access_cookie_name.startswith("__Host-"):
                raise AuthenticationConfigurationError("Production access cookies must use the __Host- prefix")
            if not self.refresh_cookie_name.startswith("__Secure-"):
                raise AuthenticationConfigurationError("Production refresh cookies must use the __Secure- prefix")
            if self.cookie_same_site != "none":
                raise AuthenticationConfigurationError("Production cookies must support the approved cross-site frontend")
            if set(self.allowed_origins) != PRODUCTION_FRONTEND_ORIGINS:
                raise AuthenticationConfigurationError("Production authentication origins do not match the approved frontend origins")
            if self.frontend_url.rstrip("/") not in PRODUCTION_FRONTEND_ORIGINS:
                raise AuthenticationConfigurationError("Production email links must use an approved frontend origin")
            if not self.smtp_host or not self.rabbitmq_url:
                raise AuthenticationConfigurationError("Production email delivery configuration is incomplete")
        elif self.cookie_same_site == "none" and not self.cookie_secure:
            raise AuthenticationConfigurationError("SameSite=None cookies require the Secure attribute")

        if "*" in self.allowed_origins:
            raise AuthenticationConfigurationError("Wildcard origins are not permitted for credentialed authentication")

    def _validate_vault_settings(self) -> None:
        if self.vault_token is None or not self.vault_token.get_secret_value():
            raise AuthenticationConfigurationError("Vault credential encryption requires AUTH_VAULT_TOKEN")
        if not self.vault_addr:
            raise AuthenticationConfigurationError("Vault credential encryption requires AUTH_VAULT_ADDR")
        parsed = urlparse(self.vault_addr)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise AuthenticationConfigurationError("Vault credential encryption configuration is invalid")
        if self.environment == "production" and parsed.scheme != "https":
            raise AuthenticationConfigurationError("Production Vault connections require HTTPS")
        for value in (self.vault_transit_mount, self.vault_transit_key, self.vault_email_transit_key):
            if not value or len(value) > 128 or not value.replace("-", "").replace("_", "").isalnum():
                raise AuthenticationConfigurationError("Vault credential encryption configuration is invalid")
        if not 0 < self.vault_request_timeout_seconds <= 10:
            raise AuthenticationConfigurationError("Vault credential encryption configuration is invalid")
        if not 60 <= self.vault_token_renewal_seconds <= 3600:
            raise AuthenticationConfigurationError("Vault credential encryption configuration is invalid")


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
