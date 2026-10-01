import asyncio

from auth.rate_limit import RateLimitKeyFactory, RateLimitPolicy, TokenBucketRateLimiter


class ScriptedRedis:
    def __init__(self, response: list[int]) -> None:
        self.response = response
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> list[int]:
        self.calls.append((script, numkeys, *keys_and_args))
        return self.response


def test_token_bucket_returns_remaining_capacity_for_an_allowed_request() -> None:
    redis = ScriptedRedis([1, 0, 4])
    policy = RateLimitPolicy("auth.login.identity", capacity=5, refill_tokens=5, refill_period_seconds=900)
    limiter = TokenBucketRateLimiter(redis, RateLimitKeyFactory(b"d" * 32))

    result = asyncio.run(limiter.check(policy, "identity-fingerprint"))

    assert result.allowed
    assert result.remaining_tokens == 4
    assert result.retry_after_seconds == 0
    assert redis.calls[0][1] == 1


def test_token_bucket_returns_retry_after_for_a_rejected_request() -> None:
    redis = ScriptedRedis([0, 2_500, 0])
    policy = RateLimitPolicy("auth.login.identity", capacity=5, refill_tokens=5, refill_period_seconds=900)
    limiter = TokenBucketRateLimiter(redis, RateLimitKeyFactory(b"d" * 32))

    result = asyncio.run(limiter.check(policy, "identity-fingerprint"))

    assert not result.allowed
    assert result.remaining_tokens == 0
    assert result.retry_after_seconds == 3


def test_rate_limit_keys_do_not_include_the_raw_subject() -> None:
    key = RateLimitKeyFactory(b"d" * 32).create(
        RateLimitPolicy("auth.login.ip", capacity=20, refill_tokens=20, refill_period_seconds=900),
        "198.51.100.10",
    )

    assert "198.51.100.10" not in key
