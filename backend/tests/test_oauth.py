from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from auth.config import AuthSettings
from auth.oauth import (
    GITHUB_CONNECT_START_ROUTE,
    OAUTH_CALLBACK_ROUTE,
    OAuthPurpose,
    OAuthRejected,
    OAuthStateStore,
    OAuthTransaction,
    ProviderConfiguration,
    _provider_configuration,
    _provider_identity,
    install_oauth_routes,
    oauth_callback_path,
    refresh_github_credential,
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


@pytest.mark.anyio
async def test_repository_connection_state_is_bound_to_an_owner() -> None:
    redis = FakeRedis()
    store = OAuthStateStore(redis_client=redis, state_key=b"a" * 32)
    owner_id = UUID("00000000-0000-0000-0000-000000000011")

    state, _, _ = await store.create(
        provider="github",
        destination="https://traceai.vercel.app",
        user_agent="test-agent",
        purpose=OAuthPurpose.REPOSITORY_CONNECTION,
        user_id=owner_id,
        session_id=UUID("00000000-0000-0000-0000-000000000012"),
    )

    transaction = await store.consume(state)

    assert transaction.purpose == OAuthPurpose.REPOSITORY_CONNECTION
    assert transaction.user_id == str(owner_id)
    assert transaction.session_id == "00000000-0000-0000-0000-000000000012"


def test_repository_connection_route_is_explicitly_registered() -> None:
    app = FastAPI()
    install_oauth_routes(app, AuthSettings(), audit_hasher=None)

    assert GITHUB_CONNECT_START_ROUTE in {route.path for route in app.routes}


def test_github_login_discards_provider_tokens(monkeypatch) -> None:
    configuration = ProviderConfiguration(
        provider="github",
        client_id="client",
        client_secret="secret",
        redirect_uri="https://trace.example/auth/oauth/github/callback",
        authorize_url="https://github.example/authorize",
        token_url="https://github.example/token",
        scope="read:user user:email",
        github_user_url="https://github.example/user",
        github_emails_url="https://github.example/emails",
    )
    monkeypatch.setattr(
        "auth.oauth._post_form",
        lambda _url, _values: {
            "access_token": "github-access-token",
            "refresh_token": "github-refresh-token",
        },
    )
    monkeypatch.setattr(
        "auth.oauth._get_json",
        lambda url, _token: (
            {"id": 123}
            if url.endswith("/user")
            else [{"email": "owner@example.test", "primary": True, "verified": True}]
        ),
    )

    identity = _provider_identity(
        configuration,
        "authorization-code",
        OAuthTransaction(
            provider="github",
            verifier="verifier",
            nonce=None,
            destination="https://trace.example",
            user_agent_hash="hash",
        ),
    )

    assert identity.subject == "123"
    assert identity.credential_payload is None


def test_github_repository_connection_retains_only_provider_token_payload(
    monkeypatch,
) -> None:
    configuration = ProviderConfiguration(
        provider="github",
        client_id="client",
        client_secret="secret",
        redirect_uri="https://trace.example/auth/oauth/github/callback",
        authorize_url="https://github.example/authorize",
        token_url="https://github.example/token",
        scope="read:user user:email repo",
        github_user_url="https://github.example/user",
        github_emails_url="https://github.example/emails",
    )
    monkeypatch.setattr(
        "auth.oauth._post_form",
        lambda _url, _values: {
            "access_token": "github-access-token",
            "refresh_token": "github-refresh-token",
            "expires_in": 28_800,
        },
    )
    monkeypatch.setattr(
        "auth.oauth._get_json",
        lambda url, _token: (
            {"id": 123}
            if url.endswith("/user")
            else [{"email": "owner@example.test", "primary": True, "verified": True}]
        ),
    )

    identity = _provider_identity(
        configuration,
        "authorization-code",
        OAuthTransaction(
            provider="github",
            verifier="verifier",
            nonce=None,
            destination="https://trace.example",
            user_agent_hash="hash",
            purpose=OAuthPurpose.REPOSITORY_CONNECTION,
            user_id="00000000-0000-0000-0000-000000000011",
            session_id="00000000-0000-0000-0000-000000000012",
        ),
    )

    assert identity.credential_payload is not None
    assert identity.credential_payload["access_token"] == "github-access-token"
    assert identity.credential_payload["refresh_token"] == "github-refresh-token"
    assert identity.credential_payload["expires_in"] == 28_800
    assert isinstance(identity.credential_payload["access_token_expires_at"], str)


def test_github_refresh_replaces_the_encrypted_payload(monkeypatch) -> None:
    class FakeCredentialService:
        def __init__(self) -> None:
            self.replaced: dict[str, object] | None = None

        def decrypt_for_provider_call(self, *, owner_id, credential_id):
            return {"refresh_token": "old-refresh-token"}

        def replace_payload(self, *, owner_id, credential_id, payload):
            self.replaced = payload

    service = FakeCredentialService()
    settings = AuthSettings(
        github_client_id="github-client",
        github_client_secret=SecretStr("github-secret"),
        github_redirect_uri="https://trace.example/auth/oauth/github/callback",
    )
    monkeypatch.setattr(
        "auth.oauth._post_form",
        lambda _url, values: (
            {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
            }
            if values["grant_type"] == "refresh_token"
            else {}
        ),
    )

    refreshed = refresh_github_credential(
        service=service,
        settings=settings,
        owner_id=UUID("00000000-0000-0000-0000-000000000011"),
        credential_id=UUID("00000000-0000-0000-0000-000000000010"),
    )

    assert refreshed["access_token"] == "new-access-token"
    assert refreshed["refresh_token"] == "new-refresh-token"
    assert service.replaced == refreshed


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
