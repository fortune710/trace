from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from auth.config import AuthSettings
from auth.oauth import (
    GITHUB_CONNECT_START_ROUTE,
    LINEAR_CONNECT_START_ROUTE,
    OAUTH_CALLBACK_ROUTE,
    GitHubConnectionStatus,
    OAuthPurpose,
    OAuthRejected,
    OAuthStateStore,
    OAuthTransaction,
    ProviderConfiguration,
    _connection_redirect,
    _provider_configuration,
    _provider_identity,
    _repository_connection_redirect,
    get_github_connection_status,
    install_oauth_routes,
    oauth_callback_path,
    refresh_github_credential,
)
from credentials.models import CredentialKind, CredentialProvider


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


@pytest.mark.anyio
async def test_linear_issue_connection_state_is_bound_to_an_owner() -> None:
    redis = FakeRedis()
    store = OAuthStateStore(redis_client=redis, state_key=b"a" * 32)
    owner_id = UUID("00000000-0000-0000-0000-000000000021")

    state, _, nonce = await store.create(
        provider="linear",
        destination="https://traceai.vercel.app",
        user_agent="test-agent",
        purpose=OAuthPurpose.ISSUE_TRACKING_CONNECTION,
        user_id=owner_id,
        session_id=UUID("00000000-0000-0000-0000-000000000022"),
    )
    transaction = await store.consume(state)

    assert nonce is None
    assert transaction.purpose is OAuthPurpose.ISSUE_TRACKING_CONNECTION
    assert transaction.user_id == str(owner_id)


def test_repository_connection_route_is_explicitly_registered() -> None:
    app = FastAPI()
    install_oauth_routes(app, AuthSettings(), audit_hasher=None)

    paths = {route.path for route in app.routes}

    assert GITHUB_CONNECT_START_ROUTE in paths
    assert LINEAR_CONNECT_START_ROUTE in paths
    assert "/auth/oauth/github/connection" in paths


def test_github_repository_connection_requests_the_documented_scope() -> None:
    settings = AuthSettings(
        github_client_id="github-client-id",
        github_client_secret=SecretStr("github-client-secret"),
        github_redirect_uri="https://trace.example/auth/oauth/github/callback",
    )

    sign_in = _provider_configuration(settings, "github")
    repository_connection = _provider_configuration(
        settings,
        "github",
        purpose=OAuthPurpose.REPOSITORY_CONNECTION,
    )

    assert sign_in.scope == "read:user user:email"
    assert repository_connection.scope == "read:user user:email repo"


def test_linear_issue_connection_requests_documented_scopes() -> None:
    settings = AuthSettings(
        linear_client_id="linear-client-id",
        linear_client_secret=SecretStr("linear-client-secret"),
        linear_redirect_uri="https://trace.example/auth/oauth/linear/callback",
    )

    configuration = _provider_configuration(
        settings,
        "linear",
        purpose=OAuthPurpose.ISSUE_TRACKING_CONNECTION,
    )

    assert configuration.scope == "read,issues:create"


def test_repository_connection_redirects_always_return_to_integrations() -> None:
    success = _repository_connection_redirect(
        "https://trace.example", outcome="connected", request_id="request-123"
    )
    failure = _repository_connection_redirect(
        "https://trace.example", outcome="failed", request_id="request-123"
    )

    assert success.status_code == 303
    assert success.headers["location"] == (
        "https://trace.example/integrations?github=connected&request_id=request-123"
    )
    assert failure.headers["location"] == (
        "https://trace.example/integrations?github=failed&request_id=request-123"
    )


def test_linear_connection_redirect_uses_the_linear_outcome_key() -> None:
    response = _connection_redirect(
        "https://trace.example",
        outcome="connected",
        request_id="request-123",
        provider="linear",
    )

    assert response.headers["location"] == (
        "https://trace.example/integrations?linear=connected&request_id=request-123"
    )


class FakeGitHubCredentialService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.metadata_value = SimpleNamespace(
            revoked_at=None,
            provider=CredentialProvider.GITHUB,
            kind=CredentialKind.OAUTH,
        )

    def metadata(self, *, owner_id, credential_id):
        return self.metadata_value

    def decrypt_for_provider_call(self, *, owner_id, credential_id):
        return self.payload


