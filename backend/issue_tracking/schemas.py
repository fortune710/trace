"""HTTP contracts for creating external issue links."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from issue_tracking.models import IssueLinkState, IssueProviderName


class IssueRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IssuePreviewRequest(IssueRequestModel):
    provider: IssueProviderName


class IssuePreviewResponse(IssueRequestModel):
    title: str
    body_markdown: str


class ConnectedIssueProject(IssueRequestModel):
    provider: IssueProviderName
    owner: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    project: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]


class IssueTrackingDetails(IssueRequestModel):
    connected_projects: list[ConnectedIssueProject] = Field(
        default_factory=list, max_length=64
    )


class LinearTeamResponse(IssueRequestModel):
    id: UUID
    name: str
    key: str


class LinearProjectResponse(IssueRequestModel):
    id: UUID
    name: str


class IssueLinkResponse(IssueRequestModel):
    id: UUID
    finding_id: UUID
    provider: IssueProviderName
    destination_id: str
    external_identifier: str | None
    external_url: str | None
    state: IssueLinkState
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ConnectedIssueProject",
    "IssueLinkResponse",
    "IssuePreviewRequest",
    "IssuePreviewResponse",
    "IssueTrackingDetails",
    "LinearProjectResponse",
    "LinearTeamResponse",
]
