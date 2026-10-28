from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_remediation_issue_creation_validates_the_destination_and_owner(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    local_project_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    path = f"/api/v1/remediations/{graph['remediation_id']}/issue"
    body = {"destination": {"provider": "github"}}

    missing_csrf = owner.client.post(path, json=body)
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_validation_failed"

    invalid_destination = owner.client.post(
        path,
        headers=owner.headers(),
        json={"destination": {"provider": "github", "owner": "acme"}},
    )
    assert invalid_destination.status_code == 422

    foreign = other.client.post(path, headers=other.headers(), json=body)
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "authorization_denied"

    no_provider_credential = owner.client.post(path, headers=owner.headers(), json=body)
    assert no_provider_credential.status_code == 403
    assert no_provider_credential.json()["error"]["code"] == (
        "issue_provider_authorization_required"
    )


def test_remediation_pull_request_rejects_nonempty_request_bodies_before_lookup(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    local_project_factory,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])

    response = owner.client.post(
        f"/api/v1/remediations/{graph['remediation_id']}/pull-request",
        headers=owner.headers(),
        json={"unexpected": True},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "This endpoint does not accept a body."
