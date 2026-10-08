from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from typing import Any

from redis.exceptions import RedisError

from auth.config import AuthSettings
from auth.errors import AuthError, RateLimitExceeded
from auth.tokens import decode_base64url_key
from db.session import get_redis_client

TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_millisecond = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local current_time = redis.call('TIME')
local now = tonumber(current_time[1]) * 1000 + math.floor(tonumber(current_time[2]) / 1000)
local state = redis.call('HMGET', key, 'tokens', 'updated_at')
local tokens = tonumber(state[1]) or capacity
local updated_at = tonumber(state[2]) or now

tokens = math.min(capacity, tokens + math.max(0, now - updated_at) * refill_per_millisecond)
redis.call('HSET', key, 'tokens', tokens, 'updated_at', now)
redis.call('PEXPIRE', key, ttl)

if tokens < cost then
  local retry_after = math.ceil((cost - tokens) / refill_per_millisecond)
  return {0, retry_after, math.floor(tokens)}
end

tokens = tokens - cost
redis.call('HSET', key, 'tokens', tokens, 'updated_at', now)
return {1, 0, math.floor(tokens)}
"""


class RateLimiterUnavailable(RuntimeError):
    """Raised when Redis cannot enforce a security-sensitive limit."""


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    capacity: int
    refill_tokens: int
    refill_period_seconds: int

    def __post_init__(self) -> None:
        if (
            not self.name
            or self.capacity <= 0
            or self.refill_tokens <= 0
            or self.refill_period_seconds <= 0
        ):
            raise ValueError(
                "Rate-limit policies require positive capacity and refill values"
            )

    @property
    def refill_per_millisecond(self) -> float:
        return self.refill_tokens / (self.refill_period_seconds * 1000)

    @property
    def key_ttl_milliseconds(self) -> int:
        return math.ceil(self.capacity / self.refill_per_millisecond) + 1_000


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int
    remaining_tokens: int


class RateLimitKeyFactory:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("Rate-limit key material must contain at least 32 bytes")
        self._secret = secret

    def create(self, policy: RateLimitPolicy, subject: str) -> str:
        if not subject or len(subject) > 1024:
            raise ValueError("Rate-limit subject is malformed")
        digest = hmac.new(
            self._secret, subject.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"trace:rate-limit:v1:{policy.name}:{digest}"


class TokenBucketRateLimiter:
    def __init__(self, client: Any, key_factory: RateLimitKeyFactory) -> None:
        self._client = client
        self._key_factory = key_factory

    async def check(
        self, policy: RateLimitPolicy, subject: str, *, cost: int = 1
    ) -> RateLimitResult:
        if cost <= 0 or cost > policy.capacity:
            raise ValueError(
                "Rate-limit cost must be between one and the policy capacity"
            )

        key = self._key_factory.create(policy, subject)
        try:
            result = await self._client.eval(
                TOKEN_BUCKET_SCRIPT,
                1,
                key,
                str(policy.capacity),
                repr(policy.refill_per_millisecond),
                str(cost),
                str(policy.key_ttl_milliseconds),
            )
        except RedisError as error:
            raise RateLimiterUnavailable("Rate limiter is unavailable") from error

        if len(result) != 3:
            raise RateLimiterUnavailable("Rate limiter returned an invalid response")

        allowed, retry_after_milliseconds, remaining_tokens = (
            int(value) for value in result
        )
        return RateLimitResult(
            allowed=allowed == 1,
            retry_after_seconds=max(1, math.ceil(retry_after_milliseconds / 1000))
            if not allowed
            else 0,
            remaining_tokens=max(0, remaining_tokens),
        )


AUTH_RATE_LIMIT_POLICIES = {
    "auth.login.ip": RateLimitPolicy(
        "auth.login.ip", capacity=20, refill_tokens=20, refill_period_seconds=900
    ),
    "auth.login.identity": RateLimitPolicy(
        "auth.login.identity", capacity=5, refill_tokens=5, refill_period_seconds=900
    ),
    "auth.registration.ip": RateLimitPolicy(
        "auth.registration.ip",
        capacity=10,
        refill_tokens=10,
        refill_period_seconds=3600,
    ),
    "auth.password_recovery.ip": RateLimitPolicy(
        "auth.password_recovery.ip",
        capacity=5,
        refill_tokens=5,
        refill_period_seconds=3600,
    ),
    "auth.password_recovery.identity": RateLimitPolicy(
        "auth.password_recovery.identity",
        capacity=3,
        refill_tokens=3,
        refill_period_seconds=3600,
    ),
    "auth.oauth_start.ip": RateLimitPolicy(
        "auth.oauth_start.ip", capacity=10, refill_tokens=10, refill_period_seconds=600
    ),
    "auth.refresh.session": RateLimitPolicy(
        "auth.refresh.session", capacity=30, refill_tokens=30, refill_period_seconds=300
    ),
    "resource.project_write.user": RateLimitPolicy(
        "resource.project_write.user",
        capacity=60,
        refill_tokens=60,
        refill_period_seconds=900,
    ),
    "resource.review_submit.user": RateLimitPolicy(
        "resource.review_submit.user",
        capacity=20,
        refill_tokens=20,
        refill_period_seconds=900,
    ),
    "resource.credential_write.user": RateLimitPolicy(
        "resource.credential_write.user",
        capacity=20,
        refill_tokens=20,
        refill_period_seconds=900,
    ),
    "resource.repository_read.user": RateLimitPolicy(
        "resource.repository_read.user",
        capacity=60,
        refill_tokens=60,
        refill_period_seconds=900,
    ),
}


def rate_limiter_from_settings(settings: AuthSettings) -> TokenBucketRateLimiter:
    settings.validate_for_authentication()
    assert settings.token_hash_key is not None
    return TokenBucketRateLimiter(
        get_redis_client(),
        RateLimitKeyFactory(
            decode_base64url_key(
                settings.token_hash_key.get_secret_value(), name="AUTH_TOKEN_HASH_KEY"
            )
        ),
    )


async def enforce_rate_limit(
    limiter: TokenBucketRateLimiter,
    *,
    policy: RateLimitPolicy,
    subject: str,
) -> None:
    try:
        result = await limiter.check(policy, subject)
    except RateLimiterUnavailable as error:
        raise AuthError(
            code="auth_temporarily_unavailable",
            message="Authentication is temporarily unavailable.",
            status_code=503,
            event="dependency",
            reason="rate_limiter_unavailable",
        ) from error

    if not result.allowed:
        raise RateLimitExceeded(result.retry_after_seconds, policy.name)
