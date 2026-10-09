from __future__ import annotations

import pytest

from integration.github_stub import GithubApiStub

pytestmark = pytest.mark.integration


def _repository(repository_id: int, owner: str, name: str) -> dict[str, object]:
    return {
        "id": repository_id,
        "owner": {"login": owner},
        "name": name,
        "full_name": f"{owner}/{name}",
        "private": True,
        "visibility": "private",
        "default_branch": "main",
        "html_url": f"https://github.com/{owner}/{name}",
    }


def _branch(name: str, sha: str, *, protected: bool = False) -> dict[str, object]:
    return {
        "name": name,
        "commit": {"sha": sha},
        "protected": protected,
    }


def test_authenticated_repository_listing_paginates_and_maps_metadata(
    account_pair,
    credential_factory,
    external_repository_factory,
    github_stub: GithubApiStub,
) -> None:
    owner, _ = account_pair
    credential = credential_factory(owner, access_token="owner-token")
    external_repository_factory(owner, credential["id"])
    github_stub.repositories_by_token["owner-token"] = [
        _repository(12345, "octocat", "hello-world"),
        _repository(67890, "octocat", "second-repo"),
    ]

    first = owner.request(
        "GET", "/api/v1/repositories?source=github&page=1&page_size=1"
    )
    second = owner.request(
        "GET", "/api/v1/repositories?source=github&page=2&page_size=1"
    )

    assert first.status_code == 200, first.text
    assert first.json() == {
        "items": [
            {
                "source": "github",
                "repository_id": "12345",
                "owner_login": "octocat",
                "name": "hello-world",
                "full_name": "octocat/hello-world",
                "visibility": "private",
                "private": True,
                "default_branch": "main",
                "web_url": "https://github.com/octocat/hello-world",
            }
        ],
        "next_page": 2,
    }
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["repository_id"] == "67890"


def test_branch_listing_and_project_creation_persist_server_resolved_metadata(
    account_pair,
    credential_factory,
    external_repository_factory,
    github_stub: GithubApiStub,
) -> None:
    owner, _ = account_pair
    credential = credential_factory(owner, access_token="owner-token")
    external_repository_factory(owner, credential["id"])
    github_stub.repositories_by_token["owner-token"] = [
        _repository(12345, "octocat", "hello-world")
    ]
    commit_sha = "a" * 40
    github_stub.branches_by_repository["12345"] = [
        _branch("main", commit_sha, protected=True),
        _branch("develop", "b" * 40),
    ]

    branches = owner.request(
        "GET",
        "/api/v1/repositories/12345/branches?source=github&page=1&page_size=1",
    )
    created = owner.request(
        "POST",
        "/api/v1/projects",
        json={
            "name": "github project",
            "source": "github",
            "repository_id": "12345",
            "branch_name": "main",
            "category": "business",
        },
    )

    assert branches.status_code == 200, branches.text
    assert branches.json()["items"][0] == {
        "source": "github",
        "repository_id": "12345",
        "name": "main",
        "commit_sha": commit_sha,
        "protected": True,
    }
    assert branches.json()["next_page"] == 2
    assert created.status_code == 201, created.text
    assert created.json()["external_repository_id"] == "12345"
    assert created.json()["repository_owner"] == "octocat"
    assert created.json()["repository_name"] == "hello-world"
    assert created.json()["branch_name"] == "main"
    assert created.json()["repository_visibility"] == "private"
    assert created.json()["current_revision"] == commit_sha
    assert created.json()["imported_at"] is not None


def test_repository_import_isolation_and_duplicate_rollback(
    account_pair,
    credential_factory,
    external_repository_factory,
    github_stub: GithubApiStub,
) -> None:
    owner, other = account_pair
    owner_credential = credential_factory(owner, access_token="owner-token")
    other_credential = credential_factory(other, access_token="other-token")
    external_repository_factory(owner, owner_credential["id"])
    external_repository_factory(other, other_credential["id"])
    github_stub.repositories_by_token["owner-token"] = [
        _repository(12345, "owner", "owner-repo")
    ]
    github_stub.repositories_by_token["other-token"] = [
        _repository(67890, "other", "other-repo")
    ]
    github_stub.branches_by_repository["12345"] = [_branch("main", "a" * 40)]
    github_stub.branches_by_repository["67890"] = [_branch("main", "b" * 40)]

    owner_listing = owner.request("GET", "/api/v1/repositories?source=github")
    other_listing = other.request("GET", "/api/v1/repositories?source=github")
    foreign_import = owner.request(
        "POST",
        "/api/v1/projects",
        json={
            "name": "foreign project",
            "source": "github",
            "repository_id": "67890",
            "branch_name": "main",
            "category": "other",
        },
    )
    valid_body = {
        "name": "owner project",
        "source": "github",
        "repository_id": "12345",
        "branch_name": "main",
        "category": "other",
    }
    created = owner.request("POST", "/api/v1/projects", json=valid_body)
    duplicate = owner.request("POST", "/api/v1/projects", json=valid_body)
    projects = owner.request("GET", "/api/v1/projects")

    assert owner_listing.json()["items"][0]["repository_id"] == "12345"
    assert other_listing.json()["items"][0]["repository_id"] == "67890"
    assert foreign_import.status_code == 404
    assert foreign_import.json()["error"]["code"] == "repository_not_found"
    assert created.status_code == 201, created.text
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "resource_conflict"
    assert len(projects.json()["items"]) == 1


def test_repository_import_maps_auth_missing_not_found_rate_limit_and_outage(
    account_pair,
    credential_factory,
    external_repository_factory,
    github_stub: GithubApiStub,
) -> None:
    owner, other = account_pair
    missing_auth = owner.request("GET", "/api/v1/repositories?source=github")
    credential = credential_factory(other, access_token="other-token")
    external_repository_factory(other, credential["id"])
    github_stub.repositories_by_token["other-token"] = [
        _repository(12345, "octocat", "hello-world")
    ]

    github_stub.failures["/repositories/12345"] = (404, {})
    missing_repository = other.request(
        "GET", "/api/v1/repositories/12345/branches?source=github"
    )
    github_stub.failures.clear()
    github_stub.failures["/repos/octocat/hello-world/branches/missing"] = (404, {})
    missing_branch = other.request(
        "POST",
        "/api/v1/projects",
        json={
            "name": "missing branch",
            "source": "github",
            "repository_id": "12345",
            "branch_name": "missing",
            "category": "other",
        },
    )
    github_stub.failures.clear()
    github_stub.failures["/user/repos"] = (429, {"Retry-After": "17"})
    rate_limited = other.request("GET", "/api/v1/repositories?source=github")
    github_stub.failures.clear()
    github_stub.failures["/user/repos"] = (503, {})
    unavailable = other.request("GET", "/api/v1/repositories?source=github")
    github_stub.failures.clear()
    github_stub.repositories_by_token["other-token"] = [{"id": 12345}]
    malformed = other.request("GET", "/api/v1/repositories?source=github")

    assert missing_auth.status_code == 403
    assert missing_auth.json()["error"]["code"] == "github_authorization_required"
    assert missing_repository.status_code == 404
    assert missing_repository.json()["error"]["code"] == "repository_not_found"
    assert missing_branch.status_code == 404
    assert missing_branch.json()["error"]["code"] == "branch_not_found"
    assert rate_limited.status_code == 429
    assert rate_limited.headers["Retry-After"] == "17"
    assert rate_limited.json()["error"]["code"] == "provider_rate_limited"
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "provider_unavailable"
    assert malformed.status_code == 503
    assert malformed.json()["error"]["code"] == "provider_unavailable"
