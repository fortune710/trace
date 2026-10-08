from __future__ import annotations

from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from credentials.models import Credential
from db.rls import principal_transaction

pytestmark = pytest.mark.integration


def test_credential_owner_can_create_read_rotate_and_revoke(
    account_pair,
    credential_factory,
    integration_engine,
) -> None:
    owner, _ = account_pair
    created = credential_factory(owner)
    credential_id = UUID(created["id"])

    assert {
        "id",
        "provider",
        "kind",
        "active",
        "created_at",
        "updated_at",
        "revoked_at",
    } == set(created)
    assert (
        owner.request("GET", f"/api/v1/credentials/{credential_id}").status_code == 200
    )

    with principal_transaction(integration_engine, owner.user_id) as connection:
        before = connection.execute(
            sa.select(Credential.ciphertext).where(Credential.id == credential_id)
        ).scalar_one()

    rotated = owner.request(
        "POST",
        f"/api/v1/credentials/{credential_id}/rotate",
        json={
            "provider": "github",
            "kind": "oauth",
            "payload": {"access_token": "rotated-test-token"},
        },
    )
    assert rotated.status_code == 200
    assert "rotated-test-token" not in rotated.text

    with principal_transaction(integration_engine, owner.user_id) as connection:
        after = connection.execute(
            sa.select(Credential.ciphertext).where(Credential.id == credential_id)
        ).scalar_one()
    assert before != after

    revoked = owner.request("DELETE", f"/api/v1/credentials/{credential_id}")
    assert revoked.status_code == 204
    metadata = owner.request("GET", f"/api/v1/credentials/{credential_id}")
    assert metadata.status_code == 200
    assert metadata.json()["active"] is False

    conflict = owner.request(
        "POST",
        f"/api/v1/credentials/{credential_id}/rotate",
        json={
            "provider": "github",
            "kind": "oauth",
            "payload": {"access_token": "second-rotation"},
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "resource_conflict"
    assert "second-rotation" not in conflict.text


def test_foreign_credential_read_rotate_revoke_and_listing_are_denied(
    account_pair,
    credential_factory,
) -> None:
    owner, other = account_pair
    credential = credential_factory(owner)
    credential_id = credential["id"]

    for method, path, body in (
        ("GET", f"/api/v1/credentials/{credential_id}", None),
        (
            "POST",
            f"/api/v1/credentials/{credential_id}/rotate",
            {
                "provider": "github",
                "kind": "oauth",
                "payload": {"access_token": "foreign-rotate"},
            },
        ),
        ("DELETE", f"/api/v1/credentials/{credential_id}", None),
    ):
        response = (
            other.request(method, path, json=body)
            if body
            else other.request(method, path)
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "authorization_denied"
        assert credential_id not in response.text

    assert other.request("GET", "/api/v1/credentials").json()["items"] == []


def test_credentials_require_auth_csrf_and_strict_request_bodies(
    account_pair,
    integration_app,
) -> None:
    owner, _ = account_pair
    invalid = owner.request(
        "POST",
        "/api/v1/credentials",
        json={
            "provider": "github",
            "kind": "oauth",
            "payload": {"access_token": "invalid-body"},
            "unknown": True,
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_request"

    no_csrf = owner.client.post(
        "/api/v1/credentials",
        json={
            "provider": "github",
            "kind": "oauth",
            "payload": {"access_token": "missing-csrf"},
        },
    )
    assert no_csrf.status_code == 403

    unauthenticated = TestClient(integration_app).get("/api/v1/credentials")
    assert unauthenticated.status_code == 401
