"""Compatibility helpers required by immudb-py's verification call."""

from __future__ import annotations


def sigdecode_der(signature: bytes, order: int) -> tuple[int, int]:
    """Reject direct use while retaining the argument expected by immudb-py.

    The cryptography-backed verifier consumes DER signatures directly, so this
    decoder is intentionally never called.  Raising makes accidental use of
    the compatibility shim explicit rather than silently parsing signatures.
    """

    del signature, order
    raise RuntimeError("DER decoding is handled by cryptography")
