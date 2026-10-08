from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class PasswordPolicyError(ValueError):
    """Raised when a password cannot safely enter the hash function."""


_PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)
_MINIMUM_PASSWORD_LENGTH = 12
_MAXIMUM_PASSWORD_BYTES = 1024


def validate_password(password: str) -> None:
    if len(password) < _MINIMUM_PASSWORD_LENGTH:
        raise PasswordPolicyError("Password does not meet the minimum length")
    if len(password.encode("utf-8")) > _MAXIMUM_PASSWORD_BYTES:
        raise PasswordPolicyError("Password exceeds the maximum length")


def hash_password(password: str) -> str:
    validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
