from __future__ import annotations

import base64
import binascii
import json
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from auth.config import AuthSettings
from auth.tokens import decode_base64url_key


class CredentialDecryptionError(ValueError):
    """Raised without revealing whether ciphertext, key, or AAD was invalid."""


class CredentialEncryptionUnavailable(RuntimeError):
    """Raised when the configured credential-encryption service cannot be used."""


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: bytes
    nonce: bytes
    key_version: str
    aad_version: str = "v1"
    encryption_provider: str = "local"
    key_reference: str = "local-v1"


class CredentialCipher:
    """AES-256-GCM encryption for provider credentials stored in private.credentials.

    The key is supplied by the deployment's secret/KMS adapter and is never persisted
    alongside the encrypted credential.
    """

    def __init__(self, *, key: bytes, key_version: str) -> None:
        if len(key) != 32:
            raise ValueError("Credential encryption keys must contain exactly 32 bytes")
        if not key_version:
            raise ValueError("Credential key version is required")

        self._cipher = AESGCM(key)
        self._key_version = key_version

    @staticmethod
    def _aad(
        *, credential_id: UUID, owner_id: UUID, provider: str, credential_kind: str
    ) -> bytes:
        return json.dumps(
            {
                "credential_id": str(credential_id),
                "credential_kind": credential_kind,
                "owner_id": str(owner_id),
                "provider": provider,
                "version": "v1",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def encrypt_json(
        self,
        value: dict[str, object],
        *,
        credential_id: UUID,
        owner_id: UUID,
        provider: str,
        credential_kind: str,
    ) -> EncryptedCredential:
        plaintext = json.dumps(value, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext,
            self._aad(
                credential_id=credential_id,
                owner_id=owner_id,
                provider=provider,
                credential_kind=credential_kind,
            ),
        )
        return EncryptedCredential(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=self._key_version,
            key_reference=self._key_version,
        )

    def decrypt_json(
        self,
        encrypted: EncryptedCredential,
        *,
        credential_id: UUID,
        owner_id: UUID,
        provider: str,
        credential_kind: str,
    ) -> dict[str, object]:
        if (
            encrypted.aad_version != "v1"
            or encrypted.encryption_provider != "local"
            or encrypted.key_version != self._key_version
            or encrypted.key_reference != self._key_version
        ):
            raise CredentialDecryptionError("Credential cannot be decrypted")

        try:
            plaintext = self._cipher.decrypt(
                encrypted.nonce,
                encrypted.ciphertext,
                self._aad(
                    credential_id=credential_id,
                    owner_id=owner_id,
                    provider=provider,
                    credential_kind=credential_kind,
                ),
            )
            decoded = json.loads(plaintext)
        except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CredentialDecryptionError("Credential cannot be decrypted") from error

        if not isinstance(decoded, dict):
            raise CredentialDecryptionError("Credential cannot be decrypted")
        return decoded


class VaultTransitTransport(Protocol):
    def write(self, path: str, payload: dict[str, str]) -> dict[str, object]: ...


class VaultTransitClient:
    """Minimal, allowlisted Vault HTTP client for the Transit encryption endpoints."""

    def __init__(self, *, address: str, token: str, timeout_seconds: float) -> None:
        self._address = address.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def _request(self, path: str, payload: dict[str, str]) -> dict[str, object]:
        request = Request(
            f"{self._address}/v1/{quote(path, safe='/')}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Vault-Token": self._token},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            raise CredentialEncryptionUnavailable(
                "Credential encryption service is unavailable"
            ) from error

        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CredentialEncryptionUnavailable(
                "Credential encryption service is unavailable"
            ) from error
        if not isinstance(decoded, dict):
            raise CredentialEncryptionUnavailable(
                "Credential encryption service is unavailable"
            )
        return decoded

    def write(self, path: str, payload: dict[str, str]) -> dict[str, object]:
        decoded = self._request(path, payload)
        data = decoded.get("data")
        if not isinstance(data, dict):
            raise CredentialEncryptionUnavailable(
                "Credential encryption service is unavailable"
            )
        return data

    def renew_self(self) -> None:
        decoded = self._request("auth/token/renew-self", {})
        auth = decoded.get("auth")
        if not isinstance(auth, dict) or not isinstance(
            auth.get("lease_duration"), int
        ):
            raise CredentialEncryptionUnavailable(
                "Credential encryption service is unavailable"
            )


class VaultTransitCredentialCipher:
    """Vault Transit encryption for retained provider credentials.

    Vault owns the AES-GCM key and embeds the Vault key version in its ciphertext.
    The supplied context is authenticated data and prevents a credential from being
    decrypted for another owner, provider, or credential type.
    """

    def __init__(self, *, client: VaultTransitTransport, mount: str, key: str) -> None:
        self._client = client
        self._mount = mount
        self._key = key

    @staticmethod
    def _aad(
        *, credential_id: UUID, owner_id: UUID, provider: str, credential_kind: str
    ) -> bytes:
        return CredentialCipher._aad(
            credential_id=credential_id,
            owner_id=owner_id,
            provider=provider,
            credential_kind=credential_kind,
        )

    def _context(
        self,
        *,
        credential_id: UUID,
        owner_id: UUID,
        provider: str,
        credential_kind: str,
    ) -> str:
        return base64.b64encode(
            self._aad(
                credential_id=credential_id,
                owner_id=owner_id,
                provider=provider,
                credential_kind=credential_kind,
            )
        ).decode("ascii")

    def encrypt_json(
        self,
        value: dict[str, object],
        *,
        credential_id: UUID,
        owner_id: UUID,
        provider: str,
        credential_kind: str,
    ) -> EncryptedCredential:
        plaintext = base64.b64encode(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii")
        response = self._client.write(
            f"{self._mount}/encrypt/{self._key}",
            {
                "plaintext": plaintext,
                "context": self._context(
                    credential_id=credential_id,
                    owner_id=owner_id,
                    provider=provider,
                    credential_kind=credential_kind,
                ),
            },
        )
        ciphertext = response.get("ciphertext")
        if not isinstance(ciphertext, str) or not ciphertext.startswith("vault:v"):
            raise CredentialEncryptionUnavailable(
                "Credential encryption service is unavailable"
            )
        key_version = ciphertext.split(":", 2)[1]
        return EncryptedCredential(
            ciphertext=ciphertext.encode("ascii"),
            nonce=b"",
            key_version=key_version,
            encryption_provider="vault",
            key_reference=f"{self._mount}/{self._key}",
        )

    def decrypt_json(
        self,
        encrypted: EncryptedCredential,
        *,
        credential_id: UUID,
        owner_id: UUID,
        provider: str,
        credential_kind: str,
    ) -> dict[str, object]:
        if (
            encrypted.aad_version != "v1"
            or encrypted.encryption_provider != "vault"
            or encrypted.key_reference != f"{self._mount}/{self._key}"
        ):
            raise CredentialDecryptionError("Credential cannot be decrypted")
        try:
            ciphertext = encrypted.ciphertext.decode("ascii")
        except UnicodeDecodeError as error:
            raise CredentialDecryptionError("Credential cannot be decrypted") from error
        if not ciphertext.startswith("vault:v"):
            raise CredentialDecryptionError("Credential cannot be decrypted")
        try:
            response = self._client.write(
                f"{self._mount}/decrypt/{self._key}",
                {
                    "ciphertext": ciphertext,
                    "context": self._context(
                        credential_id=credential_id,
                        owner_id=owner_id,
                        provider=provider,
                        credential_kind=credential_kind,
                    ),
                },
            )
            plaintext = response.get("plaintext")
            if not isinstance(plaintext, str):
                raise CredentialDecryptionError("Credential cannot be decrypted")
            decoded = json.loads(base64.b64decode(plaintext, validate=True))
        except (
            CredentialEncryptionUnavailable,
            UnicodeDecodeError,
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as error:
            raise CredentialDecryptionError("Credential cannot be decrypted") from error
        if not isinstance(decoded, dict):
            raise CredentialDecryptionError("Credential cannot be decrypted")
        return decoded


def credential_cipher_from_settings(
    settings: AuthSettings,
) -> CredentialCipher | VaultTransitCredentialCipher:
    settings.validate_for_authentication()
    if settings.credential_encryption_provider == "vault":
        assert settings.vault_addr is not None
        assert settings.vault_token is not None
        return VaultTransitCredentialCipher(
            client=VaultTransitClient(
                address=settings.vault_addr,
                token=settings.vault_token.get_secret_value(),
                timeout_seconds=settings.vault_request_timeout_seconds,
            ),
            mount=settings.vault_transit_mount,
            key=settings.vault_transit_key,
        )
    assert settings.credential_encryption_key is not None
    return CredentialCipher(
        key=decode_base64url_key(
            settings.credential_encryption_key.get_secret_value(),
            name="AUTH_CREDENTIAL_ENCRYPTION_KEY",
        ),
        key_version=settings.credential_encryption_key_version,
    )


def email_payload_cipher_from_settings(
    settings: AuthSettings,
) -> CredentialCipher | VaultTransitCredentialCipher:
    """Create the distinct cipher used for durable email job payloads.

    The type is intentionally the same as the provider-credential cipher: both
    provide authenticated encryption, but the Transit key and authenticated context
    are distinct so an email payload cannot be substituted for a provider credential.
    """
    if settings.credential_encryption_provider == "vault":
        settings._validate_vault_settings()
        assert settings.vault_addr is not None
        assert settings.vault_token is not None
        return VaultTransitCredentialCipher(
            client=VaultTransitClient(
                address=settings.vault_addr,
                token=settings.vault_token.get_secret_value(),
                timeout_seconds=settings.vault_request_timeout_seconds,
            ),
            mount=settings.vault_transit_mount,
            key=settings.vault_email_transit_key,
        )
    if settings.credential_encryption_key is None:
        raise CredentialEncryptionUnavailable(
            "Email payload encryption configuration is incomplete"
        )
    return CredentialCipher(
        key=decode_base64url_key(
            settings.credential_encryption_key.get_secret_value(),
            name="AUTH_CREDENTIAL_ENCRYPTION_KEY",
        ),
        key_version=settings.credential_encryption_key_version,
    )
