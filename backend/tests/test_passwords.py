import pytest

from auth.passwords import PasswordPolicyError, hash_password, verify_password


def test_argon2id_password_hash_verifies_only_the_original_password() -> None:
    password_hash = hash_password("a secure test passphrase")

    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "a secure test passphrase")
    assert not verify_password(password_hash, "an incorrect test passphrase")


def test_password_policy_rejects_short_passwords() -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password("too-short")
