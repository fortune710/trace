from datetime import UTC, datetime
from uuid import UUID

import pytest

from auth.tokens import (
    InvalidAccessToken,
    JWTService,
    TokenPurpose,
    digest_opaque_token,
)


def test_access_token_has_the_approved_contract() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    session_id = UUID("00000000-0000-0000-0000-000000000002")
    service = JWTService.from_private_key_bytes(
        b"a" * 32,
        key_id="test-v1",
        issuer="trace-api",
        audience="trace-api",
    )

    token = service.issue(user_id=user_id, session_id=session_id, now=datetime.now(UTC))
    claims = service.verify(token)

    assert claims.user_id == user_id
    assert claims.session_id == session_id
    assert claims.expires_at.timestamp() - claims.issued_at.timestamp() == 60 * 60


def test_access_token_is_rejected_by_a_different_audience() -> None:
    service = JWTService.from_private_key_bytes(
        b"a" * 32,
        key_id="test-v1",
        issuer="trace-api",
        audience="trace-api",
    )
    token = service.issue(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        session_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    other_audience = JWTService.from_private_key_bytes(
        b"a" * 32,
        key_id="test-v1",
        issuer="trace-api",
        audience="another-api",
    )

    with pytest.raises(InvalidAccessToken):
        other_audience.verify(token)


def test_opaque_token_digests_are_purpose_bound() -> None:
    refresh_digest = digest_opaque_token(
        "a" * 43, key=b"b" * 32, purpose=TokenPurpose.REFRESH
    )
    recovery_digest = digest_opaque_token(
        "a" * 43, key=b"b" * 32, purpose=TokenPurpose.PASSWORD_RECOVERY
    )

    assert refresh_digest != recovery_digest
