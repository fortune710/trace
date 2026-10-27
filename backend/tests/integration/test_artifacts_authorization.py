from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


def test_owner_can_read_and_mutate_findings_and_remediations(
    account_pair,
    local_project_factory,
    agent_factory,
    artifact_graph_factory,
    recording_audit_recorder,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])

    findings = owner.request("GET", f"/api/v1/reviews/{graph['review_id']}/findings")
    assert findings.status_code == 200
    assert findings.json()["items"][0]["id"] == str(graph["finding_id"])

    finding = owner.request("GET", f"/api/v1/findings/{graph['finding_id']}")
    assert finding.status_code == 200
    initial_updated_at = finding.json()["updated_at"]
    invalid_from_open = owner.request(
        "PATCH",
        f"/api/v1/findings/{graph['finding_id']}",
        json={"status": "resolved"},
    )
    assert invalid_from_open.status_code == 409
    updated = owner.request(
        "PATCH",
        f"/api/v1/findings/{graph['finding_id']}",
        json={"status": "accepted"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "accepted"
    assert updated.json()["status_changed_at"] is not None
    assert updated.json()["updated_at"] == initial_updated_at

    duplicate = owner.request(
        "PATCH",
        f"/api/v1/findings/{graph['finding_id']}",
        json={"status": "accepted"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "resource_conflict"

    invalid_from_accepted = owner.request(
        "PATCH",
        f"/api/v1/findings/{graph['finding_id']}",
        json={"status": "dismissed"},
    )
    assert invalid_from_accepted.status_code == 409

    resolved = owner.request(
        "PATCH",
        f"/api/v1/findings/{graph['finding_id']}",
        json={"status": "resolved"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    invalid_from_resolved = owner.request(
        "PATCH",
        f"/api/v1/findings/{graph['finding_id']}",
        json={"status": "open"},
    )
    assert invalid_from_resolved.status_code == 409

    unresolved = owner.request(
        "PATCH",
        f"/api/v1/findings/{graph['finding_id']}",
        json={"status": "accepted"},
    )
    assert unresolved.status_code == 200
    assert unresolved.json()["status"] == "accepted"

    second_graph = artifact_graph_factory(owner, project["id"], agent["id"])
    dismissed = owner.request(
        "PATCH",
        f"/api/v1/findings/{second_graph['finding_id']}",
        json={"status": "dismissed"},
    )
    assert dismissed.status_code == 200
    reopened = owner.request(
        "PATCH",
        f"/api/v1/findings/{second_graph['finding_id']}",
        json={"status": "open"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"

    triage_events = [
        event
        for event in recording_audit_recorder.events
        if event["event_type"] == "resource.finding.triaged"
    ]
    assert len(triage_events) == 5
    assert triage_events[0]["fields"] == {
        "finding_id": str(graph["finding_id"]),
        "review_id": str(graph["review_id"]),
        "from_status": "open",
        "to_status": "accepted",
    }

    created = owner.request(
        "POST",
        f"/api/v1/findings/{graph['finding_id']}/remediations",
        json={"proposed_diff": "diff --git a/a b/a"},
    )
    assert created.status_code == 201
    remediation_id = created.json()["id"]
    assert (
        owner.request("GET", f"/api/v1/remediations/{remediation_id}").status_code
        == 200
    )

    approved = owner.request("POST", f"/api/v1/remediations/{remediation_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    assert (
        owner.request(
            "GET", f"/api/v1/remediations/{graph['remediation_id']}/pull-request"
        ).status_code
        == 200
    )
    assert (
        owner.request(
            "GET", f"/api/v1/remediations/{graph['remediation_id']}/local-file-backup"
        ).status_code
        == 200
    )
    assert (
        owner.request(
            "GET", f"/api/v1/pull-requests/{graph['pull_request_id']}"
        ).status_code
        == 200
    )
    assert (
        owner.request(
            "GET", f"/api/v1/local-file-backups/{graph['backup_id']}"
        ).status_code
        == 200
    )


def test_foreign_findings_remediations_and_artifacts_are_denied(
    account_pair,
    local_project_factory,
    agent_factory,
    artifact_graph_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])

    requests = (
        ("GET", f"/api/v1/reviews/{graph['review_id']}/findings", None),
        ("GET", f"/api/v1/findings/{graph['finding_id']}", None),
        ("PATCH", f"/api/v1/findings/{graph['finding_id']}", {"status": "accepted"}),
        (
            "POST",
            f"/api/v1/findings/{graph['finding_id']}/remediations",
            {"proposed_diff": "foreign"},
        ),
        ("GET", f"/api/v1/remediations/{graph['remediation_id']}", None),
        ("POST", f"/api/v1/remediations/{graph['remediation_id']}/approve", None),
        ("POST", f"/api/v1/remediations/{graph['remediation_id']}/reject", None),
        ("GET", f"/api/v1/pull-requests/{graph['pull_request_id']}", None),
        ("GET", f"/api/v1/local-file-backups/{graph['backup_id']}", None),
    )
    for method, path, body in requests:
        response = (
            other.request(method, path, json=body)
            if body
            else other.request(method, path)
        )
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["error"]["code"] == "authorization_denied"
        assert str(owner.user_id) not in response.text

    assert other.request("GET", "/api/v1/reviews").json()["items"] == []


def test_nonexistent_artifacts_return_not_found(
    account_pair,
) -> None:
    owner, _ = account_pair
    for path in (
        f"/api/v1/pull-requests/{uuid4()}",
        f"/api/v1/local-file-backups/{uuid4()}",
    ):
        response = owner.request("GET", path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource_not_found"
