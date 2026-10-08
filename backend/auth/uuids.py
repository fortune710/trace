from __future__ import annotations

import secrets
import time
from uuid import UUID


def uuid7() -> UUID:
    """Create an RFC 9562 UUIDv7 using a millisecond timestamp and CSPRNG bits."""
    timestamp_milliseconds = time.time_ns() // 1_000_000
    if not 0 <= timestamp_milliseconds < 1 << 48:
        raise ValueError("Current timestamp cannot be represented by UUIDv7")

    random_bits = int.from_bytes(secrets.token_bytes(10), "big") & ((1 << 74) - 1)
    random_a = random_bits >> 62
    random_b = random_bits & ((1 << 62) - 1)
    value = (
        (timestamp_milliseconds << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return UUID(int=value)
