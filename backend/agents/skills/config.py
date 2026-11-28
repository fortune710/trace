"""Configuration for the skills.sh catalog client."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_skills_settings() -> SkillsSettings:
    return SkillsSettings()