def test_github_connection_status_distinguishes_never_connected_and_valid_tokens(
    monkeypatch,
) -> None:
    owner_id = UUID("00000000-0000-0000-0000-000000000011")
    service = FakeGitHubCredentialService({"access_token": "token"})
    monkeypatch.setattr("auth.oauth._latest_github_connection", lambda **_kwargs: None)

    assert (
        get_github_connection_status(
            engine=object(), service=service, settings=AuthSettings(), owner_id=owner_id
        )
        == GitHubConnectionStatus.NEVER_CONNECTED
    )

    monkeypatch.setattr(
        "auth.oauth._latest_github_connection",
        lambda **_kwargs: {
            "credential_id": UUID("00000000-0000-0000-0000-000000000010"),
            "revoked_at": None,
        },
    )
    assert (
        get_github_connection_status(
            engine=object(), service=service, settings=AuthSettings(), owner_id=owner_id
        )
        == GitHubConnectionStatus.CONNECTED
    )

    service.payload = {
        "access_token": "token",
        "access_token_expires_at": (
            datetime.now(UTC) + timedelta(minutes=5)
        ).isoformat(),
    }
    assert (
        get_github_connection_status(
            engine=object(), service=service, settings=AuthSettings(), owner_id=owner_id
        )
        == GitHubConnectionStatus.CONNECTED
    )


def test_github_connection_status_refreshes_expired_tokens_or_requires_reconnection(
    monkeypatch,
) -> None:
    owner_id = UUID("00000000-0000-0000-0000-000000000011")
    credential_id = UUID("00000000-0000-0000-0000-000000000010")
    service = FakeGitHubCredentialService(
        {
            "access_token": "expired-token",
            "access_token_expires_at": (
                datetime.now(UTC) - timedelta(minutes=5)
            ).isoformat(),
        }
    )
    monkeypatch.setattr(
        "auth.oauth._latest_github_connection",
        lambda **_kwargs: {"credential_id": credential_id, "revoked_at": None},
    )
    refreshed: list[UUID] = []

    def refresh(**kwargs):
        refreshed.append(kwargs["credential_id"])
        return {"access_token": "fresh-token"}

    monkeypatch.setattr("auth.oauth.refresh_github_credential", refresh)
    assert (
        get_github_connection_status(
            engine=object(), service=service, settings=AuthSettings(), owner_id=owner_id
        )
        == GitHubConnectionStatus.CONNECTED
    )
    assert refreshed == [credential_id]

    def reject(**_kwargs):
        raise OAuthRejected("credential refresh rejected")

    monkeypatch.setattr("auth.oauth.refresh_github_credential", reject)
    assert (
        get_github_connection_status(
            engine=object(), service=service, settings=AuthSettings(), owner_id=owner_id
        )
        == GitHubConnectionStatus.NEEDS_RECONNECTION
    )


def test_github_connection_status_requires_reconnection_for_revoked_or_invalid_state(
    monkeypatch,
) -> None:
    owner_id = UUID("00000000-0000-0000-0000-000000000011")
    service = FakeGitHubCredentialService({"access_token": "token"})
    monkeypatch.setattr(
        "auth.oauth._latest_github_connection",
        lambda **_kwargs: {
            "credential_id": UUID("00000000-0000-0000-0000-000000000010"),
            "revoked_at": datetime.now(UTC),
        },
    )

    assert (
        get_github_connection_status(
            engine=object(), service=service, settings=AuthSettings(), owner_id=owner_id
        )
        == GitHubConnectionStatus.NEEDS_RECONNECTION
    )

    monkeypatch.setattr(
        "auth.oauth._latest_github_connection",
        lambda **_kwargs: {
            "credential_id": UUID("00000000-0000-0000-0000-000000000010"),
            "revoked_at": None,
        },
    )
    service.payload = {"access_token": ""}
    assert (
        get_github_connection_status(
            engine=object(), service=service, settings=AuthSettings(), owner_id=owner_id
        )
        == GitHubConnectionStatus.NEEDS_RECONNECTION
    )


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


def test_google_login_extracts_a_bounded_display_name(monkeypatch) -> None:
    configuration = ProviderConfiguration(
        provider="google",
        client_id="client",
        client_secret="secret",
        redirect_uri="https://trace.example/auth/oauth/google/callback",
        authorize_url="https://google.example/authorize",
        token_url="https://google.example/token",
        scope="openid email profile",
        google_jwks_url="https://google.example/jwks",
    )

    class SigningKey:
        key = object()

    class FakeJWKClient:
        def __init__(self, _url: str, *, cache_keys: bool) -> None:
            assert cache_keys is True

        def get_signing_key_from_jwt(self, _token: str) -> SigningKey:
            return SigningKey()

    monkeypatch.setattr("auth.oauth.PyJWKClient", FakeJWKClient)
    monkeypatch.setattr(
        "auth.oauth._post_form",
        lambda _url, _values: {
            "access_token": "google-access-token",
            "id_token": "id-token",
        },
    )
    monkeypatch.setattr(
        "auth.oauth.jwt.decode",
        lambda *_args, **_kwargs: {
            "email": "owner@example.test",
            "email_verified": True,
            "iss": "https://accounts.google.com",
            "name": "  Google User  ",
            "nonce": "nonce",
            "sub": "google-subject",
        },
    )

    identity = _provider_identity(
        configuration,
        "authorization-code",
        OAuthTransaction(
            provider="google",
            verifier="verifier",
            nonce="nonce",
            destination="https://trace.example",
            user_agent_hash="hash",
        ),
    )

    assert identity.subject == "google-subject"
    assert identity.email == "owner@example.test"
    assert identity.display_name == "Google User"


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


