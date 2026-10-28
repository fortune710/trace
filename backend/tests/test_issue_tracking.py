from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from auth.config import AuthSettings
from core.v1 import build_router
from issue_tracking.contracts import (
    GitHubIssueDestination,
    IssuePayload,
    IssueProviderError,
    LinearIssueDestination,
)
from issue_tracking.models import IssueProviderName
from issue_tracking.providers import GitHubIssuesProvider, LinearIssuesProvider
from issue_tracking.routes import _audit_issue_creation
from issue_tracking.service import _payload, _project_destination


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://issues.example.test",
        transport=httpx.MockTransport(handler),
    )


def test_github_provider_creates_issue_with_markdown_body() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            json={"number": 21, "html_url": "https://github.com/acme/trace/issues/21"},
        )

    provider = GitHubIssuesProvider(
        base_url="https://issues.example.test",
        client=_client(handler),
    )

    created = provider.create_issue(
        access_token=SecretStr("github-token"),
        destination=GitHubIssueDestination(owner="acme", repository="trace"),
        payload=IssuePayload(title="Unsafe query", body_markdown="## Finding"),
    )

    assert created.external_id == "21"
    assert created.url == "https://github.com/acme/trace/issues/21"
    assert requests[0].url.path == "/repos/acme/trace/issues"
    assert requests[0].headers["authorization"] == "Bearer github-token"
    assert json.loads(requests[0].content) == {
        "title": "Unsafe query",
        "body": "## Finding",
    }


def test_linear_provider_maps_team_project_and_markdown() -> None:
    request_body: dict[str, object] = {}
    team_id = uuid4()
    project_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        request_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "identifier": "ENG-21",
                            "url": "https://linear.app/issue/ENG-21",
                        },
                    }
                }
            },
        )

    provider = LinearIssuesProvider(
        api_url="https://issues.example.test/graphql",
        client=_client(handler),
    )
    created = provider.create_issue(
        access_token=SecretStr("linear-token"),
        destination=LinearIssueDestination(
            team_id=str(team_id), project_id=str(project_id)
        ),
        payload=IssuePayload(title="Unsafe query", body_markdown="## Finding"),
    )

    assert created.external_id == "ENG-21"
    assert created.url == "https://linear.app/issue/ENG-21"
    assert request_body["variables"] == {
        "input": {
            "teamId": str(team_id),
            "projectId": str(project_id),
            "title": "Unsafe query",
            "description": "## Finding",
        }
    }


def test_linear_provider_lists_teams_and_team_projects() -> None:
    requests: list[dict[str, object]] = []
    team_id = uuid4()
    project_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if "LinearTeams" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "teams": {
                            "nodes": [
                                {
                                    "id": str(team_id),
                                    "name": "Engineering",
                                    "key": "ENG",
                                }
                            ]
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "team": {
                        "projects": {
                            "nodes": [{"id": str(project_id), "name": "Trace"}]
                        }
                    }
                }
            },
        )

    provider = LinearIssuesProvider(
        api_url="https://issues.example.test/graphql",
        client=_client(handler),
    )

    teams = provider.list_teams(access_token=SecretStr("linear-token"))
    projects = provider.list_projects(
        access_token=SecretStr("linear-token"),
        team_id=str(team_id),
    )

    assert [(team.id, team.name, team.key) for team in teams] == [
        (str(team_id), "Engineering", "ENG")
    ]
    assert [(project.id, project.name) for project in projects] == [
        (str(project_id), "Trace")
    ]
    assert requests[1]["variables"] == {"teamId": str(team_id)}


def test_linear_provider_rejects_graphql_errors() -> None:
    provider = LinearIssuesProvider(
        api_url="https://issues.example.test/graphql",
        client=_client(
            lambda _request: httpx.Response(
                200,
                json={
                    "errors": [
                        {"extensions": {"code": "FORBIDDEN"}, "message": "no access"}
                    ]
                },
            )
        ),
    )

    with pytest.raises(IssueProviderError, match="access_denied"):
        provider.list_teams(access_token=SecretStr("linear-token"))


