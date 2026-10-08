from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy import Engine, create_engine


class DatabaseSettings(BaseSettings):
    database_url: str | None = None
    maintenance_database_url: str | None = None
    redis_url: str | None = None

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")


@lru_cache
def get_engine() -> Engine:
    database_url = DatabaseSettings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return create_engine(database_url, pool_pre_ping=True)


@lru_cache
def get_maintenance_engine() -> Engine:
    database_url = DatabaseSettings().maintenance_database_url
    if not database_url:
        raise RuntimeError("MAINTENANCE_DATABASE_URL is not configured")

    return create_engine(database_url, pool_pre_ping=True)


def get_redis_url() -> str:
    redis_url = DatabaseSettings().redis_url
    if not redis_url:
        raise RuntimeError("REDIS_URL is not configured")

    return redis_url


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(
        get_redis_url(),
        decode_responses=False,
        health_check_interval=30,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


async def close_redis_client() -> None:
    if get_redis_client.cache_info().currsize == 0:
        return

    redis_client = get_redis_client()
    await redis_client.aclose()
    get_redis_client.cache_clear()
