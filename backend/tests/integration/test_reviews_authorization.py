from __future__ import annotations

from uuid import UUID

import pytest

pytestmark = pytest.mark.integration


def test_review_owner_can_queue_cancel_retry_and_dispatch_safe_identifiers(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
    dispatcher_stub,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    first_agent = agent_factory(owner, name="security-one")
    second_agent = agent_factory(owner, name="security-two")

    review = review_factory(
        owner,
        project_id=project["id"],
        agent_ids=[
            first_agent["id"],
            second_agent["id"],
        ],
    )
    review_id = review["id"]
    assert review["status"] == "queued"
    assert {call[0] for call in dispatcher_stub.calls} == {UUID(review_id)}
    assert dispatcher_stub.calls[0][1] == owner.user_id
    assert len(review["agents"]) == 2

    fetched = owner.request("GET", f"/api/v1/reviews/{review_id}")
    assert fetched.status_code == 200
    assert len(fetched.json()["agents"]) == 2

    cancelled = owner.request("POST", f"/api/v1/reviews/{review_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = owner.request("POST", f"/api/v1/reviews/{review_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["id"] != review_id
    assert len(dispatcher_stub.calls) == 2

    listed = owner.request("GET", "/api/v1/reviews?project_id=" + project["id"])
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2


def test_one_agent_can_be_reused_and_foreign_review_access_is_denied(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    first = review_factory(owner, project["id"], [agent["id"]])
    second = review_factory(owner, project["id"], [agent["id"]])
    assert first["id"] != second["id"]

    for method, path, body in (
        ("GET", f"/api/v1/reviews/{first['id']}", None),
        ("POST", f"/api/v1/reviews/{first['id']}/cancel", None),
        ("POST", f"/api/v1/reviews/{first['id']}/retry", None),
    ):
        response = (
            other.request(method, path, json=body)
            if body
            else other.request(method, path)
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "authorization_denied"
        assert str(owner.user_id) not in response.text

    assert other.request("GET", "/api/v1/reviews").json()["items"] == []


def test_review_rejects_foreign_project_and_foreign_agent(
    account_pair,
    local_project_factory,
    agent_factory,
) -> None:
    owner, other = account_pair
    owner_project = local_project_factory(owner)
    owner_agent = agent_factory(owner)

    foreign_project = other.request(
        "POST",
        "/api/v1/projects",
        json={
            "name": "other-project",
            "source": "local",
            "local_path_hash": "d" * 64,
        },
    ).json()
    foreign_agent = agent_factory(other, name="other-agent")

    foreign_project_request = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": foreign_project["id"],
            "source_revision": "revision",
            "selected_categories": ["security"],
            "agent_ids": [owner_agent["id"]],
        },
    )
    assert foreign_project_request.status_code == 403

    foreign_agent_request = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": owner_project["id"],
            "source_revision": "revision",
            "selected_categories": ["security"],
            "agent_ids": [foreign_agent["id"]],
        },
    )
    assert foreign_agent_request.status_code == 403
    assert str(foreign_agent["id"]) not in foreign_agent_request.text
