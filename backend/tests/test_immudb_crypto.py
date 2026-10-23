from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ecdsa import VerifyingKey
from ecdsa.util import sigdecode_der


def test_immudb_signature_compatibility_uses_cryptography() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    message = b"verified immudb state"
    signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))

    verifying_key = VerifyingKey.from_pem(public_key)

    assert verifying_key.verify(
        signature,
        message,
        hashlib.sha256,
        sigdecode=sigdecode_der,
    )
