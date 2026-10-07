from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient
from pydantic import SecretStr

import main
from auth.config import (
    PRODUCTION_FRONTEND_ORIGINS,
    AuthenticationConfigurationError,
    AuthSettings,
)
from auth.cookies import set_auth_cookies
from auth.credentials import (
    VaultTransitCredentialCipher,
    credential_cipher_from_settings,
)
from auth.csrf import issue_csrf_token, validate_csrf_token
from auth.errors import AuthError, AuthorizationDenied, install_auth_error_handlers
from auth.principal import CurrentPrincipal, install_principal_context
from auth.routes import install_auth_routes
from auth.tokens import AccessTokenClaims, InvalidAccessToken
from main import create_app


def _encoded_key(byte: bytes) -> str:
    return urlsafe_b64encode(byte * 32).decode("ascii").rstrip("=")


def test_auth_routes_bind_the_configured_cookie_names() -> None:
    app = FastAPI()
    settings = AuthSettings(
        access_cookie_name="test_access",
        refresh_cookie_name="test_refresh",
        csrf_cookie_name="test_csrf",
    )

    install_auth_routes(app, settings, audit_hasher=None)

    cookie_parameters = {
        route.path: {field.alias for field in route.dependant.cookie_params}
        for route in app.routes
        if hasattr(route, "dependant")
    }

    assert cookie_parameters["/auth/session"] == set()
    assert cookie_parameters["/auth/refresh"] == {"test_refresh", "test_csrf"}
    assert cookie_parameters["/auth/logout"] == {"test_refresh", "test_csrf"}


