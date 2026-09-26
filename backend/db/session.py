from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine


class DatabaseSettings(BaseSettings):
    database_url: str | None = None
    redis_url: str | None = None

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")


@lru_cache
def get_engine() -> Engine:
    database_url = DatabaseSettings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return create_engine(database_url, pool_pre_ping=True)


def get_redis_url() -> str:
    redis_url = DatabaseSettings().redis_url
    if not redis_url:
        raise RuntimeError("REDIS_URL is not configured")

    return redis_url
