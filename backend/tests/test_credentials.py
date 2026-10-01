from uuid import UUID

import pytest

from auth.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
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
            return {"plaintext": "eyJhY2Nlc3NfdG9rZW4iOiJwcm92aWRlci1hY2Nlc3MtdG9rZW4ifQ=="}
        raise AssertionError(f"Unexpected Vault path: {path}")


def test_provider_tokens_are_encrypted_and_bound_to_their_owner() -> None:
    cipher = CredentialCipher(key=b"c" * 32, key_version="test-v1")
    credential_id = UUID("00000000-0000-0000-0000-000000000010")
    owner_id = UUID("00000000-0000-0000-0000-000000000011")
    value = {"access_token": "provider-access-token", "refresh_token": "provider-refresh-token"}

    encrypted = cipher.encrypt_json(
        value,
        credential_id=credential_id,
        owner_id=owner_id,
        provider="github",
        credential_kind="oauth",
    )

    assert b"provider-access-token" not in encrypted.ciphertext
    assert cipher.decrypt_json(
        encrypted,
        credential_id=credential_id,
        owner_id=owner_id,
        provider="github",
        credential_kind="oauth",
    ) == value
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
    cipher = VaultTransitCredentialCipher(client=client, mount="transit", key="trace-provider-credentials")
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
    assert cipher.decrypt_json(
        encrypted,
        credential_id=credential_id,
        owner_id=owner_id,
        provider="github",
        credential_kind="oauth",
    ) == value
    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt_json(
            encrypted,
            credential_id=credential_id,
            owner_id=UUID("00000000-0000-0000-0000-000000000012"),
            provider="github",
            credential_kind="oauth",
        )
