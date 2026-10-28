"""External issue-tracker adapters with bounded, credential-free failures."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from issue_tracking.contracts import (
    CreatedExternalIssue,
    GitHubIssueDestination,
    IssueDestination,
    IssuePayload,
    IssueProviderError,
    LinearIssueDestination,
    LinearProject,
    LinearTeam,
)
from issue_tracking.models import IssueProviderName

_LINEAR_ISSUE_CREATE = """
mutation CreateIssue($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { identifier url }
  }
}
"""

_LINEAR_TEAMS = """
query LinearTeams {
  teams(first: 100) {
    nodes { id name key }
  }
}
"""

_LINEAR_TEAM_PROJECTS = """
query LinearTeamProjects($teamId: ID!) {
  team(id: $teamId) {
    projects(first: 100) {
      nodes { id name }
    }
  }
}
"""


class GitHubIssuesProvider:
    name = IssueProviderName.GITHUB

    def __init__(self, *, base_url: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=10.0)

    def create_issue(
        self,
        *,
        access_token: SecretStr,
        destination: IssueDestination,
        payload: IssuePayload,
    ) -> CreatedExternalIssue:
        if not isinstance(destination, GitHubIssueDestination):
            raise IssueProviderError("validation")
        try:
            response = self._client.post(
                f"{self._base_url}/repos/{destination.owner}/{destination.repository}/issues",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token.get_secret_value()}",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
                json={"title": payload.title, "body": payload.body_markdown},
            )
        except httpx.HTTPError as error:
            raise IssueProviderError("unavailable") from error
        _raise_for_status(response)
        try:
            body = response.json()
            identifier = body["number"]
            url = body["html_url"]
        except (KeyError, TypeError, ValueError) as error:
            raise IssueProviderError("malformed_response") from error
        if not isinstance(identifier, int) or not isinstance(url, str) or not url:
            raise IssueProviderError("malformed_response")
        return CreatedExternalIssue(external_id=str(identifier), url=url)

    def verify_destination(
        self,
        *,
        access_token: SecretStr,
        destination: IssueDestination,
    ) -> None:
        if not isinstance(destination, GitHubIssueDestination):
            raise IssueProviderError("validation")
        try:
            response = self._client.get(
                f"{self._base_url}/repos/{destination.owner}/{destination.repository}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token.get_secret_value()}",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
            )
        except httpx.HTTPError as error:
            raise IssueProviderError("unavailable") from error
        _raise_for_status(response)


class LinearIssuesProvider:
    name = IssueProviderName.LINEAR

    def __init__(self, *, api_url: str, client: httpx.Client | None = None) -> None:
        self._api_url = api_url
        self._client = client or httpx.Client(timeout=10.0)

    def create_issue(
        self,
        *,
        access_token: SecretStr,
        destination: IssueDestination,
        payload: IssuePayload,
    ) -> CreatedExternalIssue:
        if not isinstance(destination, LinearIssueDestination):
            raise IssueProviderError("validation")
        issue_input: dict[str, str] = {
            "teamId": destination.team_id,
            "title": payload.title,
            "description": payload.body_markdown,
        }
        if destination.project_id:
            issue_input["projectId"] = destination.project_id
        try:
            response = self._client.post(
                self._api_url,
                headers={"Authorization": f"Bearer {access_token.get_secret_value()}"},
                json={
                    "query": _LINEAR_ISSUE_CREATE,
                    "variables": {"input": issue_input},
                },
            )
        except httpx.HTTPError as error:
            raise IssueProviderError("unavailable") from error
        body = _linear_data(response)
        try:
            result = body["issueCreate"]
            issue = result["issue"]
            identifier = issue["identifier"]
            url = issue["url"]
        except (KeyError, TypeError, ValueError) as error:
            raise IssueProviderError("malformed_response") from error
        if (
            result.get("success") is not True
            or not isinstance(identifier, str)
            or not isinstance(url, str)
        ):
            raise IssueProviderError("validation")
        return CreatedExternalIssue(external_id=identifier, url=url)

    def verify_destination(
        self,
        *,
        access_token: SecretStr,
        destination: IssueDestination,
    ) -> None:
        if not isinstance(destination, LinearIssueDestination):
            raise IssueProviderError("validation")
        if destination.project_id is None:
            raise IssueProviderError("validation")
        projects = self.list_projects(
            access_token=access_token,
            team_id=destination.team_id,
        )
        if destination.project_id not in {project.id for project in projects}:
            raise IssueProviderError("not_found")

    def list_teams(self, *, access_token: SecretStr) -> list[LinearTeam]:
        body = self._graphql(
            access_token=access_token,
            query=_LINEAR_TEAMS,
            variables=None,
        )
        try:
            nodes = body["teams"]["nodes"]
        except (KeyError, TypeError) as error:
            raise IssueProviderError("malformed_response") from error
        if not isinstance(nodes, list):
            raise IssueProviderError("malformed_response")
        teams: list[LinearTeam] = []
        for node in nodes:
            if not isinstance(node, dict):
                raise IssueProviderError("malformed_response")
            identifier = node.get("id")
            name = node.get("name")
            key = node.get("key")
            if (
                not isinstance(identifier, str)
                or not identifier
                or not isinstance(name, str)
                or not name
                or not isinstance(key, str)
                or not key
            ):
                raise IssueProviderError("malformed_response")
            teams.append(LinearTeam(id=identifier, name=name, key=key))
        return teams

    def list_projects(
        self,
        *,
        access_token: SecretStr,
        team_id: str,
    ) -> list[LinearProject]:
        body = self._graphql(
            access_token=access_token,
            query=_LINEAR_TEAM_PROJECTS,
            variables={"teamId": team_id},
        )
        try:
            team = body["team"]
            if team is None:
                raise IssueProviderError("not_found")
            nodes = team["projects"]["nodes"]
        except (KeyError, TypeError) as error:
            raise IssueProviderError("malformed_response") from error
        if not isinstance(nodes, list):
            raise IssueProviderError("malformed_response")
        projects: list[LinearProject] = []
        for node in nodes:
            if not isinstance(node, dict):
                raise IssueProviderError("malformed_response")
            identifier = node.get("id")
            name = node.get("name")
            if (
                not isinstance(identifier, str)
                or not identifier
                or not isinstance(name, str)
                or not name
            ):
                raise IssueProviderError("malformed_response")
            projects.append(LinearProject(id=identifier, name=name))
        return projects

    def _graphql(
        self,
        *,
        access_token: SecretStr,
        query: str,
        variables: dict[str, str] | None,
    ) -> dict[str, Any]:
        try:
            response = self._client.post(
                self._api_url,
                headers={"Authorization": f"Bearer {access_token.get_secret_value()}"},
                json={"query": query, "variables": variables or {}},
            )
        except httpx.HTTPError as error:
            raise IssueProviderError("unavailable") from error
        return _linear_data(response)


def _raise_for_status(response: httpx.Response) -> None:
    if 200 <= response.status_code < 300:
        return
    if response.status_code in {403, 429} and _is_rate_limited(response):
        raise IssueProviderError(
            "rate_limited", retry_after_seconds=_retry_after(response)
        )
    if response.status_code == 401:
        raise IssueProviderError("authorization")
    if response.status_code == 403:
        raise IssueProviderError("access_denied")
    if response.status_code == 404:
        raise IssueProviderError("not_found")
    if response.status_code == 422 or 400 <= response.status_code < 500:
        raise IssueProviderError("validation")
    raise IssueProviderError("unavailable")


def _is_rate_limited(response: httpx.Response) -> bool:
    return (
        response.status_code == 429
        or response.headers.get("x-ratelimit-remaining") == "0"
        or response.headers.get("retry-after") is not None
    )


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("retry-after")
    return int(value) if value and value.isdecimal() else None


def _linear_data(response: httpx.Response) -> dict[str, Any]:
    _raise_for_status(response)
    try:
        body = response.json()
    except ValueError as error:
        raise IssueProviderError("malformed_response") from error
    if not isinstance(body, dict):
        raise IssueProviderError("malformed_response")
    errors = body.get("errors")
    if isinstance(errors, list) and errors:
        codes = {
            error.get("extensions", {}).get("code")
            for error in errors
            if isinstance(error, dict)
            and isinstance(error.get("extensions"), dict)
            and isinstance(error["extensions"].get("code"), str)
        }
        if "RATELIMITED" in codes:
            raise IssueProviderError(
                "rate_limited", retry_after_seconds=_retry_after(response)
            )
        if "UNAUTHENTICATED" in codes:
            raise IssueProviderError("authorization")
        if "FORBIDDEN" in codes:
            raise IssueProviderError("access_denied")
        if "NOT_FOUND" in codes:
            raise IssueProviderError("not_found")
        raise IssueProviderError("validation")
    data = body.get("data")
    if not isinstance(data, dict):
        raise IssueProviderError("malformed_response")
    return data


__all__ = ["GitHubIssuesProvider", "LinearIssuesProvider"]