def test_linear_issue_connection_retains_provider_token_payload(monkeypatch) -> None:
    configuration = ProviderConfiguration(
        provider="linear",
        client_id="client",
        client_secret="secret",
        redirect_uri="https://trace.example/auth/oauth/linear/callback",
        authorize_url="https://linear.example/authorize",
        token_url="https://linear.example/token",
        scope="read,issues:create",
        linear_api_url="https://linear.example/graphql",
    )
    monkeypatch.setattr(
        "auth.oauth._post_form",
        lambda _url, _values: {
            "access_token": "linear-access-token",
            "refresh_token": "linear-refresh-token",
            "expires_in": 28_800,
        },
    )
    monkeypatch.setattr(
        "auth.oauth._linear_viewer",
        lambda _url, _token: {"id": "linear-viewer-id"},
    )

    identity = _provider_identity(
        configuration,
        "authorization-code",
        OAuthTransaction(
            provider="linear",
            verifier="verifier",
            nonce=None,
            destination="https://trace.example",
            user_agent_hash="hash",
            purpose=OAuthPurpose.ISSUE_TRACKING_CONNECTION,
            user_id="00000000-0000-0000-0000-000000000011",
            session_id="00000000-0000-0000-0000-000000000012",
        ),
    )

    assert identity.subject == "linear-viewer-id"
    assert identity.credential_payload is not None
    assert identity.credential_payload["access_token"] == "linear-access-token"
    assert identity.credential_payload["refresh_token"] == "linear-refresh-token"


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


@pytest.mark.parametrize(
    ("code", "verifier"),
    [
        ("c" * 15, "v" * 43),
        ("c" * 513, "v" * 43),
        ("c" * 43, "v" * 42),
        ("c" * 43, "v" * 129),
        ("c" * 100_000, "v" * 100_000),
        ("", ""),
    ],
    ids=[
        "code-too-short",
        "code-too-long",
        "verifier-too-short",
        "verifier-too-long",
        "oversized-body",
        "empty",
    ],
)
def test_desktop_exchange_bounds_unauthenticated_fields_before_any_lookup(
    monkeypatch, code: str, verifier: str
) -> None:
    import auth.oauth as oauth_module
    from auth.errors import install_auth_error_handlers

    def redis_must_not_be_used():
        raise AssertionError("an out-of-range field reached the Redis lookup")

    monkeypatch.setattr(oauth_module, "get_redis_client", redis_must_not_be_used)
    app = FastAPI()
    install_auth_error_handlers(app)
    install_oauth_routes(app, AuthSettings(), audit_hasher=None)

    response = TestClient(app).post(
        "/auth/oauth/desktop/exchange", json={"code": code, "verifier": verifier}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    ("code", "verifier"),
    [("c" * 16, "v" * 43), ("c" * 512, "v" * 128)],
    ids=["minimum-lengths", "maximum-lengths"],
)
def test_desktop_exchange_accepts_the_documented_field_bounds(
    monkeypatch, code: str, verifier: str
) -> None:
    import auth.oauth as oauth_module
    from auth.errors import install_auth_error_handlers

    monkeypatch.setattr(oauth_module, "get_redis_client", lambda: FakeRedis())
    app = FastAPI()
    install_auth_error_handlers(app)
    install_oauth_routes(app, AuthSettings(), audit_hasher=None)

    response = TestClient(app).post(
        "/auth/oauth/desktop/exchange", json={"code": code, "verifier": verifier}
    )

    # Within bounds the request is processed; an unknown ticket is simply rejected.
    assert response.status_code == 401


class _RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def create_event(self, **kwargs: object) -> None:
        self.events.append(kwargs)

    def reasons(self) -> list[tuple[str, str, str]]:
        return [
            (
                str(event["event_type"]),
                str(event["fields"]["reason"]),  # type: ignore[index]
                str(event["fields"]["status_code"]),  # type: ignore[index]
            )
            for event in self.events
        ]


