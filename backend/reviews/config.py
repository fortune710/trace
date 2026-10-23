"""Configuration for the internal review-dispatch publisher."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReviewDispatchSettings(BaseSettings):
    """Runtime settings for publishing identifier-only review messages."""

    rabbitmq_url: str | None = None
    max_attempts: int = Field(default=8, ge=1, le=100)
    retry_base_seconds: int = Field(default=5, ge=1, le=3_600)
    retry_max_seconds: int = Field(default=900, ge=1, le=86_400)
    poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    processing_timeout_seconds: int = Field(default=300, ge=1, le=86_400)

    model_config = SettingsConfigDict(env_prefix="REVIEW_", extra="ignore")

    def validate_for_dispatch(self) -> None:
        if not self.rabbitmq_url or len(self.rabbitmq_url) > 2_048:
            raise RuntimeError("Review dispatch RabbitMQ configuration is incomplete")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise RuntimeError("Review dispatch retry configuration is invalid")
