"""Configuration for the skills.sh catalog client."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agents.skills.logging import skills_log, skills_transport_mode


class SkillsSettings(BaseSettings):
    """Server-side skills.sh access settings.

    Trace's FastAPI API runs outside Vercel, so production should either supply
    ``VERCEL_OIDC_TOKEN`` (for local/dev via ``vercel env pull``) or point
    ``SKILLS_SH_PROXY_URL`` at the Vite project's Vercel OIDC proxy function.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    base_url: str = Field(
        default="https://skills.sh",
        validation_alias=AliasChoices("SKILLS_SH_BASE_URL", "SKILLS_BASE_URL"),
    )
    oidc_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("VERCEL_OIDC_TOKEN", "SKILLS_SH_OIDC_TOKEN"),
    )
    proxy_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SKILLS_SH_PROXY_URL"),
    )
    proxy_secret: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SKILLS_SH_PROXY_SECRET"),
    )
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    max_skill_md_chars: int = Field(default=200_000, ge=1_000, le=500_000)
    max_files: int = Field(default=32, ge=1, le=64)
    max_file_chars: int = Field(default=100_000, ge=1_000, le=500_000)

    @field_validator("base_url", mode="before")
    @classmethod
    def _strip_or_default_base_url(cls, value: object) -> object:
        if value is None:
            return "https://skills.sh"
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or "https://skills.sh"
        return value

    @field_validator("proxy_url", mode="before")
    @classmethod
    def _blank_proxy_url_to_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("oidc_token", "proxy_secret", mode="before")
    @classmethod
    def _blank_secret_to_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value

    def transport_mode(self) -> str:
        return skills_transport_mode(
            proxy_url=self.proxy_url,
            proxy_secret_configured=self.proxy_secret is not None,
            oidc_configured=self.oidc_token is not None,
        )

    def log_startup_status(self) -> None:
        mode = self.transport_mode()
        skills_log(
            "skills_transport_status",
            level=30 if mode in {"unconfigured", "proxy_misconfigured"} else 20,
            transport=mode,
            proxy_url_configured=bool(self.proxy_url),
            proxy_secret_configured=self.proxy_secret is not None,
            oidc_configured=self.oidc_token is not None,
            base_host=self.base_url,
        )


@lru_cache
def get_skills_settings() -> SkillsSettings:
    settings = SkillsSettings()
    settings.log_startup_status()
    return settings
