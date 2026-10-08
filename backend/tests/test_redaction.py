from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from urllib.error import URLError
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from audit.emit import enqueue_audit
from audit.store import AuditEvent, canonical_event_json
from auth.audit import log_auth_event
from auth.credential_service import CredentialMetadata, CredentialServiceError
from auth.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    CredentialEncryptionUnavailable,
    EncryptedCredential,
    VaultTransitClient,
)
from auth.errors import AuthError, ResourceUnavailable, install_auth_error_handlers
from auth.oauth import OAuthUnavailable, _read_json
from credentials.models import (
    CredentialEncryptionProvider,
    CredentialKind,
    CredentialProvider,
)
from resources.routes import _credential_operation, _credential_response

pytestmark = pytest.mark.security


# These are deterministic synthetic values. They must never be real credentials.
SECRET_CORPUS = (
    "gho_test_redaction_7f3c9a",
    "ghr_test_refresh_91ab42",
    "sk-test_redaction_d84e11",
    "hvs.test_redaction_5aa901",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature123",
    "vault:v7:ciphertext_test_4e91",
    "raw_request_body_secret_77bd",
    "provider_response_secret_33fa",
)

FORBIDDEN_FIELDS = {
    "access_token",
    "refresh_token",
    "api_key",
    "client_secret",
    "ciphertext",
    "nonce",
    "vault_reference",
    "decrypted_payload",
    "request_body",
}


def _serialized(value: object) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def assert_no_secrets(value: object) -> None:
    serialized = _serialized(value)
    for secret in SECRET_CORPUS:
        assert secret not in serialized