def test_providers_verify_the_persisted_destination() -> None:
    github_requests: list[httpx.Request] = []
    github = GitHubIssuesProvider(
        base_url="https://issues.example.test",
        client=_client(
            lambda request: (
                github_requests.append(request),
                httpx.Response(200, json={"id": 1}),
            )[1]
        ),
    )
    github.verify_destination(
        access_token=SecretStr("github-token"),
        destination=GitHubIssueDestination(owner="acme", repository="trace"),
    )

    team_id = uuid4()
    project_id = uuid4()
    linear = LinearIssuesProvider(
        api_url="https://issues.example.test/graphql",
        client=_client(
            lambda _request: httpx.Response(
                200,
                json={
                    "data": {
                        "team": {
                            "projects": {
                                "nodes": [{"id": str(project_id), "name": "Trace"}]
                            }
                        }
                    }
                },
            )
        ),
    )
    linear.verify_destination(
        access_token=SecretStr("linear-token"),
        destination=LinearIssueDestination(
            team_id=str(team_id), project_id=str(project_id)
        ),
    )

    assert github_requests[0].method == "GET"
    assert github_requests[0].url.path == "/repos/acme/trace"


def test_github_issue_destination_uses_the_remediation_project_repository() -> None:
    destination = _project_destination(
        {
            "repository_owner": "trace-owner",
            "repository_name": "trace-repository",
            "issue_tracking_details": {
                "connected_projects": [
                    {
                        "provider": "github",
                        "owner": "untrusted-config-owner",
                        "project": "untrusted-config-repository",
                    }
                ]
            },
        },
        provider=IssueProviderName.GITHUB,
    )

    assert destination == GitHubIssueDestination(
        owner="trace-owner",
        repository="trace-repository",
    )


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "authorization"),
        (403, "access_denied"),
        (404, "not_found"),
        (422, "validation"),
    ],
)
def test_provider_maps_non_success_responses_to_safe_error_kinds(
    status_code: int,
    expected: str,
) -> None:
    provider = GitHubIssuesProvider(
        base_url="https://issues.example.test",
        client=_client(lambda _request: httpx.Response(status_code)),
    )

    with pytest.raises(IssueProviderError, match=expected):
        provider.create_issue(
            access_token=SecretStr("token"),
            destination=GitHubIssueDestination(owner="acme", repository="trace"),
            payload=IssuePayload(title="Title", body_markdown="Body"),
        )


def test_provider_maps_rate_limits_and_transport_failures() -> None:
    rate_limited = GitHubIssuesProvider(
        base_url="https://issues.example.test",
        client=_client(
            lambda _request: httpx.Response(429, headers={"Retry-After": "37"})
        ),
    )
    with pytest.raises(IssueProviderError) as rate_limit_error:
        rate_limited.create_issue(
            access_token=SecretStr("token"),
            destination=GitHubIssueDestination(owner="acme", repository="trace"),
            payload=IssuePayload(title="Title", body_markdown="Body"),
        )
    assert rate_limit_error.value.kind == "rate_limited"
    assert rate_limit_error.value.retry_after_seconds == 37

    secondary_rate_limited = GitHubIssuesProvider(
        base_url="https://issues.example.test",
        client=_client(
            lambda _request: httpx.Response(
                403,
                headers={"X-RateLimit-Remaining": "0", "Retry-After": "11"},
            )
        ),
    )
    with pytest.raises(IssueProviderError, match="rate_limited"):
        secondary_rate_limited.verify_destination(
            access_token=SecretStr("token"),
            destination=GitHubIssueDestination(owner="acme", repository="trace"),
        )

    unavailable = GitHubIssuesProvider(
        base_url="https://issues.example.test",
        client=_client(
            lambda _request: (_ for _ in ()).throw(httpx.ConnectError("down"))
        ),
    )
    with pytest.raises(IssueProviderError, match="unavailable"):
        unavailable.create_issue(
            access_token=SecretStr("token"),
            destination=GitHubIssueDestination(owner="acme", repository="trace"),
            payload=IssuePayload(title="Title", body_markdown="Body"),
        )


def test_provider_rejects_malformed_success_responses() -> None:
    provider = LinearIssuesProvider(
        api_url="https://issues.example.test/graphql",
        client=_client(lambda _request: httpx.Response(200, json={"data": {}})),
    )

    with pytest.raises(IssueProviderError, match="malformed_response"):
        provider.create_issue(
            access_token=SecretStr("token"),
            destination=LinearIssueDestination(team_id=str(uuid4())),
            payload=IssuePayload(title="Title", body_markdown="Body"),
        )


