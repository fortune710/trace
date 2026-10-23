from __future__ import annotations

from uuid import UUID

import pytest

pytestmark = pytest.mark.integration


def test_agent_owner_can_create_update_disable_and_list(
    account_pair,
    agent_factory,
) -> None:
    owner, _ = account_pair
    agent = agent_factory(owner)
    agent_id = agent["id"]

    assert owner.request("GET", "/api/v1/agents").json()["items"]
    assert owner.request("GET", f"/api/v1/agents/{agent_id}").status_code == 200

    updated = owner.request(
        "PATCH",
        f"/api/v1/agents/{agent_id}",
        json={"name": "updated-agent", "fallback_order": 2},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "updated-agent"

    disabled = owner.request("DELETE", f"/api/v1/agents/{agent_id}")
    assert disabled.status_code == 204
    assert owner.request("GET", "/api/v1/agents").json()["items"] == []
    historical = owner.request("GET", "/api/v1/agents?include_disabled=true")
    assert historical.status_code == 200
    assert historical.json()["items"][0]["disabled_at"] is not None


def test_agent_foreign_resource_and_foreign_credential_are_denied(
    account_pair,
    agent_factory,
    credential_factory,
) -> None:
    owner, other = account_pair
    agent = agent_factory(owner)
    credential = credential_factory(owner)
    agent_id = agent["id"]

    for method, path, body in (
        ("GET", f"/api/v1/agents/{agent_id}", None),
        ("PATCH", f"/api/v1/agents/{agent_id}", {"name": "foreign"}),
        ("DELETE", f"/api/v1/agents/{agent_id}", None),
    ):
        response = (
            other.request(method, path, json=body)
            if body
            else other.request(method, path)
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "authorization_denied"
        assert str(owner.user_id) not in response.text

    foreign_credential = other.request(
        "POST",
        "/api/v1/agents",
        json={
            "name": "foreign-credential-agent",
            "review_category": "security",
            "model_provider": "github",
            "model_name": "integration-model",
            "credential_id": credential["id"],
        },
    )
    assert foreign_credential.status_code == 403
    assert credential["id"] not in foreign_credential.text
    assert other.request("GET", "/api/v1/agents").json()["items"] == []


def test_agent_rejects_revoked_credential_and_unknown_fields(
    account_pair,
    credential_factory,
) -> None:
    owner, _ = account_pair
    credential = credential_factory(owner)
    credential_id = UUID(credential["id"])
    revoked = owner.request("DELETE", f"/api/v1/credentials/{credential_id}")
    assert revoked.status_code == 204

    rejected = owner.request(
        "POST",
        "/api/v1/agents",
        json={
            "name": "revoked-credential-agent",
            "review_category": "security",
            "model_provider": "github",
            "model_name": "integration-model",
            "credential_id": str(credential_id),
        },
    )
    assert rejected.status_code == 403

    unknown = owner.request(
        "POST",
        "/api/v1/agents",
        json={
            "name": "unknown-field-agent",
            "review_category": "security",
            "model_provider": "trace",
            "model_name": "integration-model",
            "unexpected": True,
        },
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "invalid_request"
