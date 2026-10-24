from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.integration


def _local_snapshot(project: dict[str, object]) -> dict[str, str]:
    return {
        "source_id": str(project["_local_source_id"]),
        "integrity_algorithm": "sha256-directory-manifest-v1",
        "digest": "a" * 64,
    }


def test_review_owner_can_queue_and_cancel_explicit_assignments(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    first_agent = agent_factory(owner, name="security-one")
    second_agent = agent_factory(owner, name="security-two")

    review = review_factory(
        owner,
        project=project,
        agent_ids=[
            first_agent["id"],
            second_agent["id"],
        ],
    )
    review_id = review["id"]
    assert review["status"] == "queued"
    assert len(review["agents"]) == 2
    assert all("assignment_id" in agent for agent in review["agents"])

    fetched = owner.request("GET", f"/api/v1/reviews/{review_id}")
    assert fetched.status_code == 200
    assert len(fetched.json()["agents"]) == 2

    cancelled = owner.request("POST", f"/api/v1/reviews/{review_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    listed = owner.request("GET", "/api/v1/reviews?project_id=" + project["id"])
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


def test_one_agent_can_be_reused_and_foreign_review_access_is_denied(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    first = review_factory(owner, project, [agent["id"]])
    second = review_factory(owner, project, [agent["id"]])
    assert first["id"] != second["id"]

    for method, path, body in (
        ("GET", f"/api/v1/reviews/{first['id']}", None),
        ("POST", f"/api/v1/reviews/{first['id']}/cancel", None),
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
            "agent_ids": [owner_agent["id"]],
        },
        headers={"Idempotency-Key": str(UUID(int=1))},
    )
    assert foreign_project_request.status_code == 403

    foreign_agent_request = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": owner_project["id"],
            "agent_ids": [foreign_agent["id"]],
            "local_source_snapshot": _local_snapshot(owner_project),
        },
        headers={"Idempotency-Key": str(UUID(int=2))},
    )
    assert foreign_agent_request.status_code == 403
    assert str(foreign_agent["id"]) not in foreign_agent_request.text


def test_review_submission_validates_request_source_state_and_idempotency(
    account_pair,
    local_project_factory,
    agent_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    first_agent = agent_factory(owner, name="first")
    second_agent = agent_factory(owner, name="second")
    body = {
        "project_id": project["id"],
        "agent_ids": [first_agent["id"], second_agent["id"]],
        "local_source_snapshot": _local_snapshot(project),
    }

    missing_key = owner.request("POST", "/api/v1/reviews", json=body)
    assert missing_key.status_code == 400

    malformed_key = owner.request(
        "POST",
        "/api/v1/reviews",
        json=body,
        headers={"Idempotency-Key": " leading"},
    )
    assert malformed_key.status_code == 400

    for label, invalid_body in (
        ("legacy source", {**body, "source_revision": "client-controlled"}),
        ("legacy categories", {**body, "selected_categories": ["security"]}),
        ("empty agents", {"project_id": project["id"], "agent_ids": []}),
        (
            "duplicate agents",
            {
                "project_id": project["id"],
                "agent_ids": [first_agent["id"], first_agent["id"]],
            },
        ),
        (
            "too many agents",
            {
                "project_id": project["id"],
                "agent_ids": [str(uuid4()) for _ in range(101)],
            },
        ),
    ):
        response = owner.request(
            "POST",
            "/api/v1/reviews",
            json=invalid_body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422, f"{label}: {response.text}"

    created = owner.request(
        "POST",
        "/api/v1/reviews",
        json=body,
        headers={"Idempotency-Key": "review-submission"},
    )
    assert created.status_code == 202
    assert created.json()["source_revision"] == "a" * 64
    assert len(created.json()["agents"]) == 2

    replayed = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [second_agent["id"], first_agent["id"]],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": "review-submission"},
    )
    assert replayed.status_code == 202
    assert replayed.json()["id"] == created.json()["id"]

    conflicting_reuse = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [first_agent["id"]],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": "review-submission"},
    )
    assert conflicting_reuse.status_code == 409

    distinct_submission = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [first_agent["id"]],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": "review-submission-2"},
    )
    assert distinct_submission.status_code == 202
    assert distinct_submission.json()["id"] != created.json()["id"]


def test_review_submission_rejects_missing_resources_and_unusable_owned_state(
    account_pair,
    local_project_factory,
    agent_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)

    missing_project = owner.request(
        "POST",
        "/api/v1/reviews",
        json={"project_id": str(uuid4()), "agent_ids": [agent["id"]]},
        headers={"Idempotency-Key": "missing-project"},
    )
    assert missing_project.status_code == 404

    missing_agent = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [str(uuid4())],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": "missing-agent"},
    )
    assert missing_agent.status_code == 404
    assert (
        owner.request("GET", "/api/v1/reviews?project_id=" + project["id"]).json()[
            "items"
        ]
        == []
    )

    incomplete_source = owner.request(
        "POST",
        "/api/v1/projects",
        json={
            "name": "incomplete-source",
            "source": "local",
            "local_path_hash": "e" * 64,
        },
    )
    assert incomplete_source.status_code == 201
    invalid_source = owner.request(
        "POST",
        "/api/v1/reviews",
        json={"project_id": incomplete_source.json()["id"], "agent_ids": [agent["id"]]},
        headers={"Idempotency-Key": "invalid-source"},
    )
    assert invalid_source.status_code == 409

    disabled = owner.request("DELETE", f"/api/v1/agents/{agent['id']}")
    assert disabled.status_code == 204
    disabled_agent = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [agent["id"]],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": "disabled-agent"},
    )
    assert disabled_agent.status_code == 409

    replacement_agent = agent_factory(owner, name="replacement")
    archived = owner.request("DELETE", f"/api/v1/projects/{project['id']}")
    assert archived.status_code == 204
    archived_project = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [replacement_agent["id"]],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": "archived-project"},
    )
    assert archived_project.status_code == 409


