"""Configuration for the internal review-dispatch publisher."""

from __future__ import annotations

from pydantic import Field, SecretStr
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


class AgentExecutionSettings(BaseSettings):
    """Configuration for review execution with optional LangSmith tracing."""

    rabbitmq_url: str | None = Field(
        default=None, validation_alias="REVIEW_RABBITMQ_URL"
    )
    langsmith_tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    langsmith_api_key: SecretStr | None = Field(
        default=None, validation_alias="LANGSMITH_API_KEY"
    )
    langsmith_endpoint: str | None = Field(
        default=None, validation_alias="LANGSMITH_ENDPOINT"
    )
    langsmith_project: str = Field(
        default="trace", validation_alias="LANGSMITH_PROJECT"
    )
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias="AGENT_OPENAI_API_KEY"
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias="AGENT_ANTHROPIC_API_KEY"
    )
    google_api_key: SecretStr | None = Field(
        default=None, validation_alias="AGENT_GOOGLE_API_KEY"
    )
    xai_api_key: SecretStr | None = Field(
        default=None, validation_alias="AGENT_XAI_API_KEY"
    )
    github_max_concurrent_requests: int = Field(
        default=2, validation_alias="REVIEW_GITHUB_MAX_CONCURRENT_REQUESTS", ge=1, le=20
    )
    github_get_max_attempts: int = Field(
        default=3, validation_alias="REVIEW_GITHUB_GET_MAX_ATTEMPTS", ge=1, le=5
    )
    github_retry_base_seconds: float = Field(
        default=0.25, validation_alias="REVIEW_GITHUB_RETRY_BASE_SECONDS", ge=0, le=10
    )
    github_retry_max_seconds: float = Field(
        default=2.0, validation_alias="REVIEW_GITHUB_RETRY_MAX_SECONDS", ge=0, le=30
    )

    model_config = SettingsConfigDict(extra="ignore")

    def validate_for_execution(self) -> None:
        if not self.rabbitmq_url or len(self.rabbitmq_url) > 2_048:
            raise RuntimeError("Review execution RabbitMQ configuration is incomplete")
        if self.langsmith_tracing and (
            self.langsmith_api_key is None
            or not self.langsmith_api_key.get_secret_value()
        ):
            raise RuntimeError("LangSmith API key is required when tracing is enabled")
        if self.github_retry_max_seconds < self.github_retry_base_seconds:
            raise RuntimeError("GitHub retry configuration is invalid")