def _desktop_oauth_client(monkeypatch):
    import base64

    import auth.oauth as oauth_module
    from auth.errors import install_auth_error_handlers

    redis = FakeRedis()
    monkeypatch.setattr(oauth_module, "get_redis_client", lambda: redis)

    async def allowed(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(oauth_module, "enforce_rate_limit", allowed)
    monkeypatch.setattr(oauth_module, "rate_limiter_from_settings", lambda _: None)
    settings = AuthSettings(
        github_client_id="github-test-client",
        github_client_secret=SecretStr("github-test-secret"),
        github_redirect_uri="https://api.example.test/auth/oauth/github/callback",
        token_hash_key=SecretStr(
            base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
        ),
    )
    audit = _RecordingAudit()
    app = FastAPI()
    install_auth_error_handlers(app)
    install_oauth_routes(
        app,
        settings,
        audit_hasher=None,
        audit_recorder=audit,  # type: ignore[arg-type]
    )
    return TestClient(app, follow_redirects=False), redis, audit, oauth_module


def _desktop_ticket(redis: FakeRedis, verifier: str, *, ticket: str) -> None:
    import json
    from dataclasses import asdict

    from auth.oauth import _pkce_challenge

    transaction = OAuthTransaction(
        provider="github",
        verifier=_pkce_challenge(verifier),
        nonce=None,
        destination="trace://oauth/callback",
        user_agent_hash="hash",
        desktop=True,
    )
    redis.values[f"trace:oauth:desktop:{ticket}"] = json.dumps(
        {"code": "provider-code", "transaction": asdict(transaction)}
    )


def test_desktop_authorization_start_and_ticket_issuance_are_audited(
    monkeypatch,
) -> None:
    client, _, audit, _ = _desktop_oauth_client(monkeypatch)

    started = client.get(
        "/auth/oauth/github/desktop/start", params={"challenge": "c" * 43}
    )
    assert started.status_code == 302
    assert audit.reasons() == [("oauth.oauth", "authorization_started", "302")]

    callback = client.get(
        "/auth/oauth/github/callback",
        params={"state": _state_from(started.headers["location"]), "code": "provider"},
    )
    assert callback.status_code == 303
    assert callback.headers["location"].startswith("trace://oauth/callback?code=")
    assert audit.reasons()[-1] == ("oauth.oauth", "desktop_ticket_issued", "303")
    ticket = callback.headers["location"].split("code=")[-1]
    # The single-use ticket is a credential and never appears in audit fields.
    assert ticket not in repr(audit.events)


def _state_from(location: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(location).query)["state"][0]


def test_desktop_exchange_audits_success_rejection_and_unavailability(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    import auth.oauth as oauth_module
    from auth.oauth import OAuthUnavailable, ProviderIdentity
    from auth.service import SessionTokens

    client, redis, audit, _ = _desktop_oauth_client(monkeypatch)
    verifier = "v" * 43
    session = SessionTokens("access", "refresh", UUID(int=1))
    monkeypatch.setattr(oauth_module, "get_engine", lambda: None)
    monkeypatch.setattr(
        oauth_module.AuthService,
        "from_settings",
        classmethod(
            lambda cls, **kwargs: SimpleNamespace(
                oauth_login=lambda **values: SimpleNamespace(tokens=session)
            )
        ),
    )
    monkeypatch.setattr(oauth_module, "_set_session", lambda *args: "csrf-token")
    monkeypatch.setattr(
        oauth_module,
        "_provider_identity",
        lambda *args: ProviderIdentity(subject="1", email="user@example.test"),
    )

    # An unknown ticket is rejected.
    unknown = client.post(
        "/auth/oauth/desktop/exchange", json={"code": "u" * 43, "verifier": verifier}
    )
    assert unknown.status_code == 401

    # A valid ticket creates a session.
    _desktop_ticket(redis, verifier, ticket="s" * 43)
    ok = client.post(
        "/auth/oauth/desktop/exchange", json={"code": "s" * 43, "verifier": verifier}
    )
    assert ok.status_code == 200

    # A provider or dependency outage is reported as unavailable.
    def provider_down(*args):
        raise OAuthUnavailable("provider is down")

    monkeypatch.setattr(oauth_module, "_provider_identity", provider_down)
    _desktop_ticket(redis, verifier, ticket="d" * 43)
    down = client.post(
        "/auth/oauth/desktop/exchange", json={"code": "d" * 43, "verifier": verifier}
    )
    assert down.status_code == 503

    assert audit.reasons() == [
        ("oauth.oauth", "callback_rejected", "401"),
        ("oauth.oauth", "session_created", "200"),
        ("oauth.oauth", "dependency_unavailable", "503"),
    ]
    # Tickets, verifiers and tokens never reach the audit trail.
    recorded = repr(audit.events)
    for secret in (verifier, "s" * 43, "csrf-token", "access", "refresh"):
        assert secret not in recorded
    # The provider is attributed once the ticket identifies it.
    providers = [event["fields"]["provider"] for event in audit.events]  # type: ignore[index]
    assert providers == ["unknown", "github", "github"]