def test_issue_payload_includes_remediation_and_redacts_secrets() -> None:
    finding = {
        "id": uuid4(),
        "title": "Leaked token sk-example_secret_key_123456789012345",
        "explanation": "The token sk-example_secret_key_123456789012345 is exposed.",
        "severity": "high",
        "category": "security",
        "evidence": "token sk-example_secret_key_123456789012345",
        "source_location": "src/auth.py:12",
        "recommendation": "Rotate token sk-example_secret_key_123456789012345",
    }
    review = {"id": uuid4(), "source_revision": "abc123"}
    remediation = {
        "prompt_text": "Remove sk-example_secret_key_123456789012345",
        "proposed_diff": "-sk-example_secret_key_123456789012345\n+[REDACTED]",
    }

    payload = _payload(finding=finding, review=review, remediation=remediation)

    assert "## Proposed implementation prompt" in payload.body_markdown
    assert "## Proposed diff" in payload.body_markdown
    assert "## Source location" not in payload.body_markdown
    assert "```diff" in payload.body_markdown
    assert "sk-example_secret_key_123456789012345" not in payload.title
    assert "sk-example_secret_key_123456789012345" not in payload.body_markdown


def test_issue_link_api_routes_are_registered() -> None:
    router = build_router(AuthSettings())

    def flattened_routes(router, prefix: str = ""):
        for route in router.routes:
            if hasattr(route, "path"):
                yield prefix + route.path, route.methods
                continue
            yield from flattened_routes(
                route.original_router,
                prefix + route.include_context.prefix,
            )

    routes = list(flattened_routes(router))
    paths = {path for path, _methods in routes}

    assert {
        "/api/v1/issue-tracking/linear/teams",
        "/api/v1/issue-tracking/linear/teams/{team_id}/projects",
        "/api/v1/projects/{project_id}/issue-tracking",
        "/api/v1/findings/{finding_id}/issue-links/preview",
        "/api/v1/issue-links/{link_id}",
    } <= paths
    assert "/api/v1/remediations/{remediation_id}/issue" in paths
    assert not any(
        path == "/api/v1/findings/{finding_id}/issue-links" and "POST" in methods
        for path, methods in routes
    )


def test_issue_creation_audit_event_contains_only_operational_data() -> None:
    events: list[dict[str, object]] = []

    class Recorder:
        def create_event(self, **kwargs: object) -> None:
            events.append(kwargs)

    request = SimpleNamespace(
        state=SimpleNamespace(request_id="request-123", principal_user_id=uuid4())
    )
    _audit_issue_creation(
        request=request,
        recorder=Recorder(),  # type: ignore[arg-type]
        provider=IssueProviderName.GITHUB,
        destination_id="acme/trace",
        outcome="accepted",
        reason="created",
        status_code=201,
    )

    assert events == [
        {
            "event_type": "issue_tracking.create.accepted",
            "request_id": "request-123",
            "owner_id": request.state.principal_user_id,
            "fields": {
                "provider": "github",
                "destination_id": "acme/trace",
                "outcome": "accepted",
                "reason": "created",
                "status_code": "201",
            },
        }
    ]


def test_issue_creation_rejection_audit_event_keeps_provider_and_no_ticket_content() -> (
    None
):
    events: list[dict[str, object]] = []

    class Recorder:
        def create_event(self, **kwargs: object) -> None:
            events.append(kwargs)

    request = SimpleNamespace(
        state=SimpleNamespace(request_id="request-456", principal_user_id=uuid4())
    )
    _audit_issue_creation(
        request=request,
        recorder=Recorder(),  # type: ignore[arg-type]
        provider=IssueProviderName.LINEAR,
        destination_id="unavailable",
        outcome="rejected",
        reason="authorization_required",
        status_code=403,
    )

    fields = events[0]["fields"]
    assert fields == {
        "provider": "linear",
        "destination_id": "unavailable",
        "outcome": "rejected",
        "reason": "authorization_required",
        "status_code": "403",
    }
    assert "token" not in repr(events[0]).casefold()
    assert "body_markdown" not in repr(events[0])
