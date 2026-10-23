"""Small immudb compatibility surface backed by ``cryptography``.

immudb-py 1.5.0 imports python-ecdsa for verifying immudb server signatures.
The SDK does not use signing or key generation in Trace.  Keeping this narrow
module in the application avoids shipping the unmaintained python-ecdsa
dependency while preserving the SDK's verification API.
"""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


class VerifyingKey:
    """Adapter for the subset of ``ecdsa.VerifyingKey`` used by immudb-py."""

    def __init__(self, key: Any) -> None:
        self._key = key

    @classmethod
    def from_pem(cls, key: str | bytes) -> VerifyingKey:
        material = key.encode("utf-8") if isinstance(key, str) else key
        loaded = serialization.load_pem_public_key(material)
        if not isinstance(loaded, ec.EllipticCurvePublicKey):
            raise TypeError("immudb signing key is not an elliptic-curve public key")
        return cls(loaded)

    def verify(
        self,
        signature: bytes,
        data: bytes,
        hashfunc: Any,
        *,
        sigdecode: Any = None,
    ) -> bool:
        del sigdecode
        algorithm = _hash_algorithm(hashfunc)
        self._key.verify(signature, data, ec.ECDSA(algorithm))
        return True


def _hash_algorithm(hashfunc: Any) -> hashes.HashAlgorithm:
    name = getattr(hashfunc, "name", "") or getattr(hashfunc, "__name__", "")
    if name in {"sha256", "openssl_sha256"}:
        return hashes.SHA256()
    if name in {"sha384", "openssl_sha384"}:
        return hashes.SHA384()
    if name in {"sha512", "openssl_sha512"}:
        return hashes.SHA512()
    raise ValueError("unsupported immudb signature hash algorithm")


from . import util

__all__ = ["VerifyingKey", "util"]
