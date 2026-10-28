"""Provider-independent issue creation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr

from issue_tracking.models import IssueProviderName


@dataclass(frozen=True, slots=True)
class GitHubIssueDestination:
    owner: str
    repository: str

    @property
    def id(self) -> str:
        return f"{self.owner}/{self.repository}"


@dataclass(frozen=True, slots=True)
class LinearIssueDestination:
    team_id: str
    project_id: str | None = None

    @property
    def id(self) -> str:
        return f"{self.team_id}:{self.project_id or ''}"


IssueDestination = GitHubIssueDestination | LinearIssueDestination


@dataclass(frozen=True, slots=True)
class IssuePayload:
    title: str
    body_markdown: str


@dataclass(frozen=True, slots=True)
class CreatedExternalIssue:
    external_id: str
    url: str


@dataclass(frozen=True, slots=True)
class LinearTeam:
    id: str
    name: str
    key: str


@dataclass(frozen=True, slots=True)
class LinearProject:
    id: str
    name: str


class IssueProvider(Protocol):
    name: IssueProviderName

    def verify_destination(
        self,
        *,
        access_token: SecretStr,
        destination: IssueDestination,
    ) -> None: ...

    def create_issue(
        self,
        *,
        access_token: SecretStr,
        destination: IssueDestination,
        payload: IssuePayload,
    ) -> CreatedExternalIssue: ...


class IssueProviderError(RuntimeError):
    def __init__(self, kind: str, *, retry_after_seconds: int | None = None) -> None:
        self.kind = kind
        self.retry_after_seconds = retry_after_seconds
        super().__init__(kind)


__all__ = [
    "CreatedExternalIssue",
    "GitHubIssueDestination",
    "IssueDestination",
    "IssuePayload",
    "IssueProvider",
    "IssueProviderError",
    "LinearIssueDestination",
    "LinearProject",
    "LinearTeam",
]
