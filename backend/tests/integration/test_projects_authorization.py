from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_project_owner_can_create_update_archive_restore_and_list(
    account_pair,
    local_project_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    project_id = project["id"]

    assert owner.request("GET", "/api/v1/projects").json()["items"]
    assert owner.request("GET", f"/api/v1/projects/{project_id}").status_code == 200

    updated = owner.request(
        "PATCH",
        f"/api/v1/projects/{project_id}",
        json={"name": "updated-project", "auto_create_pull_requests": True},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "updated-project"

    archived = owner.request("DELETE", f"/api/v1/projects/{project_id}")
    assert archived.status_code == 204
    assert owner.request("GET", "/api/v1/projects").json()["items"] == []
    assert (
        owner.request("GET", "/api/v1/projects?archived=true").json()["items"][0]["id"]
        == project_id
    )

    restored = owner.request("POST", f"/api/v1/projects/{project_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert other.request("GET", "/api/v1/projects").json()["items"] == []


def test_project_foreign_resource_and_missing_resource_disclosure(
    account_pair,
    local_project_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    project_id = project["id"]

    for method, path, body in (
        ("GET", f"/api/v1/projects/{project_id}", None),
        ("PATCH", f"/api/v1/projects/{project_id}", {"name": "nope"}),
        ("DELETE", f"/api/v1/projects/{project_id}", None),
        ("POST", f"/api/v1/projects/{project_id}/restore", None),
    ):
        response = (
            other.request(method, path, json=body)
            if body
            else other.request(method, path)
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "authorization_denied"
        assert str(owner.user_id) not in response.text
        assert project_id not in response.text

    missing = other.request("GET", f"/api/v1/projects/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "resource_not_found"


def test_project_github_binding_is_owner_scoped_and_unique(
    account_pair,
    credential_factory,
    external_repository_factory,
    github_stub,
) -> None:
    owner, other = account_pair
    credential = credential_factory(owner, access_token="owner-token")
    connection_id = external_repository_factory(owner, UUID(credential["id"]))
    github_stub.repositories_by_token["owner-token"] = [
        {
            "id": 12345,
            "owner": {"login": "octocat"},
            "name": "hello-world",
            "full_name": "octocat/hello-world",
            "private": False,
            "visibility": "public",
            "default_branch": "main",
            "html_url": "https://github.com/octocat/hello-world",
        }
    ]
    github_stub.branches_by_repository["12345"] = [
        {"name": "main", "commit": {"sha": "a" * 40}, "protected": False}
    ]
    body = {
        "name": "github-project",
        "source": "github",
        "repository_id": "12345",
        "branch_name": "main",
        "category": "other",
    }

    created = owner.request("POST", "/api/v1/projects", json=body)
    assert created.status_code == 201, created.text

    duplicate = owner.request("POST", "/api/v1/projects", json=body)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "resource_conflict"

    foreign = other.request("POST", "/api/v1/projects", json=body)
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "authorization_denied"
    assert str(connection_id) not in foreign.text


def test_project_source_validation_csrf_and_authentication(
    account_pair,
    integration_app,
) -> None:
    owner, _ = account_pair
    invalid_local = owner.request(
        "POST",
        "/api/v1/projects",
        json={
            "name": "invalid",
            "source": "local",
            "local_path_hash": "a" * 64,
            "external_repository_id": "github-field",
        },
    )
    assert invalid_local.status_code == 400
    assert invalid_local.json()["error"]["code"] == "invalid_request"

    no_csrf = owner.client.post(
        "/api/v1/projects",
        json={
            "name": "missing-csrf",
            "source": "local",
            "local_path_hash": "b" * 64,
        },
    )
    assert no_csrf.status_code == 403
    assert no_csrf.json()["error"]["code"] == "csrf_validation_failed"

    unauthenticated = TestClient(integration_app).get("/api/v1/projects")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "authentication_required"
