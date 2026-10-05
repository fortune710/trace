from base64 import urlsafe_b64encode
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient
from pydantic import SecretStr

from auth.config import AuthSettings, AuthenticationConfigurationError, PRODUCTION_FRONTEND_ORIGINS
from auth.cookies import set_auth_cookies
from auth.credentials import VaultTransitCredentialCipher, credential_cipher_from_settings
from auth.csrf import issue_csrf_token, validate_csrf_token
from auth.errors import AuthError, install_auth_error_handlers
from main import create_app


def _encoded_key(byte: bytes) -> str:
    return urlsafe_b64encode(byte * 32).decode("ascii").rstrip("=")


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

    assert isinstance(credential_cipher_from_settings(settings), VaultTransitCredentialCipher)


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

    response = TestClient(app).get("/protected", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert "secret-token" not in response.text


def test_startup_rejects_incomplete_authentication_configuration() -> None:
    application = create_app(AuthSettings())

    with pytest.raises(AuthenticationConfigurationError):
        with TestClient(application):
            pass


def test_production_cors_allows_only_the_approved_frontends() -> None:
    settings = AuthSettings(
        environment="production",
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

    with TestClient(create_app(settings)) as client:
        allowed = client.get("/health", headers={"Origin": "https://traceai.vercel.app"})
        denied = client.get("/health", headers={"Origin": "https://untrusted.example"})

    assert allowed.headers["access-control-allow-origin"] == "https://traceai.vercel.app"
    assert "access-control-allow-origin" not in denied.headers


def test_authentication_response_sets_both_http_only_credentials() -> None:
    response = Response()
    settings = AuthSettings(cookie_secure=False, access_cookie_name="trace_access", refresh_cookie_name="trace_refresh")

    set_auth_cookies(response, access_token="access-token", refresh_token="refresh-token", settings=settings)

    cookies = [value.decode("latin-1") for key, value in response.raw_headers if key == b"set-cookie"]
    assert any(cookie.startswith("trace_access=access-token") and "HttpOnly" in cookie for cookie in cookies)
    assert any(cookie.startswith("trace_refresh=refresh-token") and "HttpOnly" in cookie for cookie in cookies)
