from uuid import UUID

import pytest

from auth.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    EncryptedCredential,
    VaultTransitCredentialCipher,
)


class FakeVaultTransitClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.context: str | None = None

    def write(self, path: str, payload: dict[str, str]) -> dict[str, object]:
        self.calls.append((path, payload))
        if path.startswith("transit/encrypt/"):
            self.context = payload["context"]
            return {"ciphertext": "vault:v3:opaque-ciphertext"}
        if path.startswith("transit/decrypt/"):
            if payload["context"] != self.context:
                raise ValueError("invalid ciphertext")
            return {
                "plaintext": "eyJhY2Nlc3NfdG9rZW4iOiJwcm92aWRlci1hY2Nlc3MtdG9rZW4ifQ=="
            }
        raise AssertionError(f"Unexpected Vault path: {path}")

    def rewrap(self, *, mount: str, key: str, ciphertext: str, context: str) -> str:
        self.calls.append(
            (
                f"{mount}/rewrap/{key}",
                {"ciphertext": ciphertext, "context": context},
            )
        )
        return "vault:v4:rewrapped-ciphertext"

    def latest_version(self, *, mount: str, key: str) -> str:
        self.calls.append((f"{mount}/keys/{key}", {}))
        return "v4"


def test_provider_tokens_are_encrypted_and_bound_to_their_owner() -> None:
    cipher = CredentialCipher(key=b"c" * 32, key_version="test-v1")
    credential_id = UUID("00000000-0000-0000-0000-000000000010")
    owner_id = UUID("00000000-0000-0000-0000-000000000011")
    value = {
        "access_token": "provider-access-token",
        "refresh_token": "provider-refresh-token",
    }

    encrypted = cipher.encrypt_json(
        value,
        credential_id=credential_id,
        owner_id=owner_id,
        provider="github",
        credential_kind="oauth",
    )

    assert b"provider-access-token" not in encrypted.ciphertext
    assert (
        cipher.decrypt_json(
            encrypted,
            credential_id=credential_id,
            owner_id=owner_id,
            provider="github",
            credential_kind="oauth",
        )
        == value
    )
    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt_json(
            encrypted,
            credential_id=credential_id,
            owner_id=UUID("00000000-0000-0000-0000-000000000012"),
            provider="github",
            credential_kind="oauth",
        )


def test_vault_transit_encrypts_provider_tokens_with_owner_bound_context() -> None:
    client = FakeVaultTransitClient()
    cipher = VaultTransitCredentialCipher(
        client=client, mount="transit", key="trace-provider-credentials"
    )
    credential_id = UUID("00000000-0000-0000-0000-000000000010")
    owner_id = UUID("00000000-0000-0000-0000-000000000011")
    value = {"access_token": "provider-access-token"}

    encrypted = cipher.encrypt_json(
        value,
        credential_id=credential_id,
        owner_id=owner_id,
        provider="github",
        credential_kind="oauth",
    )

    assert encrypted.encryption_provider == "vault"
    assert encrypted.key_reference == "transit/trace-provider-credentials"
    assert encrypted.key_version == "v3"
    assert b"provider-access-token" not in encrypted.ciphertext
    assert client.calls[0][0] == "transit/encrypt/trace-provider-credentials"
    assert "provider-access-token" not in str(client.calls[0][1])
    assert (
        cipher.decrypt_json(
            encrypted,
            credential_id=credential_id,
            owner_id=owner_id,
            provider="github",
            credential_kind="oauth",
        )
        == value
    )
    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt_json(
            encrypted,
            credential_id=credential_id,
            owner_id=UUID("00000000-0000-0000-0000-000000000012"),
            provider="github",
            credential_kind="oauth",
        )


def test_local_cipher_can_rewrap_a_retired_key_version() -> None:
    credential_id = UUID("00000000-0000-0000-0000-000000000010")
    owner_id = UUID("00000000-0000-0000-0000-000000000011")
    old_cipher = CredentialCipher(key=b"a" * 32, key_version="local-v1")
    new_cipher = CredentialCipher(
        key=b"b" * 32,
        key_version="local-v2",
        verification_keys={"local-v1": b"a" * 32},
    )
    encrypted = old_cipher.encrypt_json(
        {"api_key": "provider-api-key"},
        credential_id=credential_id,
        owner_id=owner_id,
        provider="openai",
        credential_kind="api_key",
    )

    rewrapped = new_cipher.rewrap_json(
        encrypted,
        credential_id=credential_id,
        owner_id=owner_id,
        provider="openai",
        credential_kind="api_key",
    )

    assert rewrapped.key_version == "local-v2"
    assert new_cipher.decrypt_json(
        rewrapped,
        credential_id=credential_id,
        owner_id=owner_id,
        provider="openai",
        credential_kind="api_key",
    ) == {"api_key": "provider-api-key"}


def test_vault_transit_rewraps_without_decrypting_in_application() -> None:
    client = FakeVaultTransitClient()
    cipher = VaultTransitCredentialCipher(
        client=client, mount="transit", key="trace-provider-credentials"
    )
    encrypted = EncryptedCredential(
        ciphertext=b"vault:v3:opaque-ciphertext",
        nonce=b"",
        key_version="v3",
        encryption_provider="vault",
        key_reference="transit/trace-provider-credentials",
    )

    rewrapped = cipher.rewrap_json(
        encrypted,
        credential_id=UUID("00000000-0000-0000-0000-000000000010"),
        owner_id=UUID("00000000-0000-0000-0000-000000000011"),
        provider="github",
        credential_kind="oauth",
    )

    assert rewrapped.key_version == "v4"
    assert rewrapped.ciphertext == b"vault:v4:rewrapped-ciphertext"
    assert client.calls[-1][0] == "transit/rewrap/trace-provider-credentials"


def test_vault_transit_reports_the_active_key_version() -> None:
    client = FakeVaultTransitClient()
    cipher = VaultTransitCredentialCipher(
        client=client, mount="transit", key="trace-provider-credentials"
    )

    assert cipher.active_key_version == "v4"
    assert client.calls[-1][0] == "transit/keys/trace-provider-credentials"
