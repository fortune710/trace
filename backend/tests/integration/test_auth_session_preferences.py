from __future__ import annotations

import pytest
import sqlalchemy as sa

from users.models import User

pytestmark = pytest.mark.integration


def test_automatic_pull_request_preference_is_csrf_protected_and_owner_scoped(
    account_pair,
    integration_engine,
) -> None:
    owner, other = account_pair

    initial = owner.client.get("/auth/session")
    assert initial.status_code == 200
    assert initial.json()["automatic_pull_requests"] is False

    rejected = owner.client.patch(
        "/auth/session",
        json={"automatic_pull_requests": True},
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "csrf_validation_failed"

    updated = owner.client.patch(
        "/auth/session",
        headers=owner.headers(),
        json={"automatic_pull_requests": True},
    )
    assert updated.status_code == 200
    assert updated.json() == {"automatic_pull_requests": True}

    with integration_engine.connect() as connection:
        owner_value = connection.execute(
            sa.select(User.automatic_pull_requests).where(User.id == owner.user_id)
        ).scalar_one()
        other_value = connection.execute(
            sa.select(User.automatic_pull_requests).where(User.id == other.user_id)
        ).scalar_one()
    assert owner_value is True
    assert other_value is False


def test_automatic_pull_request_preference_rejects_unexpected_fields(
    account_pair,
) -> None:
    owner, _other = account_pair

    response = owner.client.patch(
        "/auth/session",
        headers=owner.headers(),
        json={"automatic_pull_requests": True, "unexpected": True},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
