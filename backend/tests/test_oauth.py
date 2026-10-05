import pytest

from auth.oauth import OAuthRejected, OAuthStateStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key, value, *, ex, nx):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def getdel(self, key):
        return self.values.pop(key, None)


@pytest.mark.anyio
async def test_oauth_state_is_single_use_and_does_not_store_raw_state_as_a_key() -> None:
    redis = FakeRedis()
    store = OAuthStateStore(redis_client=redis, state_key=b"a" * 32)

    state, verifier, nonce = await store.create(
        provider="google",
        destination="https://traceai.vercel.app",
        user_agent="test-agent",
    )
    transaction = await store.consume(state)

    assert transaction.verifier == verifier
    assert transaction.nonce == nonce
    assert all(state not in key for key in redis.values)
    with pytest.raises(OAuthRejected):
        await store.consume(state)