def test_review_validation_uses_project_then_requested_agent_order_without_writes(
    account_pair,
    local_project_factory,
    agent_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    owned_agent = agent_factory(owner)
    foreign_agent = agent_factory(other, name="foreign-agent")
    missing_agent = str(uuid4())

    foreign_first = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [foreign_agent["id"], missing_agent],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": "foreign-before-missing"},
    )
    assert foreign_first.status_code == 403
    assert foreign_first.json()["error"]["code"] == "authorization_denied"
    assert foreign_agent["id"] not in foreign_first.text

    missing_first = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [missing_agent, foreign_agent["id"]],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": "missing-before-foreign"},
    )
    assert missing_first.status_code == 404
    assert missing_first.json()["error"]["code"] == "resource_not_found"
    assert foreign_agent["id"] not in missing_first.text

    foreign_project = local_project_factory(other, name="foreign-project")
    foreign_project_request = owner.request(
        "POST",
        "/api/v1/reviews",
        json={"project_id": foreign_project["id"], "agent_ids": [owned_agent["id"]]},
        headers={"Idempotency-Key": "foreign-project-first"},
    )
    assert foreign_project_request.status_code == 403
    assert owned_agent["id"] not in foreign_project_request.text
    assert owner.request("GET", "/api/v1/reviews").json()["items"] == []


def test_review_http_contract_rejects_malformed_ids_and_bodies(
    account_pair,
    local_project_factory,
    agent_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)

    for body in (
        {"project_id": "not-a-uuid", "agent_ids": [agent["id"]]},
        {"project_id": project["id"], "agent_ids": ["not-a-uuid"]},
        {"project_id": project["id"], "agent_ids": agent["id"]},
        {"project_id": project["id"], "agent_ids": [agent["id"]], "extra": True},
    ):
        response = owner.request(
            "POST",
            "/api/v1/reviews",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    malformed_json = owner.request(
        "POST",
        "/api/v1/reviews",
        content=b"{not-json",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert malformed_json.status_code == 422
    assert malformed_json.json()["error"]["code"] == "invalid_request"
    assert owner.request("GET", "/api/v1/reviews").json()["items"] == []


def test_review_response_never_exposes_submission_secret_or_local_path(
    account_pair,
    local_project_factory,
    agent_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    raw_key = "review-secret-idempotency-key"
    created = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [agent["id"]],
            "local_source_snapshot": _local_snapshot(project),
        },
        headers={"Idempotency-Key": raw_key},
    )
    assert created.status_code == 202
    review_id = created.json()["id"]

    for response in (
        created,
        owner.request("GET", f"/api/v1/reviews/{review_id}"),
        owner.request("GET", "/api/v1/reviews"),
        owner.request("POST", f"/api/v1/reviews/{review_id}/cancel"),
    ):
        assert response.status_code in {200, 202}
        serialized = response.text
        assert raw_key not in serialized
        assert "local_path" not in serialized
        assert "idempotency_key_digest" not in serialized
        assert "request_digest" not in serialized
        assert "credential" not in serialized

    repeated_cancel = owner.request("POST", f"/api/v1/reviews/{review_id}/cancel")
    assert repeated_cancel.status_code == 409


def test_review_audits_are_allowlisted_and_never_echo_submission_values(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
    recording_audit_recorder,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    raw_idempotency_key = "raw-review-key"
    source_contents = "source-contents"

    created = review_factory(
        owner,
        project=project,
        agent_ids=[agent["id"]],
        idempotency_key=raw_idempotency_key,
    )
    cancelled = owner.request("POST", f"/api/v1/reviews/{created['id']}/cancel")
    rejected = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": project["id"],
            "agent_ids": [agent["id"]],
            "source_revision": source_contents,
        },
        headers={"Idempotency-Key": raw_idempotency_key},
    )

    assert cancelled.status_code == 200
    assert rejected.status_code == 422
    review_events = [
        event
        for event in recording_audit_recorder.events
        if str(event["event_type"]).startswith("resource.review.")
        or event["event_type"] == "review.submission.rejected"
    ]
    assert [event["event_type"] for event in review_events] == [
        "resource.review.queued",
        "resource.review.cancelled",
        "review.submission.rejected",
    ]
    assert [set(event["fields"]) for event in review_events] == [
        {"resource", "operation", "route", "status_code"},
        {"resource", "operation", "route", "status_code"},
        {"outcome", "reason", "resource", "route", "status_code"},
    ]
    serialized = json.dumps(
        [created, cancelled.json(), rejected.json(), review_events],
        default=str,
        sort_keys=True,
    )
    for forbidden in (
        raw_idempotency_key,
        source_contents,
        "credential",
        "local_path",
        "request_digest",
        "idempotency_key_digest",
    ):
        assert forbidden not in serialized
