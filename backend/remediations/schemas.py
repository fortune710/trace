"""Remediation API schemas."""

from __future__ import annotations

from issue_tracking.models import IssueProviderName
from resources.schemas import (
    RemediationPromptResponse,
    RemediationResponse,
    RequestModel,
)


class ProjectIssueDestinationRequest(RequestModel):
    """Issue-tracking destination resolved from the remediation's project."""

    provider: IssueProviderName


class RemediationIssueCreate(RequestModel):
    destination: ProjectIssueDestinationRequest


__all__ = [
    "ProjectIssueDestinationRequest",
    "RemediationIssueCreate",
    "RemediationPromptResponse",
    "RemediationResponse",
]