def assert_no_forbidden_fields(value: object) -> None:
    if isinstance(value, dict):
        assert not FORBIDDEN_FIELDS & {str(key).lower() for key in value}
        for nested in value.values():
            assert_no_forbidden_fields(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            assert_no_forbidden_fields(nested)


@pytest.mark.parametrize(
    "field",
    sorted(
        {
            "access_token",
            "client_secret",
            "raw_request_body",
            "ciphertext",
            "private_key",
        }
    ),
)
def test_audit_events_reject_sensitive_field_names(field: str) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        AuditEvent(
            event_type="credential.created",
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            request_id="request-redaction",
            owner_id=uuid4(),
            fields={field: "synthetic-secret"},
        )


@pytest.mark.parametrize("secret", SECRET_CORPUS[:6])
def test_audit_events_reject_common_secret_values(secret: str) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        AuditEvent(
            event_type="credential.created",
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            request_id="request-redaction",
            owner_id=uuid4(),
            fields={"provider": secret},
        )


def test_audit_serialization_contains_only_safe_metadata() -> None:
    event = AuditEvent(
        event_type="credential.rotated",
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        request_id="request-redaction",
        owner_id=uuid4(),
        fields={"provider": "github", "operation": "rotate"},
    )

    payload = canonical_event_json(event)
    assert_no_secrets(payload)
    assert_no_forbidden_fields(json.loads(payload))


def test_outbox_event_creation_rejects_secret_fields_before_storage() -> None:
    from audit.outbox import AuditRecorder

    recorder = AuditRecorder(engine=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sensitive"):
        recorder.create_event(
            event_type="credential.created",
            request_id="request-redaction",
            owner_id=uuid4(),
            fields={"access_token": SECRET_CORPUS[0]},
        )


def test_credential_metadata_response_is_secret_safe() -> None:
    metadata = CredentialMetadata(
        id=uuid4(),
        owner_id=uuid4(),
        provider=CredentialProvider.GITHUB,
        kind=CredentialKind.OAUTH,
        encryption_provider=CredentialEncryptionProvider.VAULT,
        key_version="v1",
        aad_version="v1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        revoked_at=None,
    )

    response = _credential_response(metadata)
    assert_no_secrets(response)
    assert_no_forbidden_fields(response)


def test_auth_error_response_does_not_echo_request_or_provider_secrets() -> None:
    app = FastAPI()
    install_auth_error_handlers(app)

    @app.get("/provider")
    def provider_failure() -> None:
        raise AuthError(
            code="resource_unavailable",
            message="The resource operation is temporarily unavailable.",
            status_code=503,
            event="resource",
            reason="dependency_unavailable",
        )

    response = TestClient(app).get(
        "/provider",
        headers={"Authorization": f"Bearer {SECRET_CORPUS[0]}"},
    )

    assert response.status_code == 503
    assert_no_secrets(response.json())
    assert_no_forbidden_fields(response.json())


def test_auth_audit_hashes_identity_and_ignores_secret_values(caplog) -> None:
    caplog.set_level(logging.INFO, logger="trace.auth")

    log_auth_event(
        event="access",
        outcome="rejected",
        reason="token_invalid",
        request_id="request-redaction",
        route="/api/v1/projects",
        status_code=401,
        identity=SECRET_CORPUS[0],
        ip_address=SECRET_CORPUS[1],
        user_agent=SECRET_CORPUS[2],
        context={"provider": "github", "policy": "safe.policy"},
    )

    assert_no_secrets(caplog.text)


def test_audit_enqueue_failure_does_not_log_exception_text(caplog) -> None:
    class FailingRecorder:
        def create_event(self, **_: object) -> None:
            raise RuntimeError(SECRET_CORPUS[3])

    caplog.set_level(logging.ERROR, logger="trace.audit")
    enqueue_audit(
        FailingRecorder(),
        event_type="credential.rotated",
        request_id="request-redaction",
        owner_id=uuid4(),
        fields={"provider": "github"},
    )

    assert "audit_enqueue_failed" in caplog.text
    assert_no_secrets(caplog.text)


def test_credential_service_errors_are_mapped_to_generic_safe_errors() -> None:
    with pytest.raises(ResourceUnavailable) as raised:
        _credential_operation(
            lambda: (_ for _ in ()).throw(CredentialServiceError(SECRET_CORPUS[6]))
        )

    assert_no_secrets(str(raised.value))
    assert str(raised.value) == "resource_unavailable"


def test_local_cipher_decryption_failure_does_not_echo_ciphertext() -> None:
    cipher = CredentialCipher(key=b"c" * 32, key_version="test-v1")
    encrypted = EncryptedCredential(
        ciphertext=SECRET_CORPUS[5].encode(),
        nonce=b"n" * 12,
        key_version="test-v1",
    )

    with pytest.raises(CredentialDecryptionError) as raised:
        cipher.decrypt_json(
            encrypted,
            credential_id=uuid4(),
            owner_id=uuid4(),
            provider="github",
            credential_kind="oauth",
        )

    assert_no_secrets(str(raised.value))


def test_vault_transport_failure_does_not_echo_secret_error(
    caplog, monkeypatch
) -> None:
    def fail_request(*_: object, **__: object) -> None:
        raise URLError(SECRET_CORPUS[4])

    monkeypatch.setattr("auth.credentials.urlopen", fail_request)
    client = VaultTransitClient(
        address="https://vault.example.test",
        token=SECRET_CORPUS[3],
        timeout_seconds=1,
    )

    with pytest.raises(CredentialEncryptionUnavailable) as raised:
        client.write("transit/encrypt/test", {"plaintext": "safe"})

    assert_no_secrets(str(raised.value))
    assert_no_secrets(caplog.text)


def test_provider_transport_failure_does_not_echo_secret_error(monkeypatch) -> None:
    def fail_request(*_: object, **__: object) -> None:
        raise URLError(SECRET_CORPUS[7])

    monkeypatch.setattr("auth.oauth.urlopen", fail_request)

    with pytest.raises(OAuthUnavailable) as raised:
        _read_json(object())  # type: ignore[arg-type]

    assert_no_secrets(str(raised.value))
