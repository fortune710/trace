"""Runtime configuration for automatic remediation PR publication."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RemediationPullRequestDispatchSettings(BaseSettings):
    rabbitmq_url: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=3)
    retry_base_seconds: int = Field(default=30, ge=1, le=3_600)
    retry_max_seconds: int = Field(default=300, ge=1, le=86_400)
    poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    processing_timeout_seconds: int = Field(default=300, ge=1, le=86_400)

    model_config = SettingsConfigDict(env_prefix="REMEDIATION_PR_", extra="ignore")

    def validate_for_dispatch(self) -> None:
        if not self.rabbitmq_url or len(self.rabbitmq_url) > 2_048:
            raise RuntimeError("Remediation PR RabbitMQ configuration is incomplete")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise RuntimeError("Remediation PR retry configuration is invalid")
