from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from auth.config import AuthSettings
from auth.oauth import (
    OAUTH_CALLBACK_ROUTE,
    OAuthRejected,
    OAuthStateStore,
    _provider_configuration,
    install_oauth_routes,
    oauth_callback_path,
)


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
async def test_oauth_state_is_single_use_and_does_not_store_raw_state_as_a_key() -> (
    None
):
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


def _example_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (
        (Path(__file__).resolve().parents[2] / ".env.example").read_text().splitlines()
    ):
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", maxsplit=1)
            values[key] = value
    return values


@pytest.mark.parametrize("provider", ("github", "google"))
def test_documented_oauth_redirect_uri_matches_the_registered_callback_route(
    provider: str,
) -> None:
    environment = _example_environment()
    settings = AuthSettings(
        github_client_id="github-test-client",
        github_client_secret=SecretStr("github-test-secret"),
        github_redirect_uri=environment["AUTH_GITHUB_REDIRECT_URI"],
        google_client_id="google-test-client",
        google_client_secret=SecretStr("google-test-secret"),
        google_redirect_uri=environment["AUTH_GOOGLE_REDIRECT_URI"],
    )
    app = FastAPI()
    install_oauth_routes(app, settings, audit_hasher=None)

    configured_path = urlparse(
        _provider_configuration(settings, provider).redirect_uri
    ).path
    registered_paths = {route.path for route in app.routes}

    assert configured_path == oauth_callback_path(provider)
    assert OAUTH_CALLBACK_ROUTE in registered_paths