def test_approved_authentication_configuration_is_accepted() -> None:
    settings = AuthSettings(
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        credential_encryption_key=SecretStr(_encoded_key(b"c")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
    )

    settings.validate_for_authentication()


def test_production_rejects_insecure_cookie_configuration() -> None:
    settings = AuthSettings(
        environment="production",
        cookie_secure=False,
        access_cookie_name="trace_access",
        refresh_cookie_name="trace_refresh",
        allowed_origins=["https://app.example.test"],
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        credential_encryption_key=SecretStr(_encoded_key(b"c")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
    )

    with pytest.raises(AuthenticationConfigurationError):
        settings.validate_for_authentication()


def test_vault_is_a_valid_credential_encryption_provider() -> None:
    settings = AuthSettings(
        credential_encryption_provider="vault",
        vault_addr="http://vault:8200",
        vault_token=SecretStr("local-vault-token"),
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
    )

    assert isinstance(
        credential_cipher_from_settings(settings), VaultTransitCredentialCipher
    )


def test_production_rejects_unencrypted_vault_connections() -> None:
    settings = AuthSettings(
        environment="production",
        credential_encryption_provider="vault",
        vault_addr="http://vault.example.test",
        vault_token=SecretStr("production-vault-token"),
        cookie_same_site="none",
        allowed_origins=sorted(PRODUCTION_FRONTEND_ORIGINS),
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
    )

    with pytest.raises(AuthenticationConfigurationError):
        settings.validate_for_authentication()


def test_production_rejects_local_credential_encryption() -> None:
    settings = AuthSettings(
        environment="production",
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        credential_encryption_key=SecretStr(_encoded_key(b"c")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
    )

    with pytest.raises(AuthenticationConfigurationError):
        settings.validate_for_authentication()


def test_retired_credential_keys_must_be_distinct_valid_keys() -> None:
    settings = AuthSettings(
        credential_encryption_key_version="local-v2",
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        credential_encryption_key=SecretStr(_encoded_key(b"c")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
        credential_encryption_verification_keys={
            "local-v1": _encoded_key(b"f"),
        },
    )
    settings.validate_for_authentication()

    invalid = AuthSettings(
        credential_encryption_key_version="local-v2",
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        credential_encryption_key=SecretStr(_encoded_key(b"c")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
        credential_encryption_verification_keys={"local-v2": _encoded_key(b"a")},
    )
    with pytest.raises(AuthenticationConfigurationError):
        invalid.validate_for_authentication()


def test_only_test_environment_can_replace_oauth_provider_endpoints() -> None:
    settings = AuthSettings(
        github_authorize_url="http://oauth-stub:9000/github/authorize",
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        credential_encryption_key=SecretStr(_encoded_key(b"c")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
    )

    with pytest.raises(AuthenticationConfigurationError):
        settings.validate_for_authentication()


def test_csrf_token_is_bound_to_the_authenticated_session() -> None:
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    csrf_token = issue_csrf_token(session_id=session_id, key=b"a" * 32)

    assert validate_csrf_token(
        cookie_token=csrf_token,
        header_token=csrf_token,
        session_id=session_id,
        key=b"a" * 32,
    )
    assert not validate_csrf_token(
        cookie_token=csrf_token,
        header_token=csrf_token,
        session_id=UUID("00000000-0000-0000-0000-000000000002"),
        key=b"a" * 32,
    )


def test_authentication_errors_do_not_echo_secret_context() -> None:
    app = FastAPI()
    install_auth_error_handlers(app)

    @app.get("/protected")
    def protected_route() -> None:
        raise AuthError(
            code="authentication_failed",
            message="Unable to complete authentication.",
            status_code=401,
            event="access",
            reason="token_invalid",
        )

    response = TestClient(app).get(
        "/protected", headers={"Authorization": "Bearer secret-token"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert "secret-token" not in response.text


def test_authorization_denials_use_the_generic_error_contract() -> None:
    app = FastAPI()
    install_auth_error_handlers(app)

    @app.get("/owned-resource")
    def owned_resource() -> None:
        raise AuthorizationDenied()

    response = TestClient(app).get("/owned-resource")
    error = response.json()["error"]

    assert response.status_code == 403
    assert error["code"] == "authorization_denied"
    assert error["message"] == "You are not authorized to access this resource."
    assert error["request_id"]


class _FakeJWTService:
    def __init__(self, result) -> None:
        self.result = result

    def verify(self, _token: str):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _FakeSessionStatusReader:
    def __init__(self, active: bool) -> None:
        self.active = active

    async def is_active(self, *, user_id: UUID, session_id: UUID) -> bool:
        return self.active


def _principal_test_app(jwt_service, session_reader) -> FastAPI:
    app = FastAPI()
    install_auth_error_handlers(app)
    install_principal_context(
        app,
        access_cookie_name="test_access",
        jwt_service_factory=lambda: jwt_service,
        session_status_reader_factory=lambda: session_reader,
    )

    @app.get("/protected")
    async def protected(principal: CurrentPrincipal) -> dict[str, str]:
        return {"user_id": str(principal.user_id)}

    return app


def test_current_principal_dependency_reads_the_configured_cookie() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000101")
    claims = AccessTokenClaims(
        user_id=user_id,
        session_id=UUID("00000000-0000-0000-0000-000000000102"),
        token_id="token-id",
        issued_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    app = _principal_test_app(_FakeJWTService(claims), _FakeSessionStatusReader(True))

    response = TestClient(app).get("/protected", cookies={"test_access": "token"})

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id)}


@pytest.mark.parametrize(
    "mode",
    ["invalid", "revoked"],
)
def test_current_principal_dependency_uses_one_generic_401_contract(
    mode: str,
) -> None:
    claims = AccessTokenClaims(
        user_id=UUID("00000000-0000-0000-0000-000000000101"),
        session_id=UUID("00000000-0000-0000-0000-000000000102"),
        token_id="token-id",
        issued_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    jwt_result = InvalidAccessToken("invalid") if mode == "invalid" else claims
    app = _principal_test_app(
        _FakeJWTService(jwt_result), _FakeSessionStatusReader(mode != "revoked")
    )

    response = TestClient(app).get("/protected", cookies={"test_access": "token"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers["www-authenticate"] == "Bearer"


def test_startup_rejects_incomplete_authentication_configuration() -> None:
    application = create_app(AuthSettings())

    with pytest.raises(AuthenticationConfigurationError), TestClient(application):
        pass


def test_production_cors_allows_only_the_approved_frontends(monkeypatch) -> None:
    settings = AuthSettings(
        environment="production",
        credential_encryption_provider="vault",
        vault_addr="https://vault.example.test",
        vault_token=SecretStr("production-vault-token"),
        cookie_same_site="none",
        allowed_origins=sorted(PRODUCTION_FRONTEND_ORIGINS),
        frontend_url="https://traceai.vercel.app",
        smtp_host="smtp.example.test",
        rabbitmq_url="amqps://queue.example.test",
        jwt_private_key=SecretStr(_encoded_key(b"a")),
        token_hash_key=SecretStr(_encoded_key(b"b")),
        credential_encryption_key=SecretStr(_encoded_key(b"c")),
        csrf_hmac_key=SecretStr(_encoded_key(b"d")),
        audit_hash_key=SecretStr(_encoded_key(b"e")),
    )

    monkeypatch.setattr(main.VaultTransitClient, "renew_self", lambda self: None)

    with TestClient(create_app(settings)) as client:
        allowed = client.get(
            "/health", headers={"Origin": "https://traceai.vercel.app"}
        )
        denied = client.get("/health", headers={"Origin": "https://untrusted.example"})

    assert (
        allowed.headers["access-control-allow-origin"] == "https://traceai.vercel.app"
    )
    assert "access-control-allow-origin" not in denied.headers


def test_authentication_response_sets_both_http_only_credentials() -> None:
    response = Response()
    settings = AuthSettings(
        cookie_secure=False,
        access_cookie_name="trace_access",
        refresh_cookie_name="trace_refresh",
    )

    set_auth_cookies(
        response,
        access_token="access-token",
        refresh_token="refresh-token",
        settings=settings,
    )

    cookies = [
        value.decode("latin-1")
        for key, value in response.raw_headers
        if key == b"set-cookie"
    ]
    assert any(
        cookie.startswith("trace_access=access-token") and "HttpOnly" in cookie
        for cookie in cookies
    )
    assert any(
        cookie.startswith("trace_refresh=refresh-token") and "HttpOnly" in cookie
        for cookie in cookies
    )
