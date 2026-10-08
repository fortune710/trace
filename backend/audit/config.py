"""Configuration validation for the immudb audit client and worker."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuditConfigurationError(RuntimeError):
    """Raised when the immutable audit path is incompletely configured."""


class AuditSettings(BaseSettings):
    enabled: bool = False
    host: str = "immudb"
    port: int = 3322
    database: str = "trace_audit"
    username: str | None = None
    password: SecretStr | None = None
    tls: bool = False
    ca_file: str | None = None
    public_key_file: str | None = None
    root_state_dir: str = "/tmp/trace-audit"
    request_timeout_seconds: float = 5.0
    page_size: int = 20
    max_page_size: int = 100
    max_attempts: int = 8
    retry_base_seconds: int = 5
    retry_max_seconds: int = 900
    outbox_retention_days: int = 30
    dead_letter_retention_days: int = 90
    model_config = SettingsConfigDict(env_prefix="AUDIT_", extra="ignore")

    def validate_for_audit(self) -> None:
        if self.port < 1 or self.port > 65535:
            raise AuditConfigurationError("audit port configuration is invalid")
        if not self.host or len(self.host) > 253 or urlparse(f"//{self.host}").path:
            raise AuditConfigurationError("audit host configuration is invalid")
        if not self.database or len(self.database) > 128:
            raise AuditConfigurationError("audit database configuration is invalid")
        if self.page_size < 1 or self.page_size > self.max_page_size:
            raise AuditConfigurationError("audit page-size configuration is invalid")
        if self.max_page_size < 1 or self.max_page_size > 100:
            raise AuditConfigurationError("audit page-size configuration is invalid")
        if self.request_timeout_seconds <= 0 or self.request_timeout_seconds > 60:
            raise AuditConfigurationError("audit timeout configuration is invalid")
        if self.max_attempts < 1 or self.max_attempts > 100:
            raise AuditConfigurationError("audit retry configuration is invalid")
        if (
            self.retry_base_seconds < 1
            or self.retry_max_seconds < self.retry_base_seconds
        ):
            raise AuditConfigurationError("audit retry configuration is invalid")
        if self.outbox_retention_days < 1 or self.dead_letter_retention_days < 1:
            raise AuditConfigurationError("audit retention configuration is invalid")
        if self.tls and not self.ca_file:
            raise AuditConfigurationError("audit TLS requires a CA file")
        for path_value in (self.ca_file, self.public_key_file):
            if path_value is not None and not Path(path_value).is_file():
                raise AuditConfigurationError(
                    "audit certificate configuration is invalid"
                )
        state_dir = Path(self.root_state_dir)
        if self.enabled and (
            not state_dir.is_absolute() or state_dir.exists() and not state_dir.is_dir()
        ):
            raise AuditConfigurationError("audit root state directory is invalid")
        if self.enabled and (
            not self.username
            or self.password is None
            or not self.password.get_secret_value()
        ):
            raise AuditConfigurationError("audit credentials are incomplete")


def get_audit_settings() -> AuditSettings:
    settings = AuditSettings()
    settings.validate_for_audit()
    return settings
