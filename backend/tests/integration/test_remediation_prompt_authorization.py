from __future__ import annotations

import logging
from uuid import uuid4

import pytest
import sqlalchemy as sa

from db.rls import principal_transaction
from remediations.models import Remediation
from reviews.models import Review, ReviewStatus

pytestmark = pytest.mark.integration


def test_owner_scoped_remediation_prompt_requires_csrf_and_redacts_auditing(
    account_pair,
    local_project_factory,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    recording_audit_recorder,
    caplog,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    path = f"/api/v1/remediations/{graph['remediation_id']}/prompt"
    stored_prompt = "Resolve the integration finding without unrelated changes."

    with caplog.at_level(logging.INFO, logger="trace.auth"):
        response = owner.client.get(path, headers=owner.headers())
    assert response.status_code == 200
    rendered_prompt = response.json()["prompt_text"]
    assert rendered_prompt.startswith("# Trace coding remediation prompt")
    assert "(v" not in rendered_prompt
    assert stored_prompt in rendered_prompt
    assert "## Step 1 — Verify before changing anything" in rendered_prompt
    assert "Integration finding" not in rendered_prompt
    assert stored_prompt not in caplog.text

    events = [
        event
        for event in recording_audit_recorder.events
        if event["event_type"] == "resource.remediation.prompt_read"
    ]
    assert len(events) == 1
    event = events[0]
    assert event["owner_id"] == owner.user_id
    assert isinstance(event["request_id"], str)
    assert event["fields"] == {
        "resource": "remediation",
        "operation": "prompt_read",
        "route": path,
        "status_code": "200",
    }
    assert stored_prompt not in str(events[0])

    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Review)
            .where(Review.id == graph["review_id"])
            .values(status=ReviewStatus.RUNNING)
        )
    incomplete_review = owner.client.get(path, headers=owner.headers())
    assert incomplete_review.status_code == 409
    assert incomplete_review.json()["error"]["code"] == "resource_conflict"
    assert stored_prompt not in incomplete_review.text

    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Review)
            .where(Review.id == graph["review_id"])
            .values(status=ReviewStatus.COMPLETED)
        )
        connection.execute(
            sa.update(Remediation)
            .where(Remediation.id == graph["remediation_id"])
            .values(prompt_text="x" * 50_000)
        )
    render_failed = owner.client.get(path, headers=owner.headers())
    assert render_failed.status_code == 404
    assert render_failed.json()["error"]["code"] == "resource_not_found"
    assert stored_prompt not in render_failed.text
    assert any(
        event["event_type"] == "remediation_prompt.rejected"
        and event["fields"]
        == {
            "outcome": "rejected",
            "reason": "render_failed",
            "route": path,
            "status_code": "404",
        }
        for event in recording_audit_recorder.events
    )

    missing_csrf = owner.client.get(path)
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_validation_failed"
    assert stored_prompt not in missing_csrf.text

    foreign = other.client.get(path, headers=other.headers())
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "authorization_denied"
    assert stored_prompt not in foreign.text

    missing = owner.client.get(
        f"/api/v1/remediations/{uuid4()}/prompt",
        headers=owner.headers(),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "resource_not_found"

    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Remediation)
            .where(Remediation.id == graph["remediation_id"])
            .values(prompt_text=None)
        )
    legacy_missing = owner.client.get(path, headers=owner.headers())
    assert legacy_missing.status_code == 404
    assert legacy_missing.json()["error"]["code"] == "resource_not_found"

    rejection_event_types = {
        event["event_type"]
        for event in recording_audit_recorder.events
        if event["event_type"]
        in {"csrf.rejected", "authorization.rejected", "resource.rejected"}
    }
    assert rejection_event_types == {
        "csrf.rejected",
        "authorization.rejected",
        "resource.rejected",
    }
    assert all(
        stored_prompt not in str(event) for event in recording_audit_recorder.events
    )
