"""Protected owner-scoped external issue-link APIs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Request, status

from audit.emit import enqueue_audit
from audit.outbox import AuditRecorder
from auth.config import AuthSettings
from auth.credential_service import CredentialService
from auth.credentials import credential_cipher_from_settings
from auth.csrf import validate_csrf_token
from auth.errors import AuthError
from auth.principal import CurrentPrincipal
from auth.tokens import decode_base64url_key
from db.session import get_engine
from issue_tracking.catalog import LinearCatalogService
from issue_tracking.contracts import IssueProvider
from issue_tracking.models import IssueProviderName
from issue_tracking.project_service import ProjectIssueTrackingService
from issue_tracking.providers import GitHubIssuesProvider, LinearIssuesProvider
from issue_tracking.schemas import (
    IssueLinkResponse,
    IssuePreviewRequest,
    IssuePreviewResponse,
    IssueTrackingDetails,
    LinearProjectResponse,
    LinearTeamResponse,
)
from issue_tracking.service import IssueLinkResult, IssueTrackingService
from remediations.schemas import RemediationIssueCreate

logger = logging.getLogger("trace.issue_tracking")


def build_router(
    settings: AuthSettings,
    audit_recorder: AuditRecorder | None = None,
) -> APIRouter:
    router = APIRouter()

    service, credential_service = _issue_services(settings)

    def linear_catalog_service() -> LinearCatalogService:
        return LinearCatalogService(
            provider=LinearIssuesProvider(api_url=settings.linear_api_url),
            engine=get_engine(),
            credential_service=credential_service(),
        )

    def project_issue_tracking_service() -> ProjectIssueTrackingService:
        return ProjectIssueTrackingService(
            engine=get_engine(),
            linear_catalog_service=linear_catalog_service(),
        )

    @router.get(
        "/projects/{project_id}/issue-tracking",
        response_model=IssueTrackingDetails,
    )
    def get_project_issue_tracking(
        project_id: UUID,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        return project_issue_tracking_service().get(
            owner_id=principal.user_id,
            project_id=project_id,
        )

    @router.patch(
        "/projects/{project_id}/issue-tracking",
        response_model=IssueTrackingDetails,
    )
    def update_project_issue_tracking(
        request: Request,
        project_id: UUID,
        body: IssueTrackingDetails,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        values = body.model_dump(mode="json")
        connected_projects = values["connected_projects"]
        assert isinstance(connected_projects, list)
        return project_issue_tracking_service().update(
            owner_id=principal.user_id,
            project_id=project_id,
            connected_projects=connected_projects,
        )

    @router.get(
        "/issue-tracking/linear/teams",
        response_model=list[LinearTeamResponse],
    )
    def list_linear_teams(principal: CurrentPrincipal) -> list[dict[str, str]]:
        teams = linear_catalog_service().list_teams(owner_id=principal.user_id)
        return [{"id": team.id, "name": team.name, "key": team.key} for team in teams]

    @router.get(
        "/issue-tracking/linear/teams/{team_id}/projects",
        response_model=list[LinearProjectResponse],
    )
    def list_linear_projects(
        team_id: UUID,
        principal: CurrentPrincipal,
    ) -> list[dict[str, str]]:
        projects = linear_catalog_service().list_projects(
            owner_id=principal.user_id,
            team_id=team_id,
        )
        return [{"id": project.id, "name": project.name} for project in projects]

    @router.post(
        "/findings/{finding_id}/issue-links/preview",
        response_model=IssuePreviewResponse,
    )
    def preview_issue(
        finding_id: UUID,
        body: IssuePreviewRequest,
        principal: CurrentPrincipal,
    ) -> dict[str, str]:
        issue_service = service(body.provider)
        payload = issue_service.preview_issue(
            owner_id=principal.user_id,
            finding_id=finding_id,
        )
        return {"title": payload.title, "body_markdown": payload.body_markdown}

    @router.get(
        "/findings/{finding_id}/issue-links",
        response_model=list[IssueLinkResponse],
    )
    def list_issue_links(
        finding_id: UUID,
        principal: CurrentPrincipal,
    ) -> list[dict[str, object]]:
        # Reading is provider-independent; any service instance can query links.
        results = service(IssueProviderName.GITHUB).list_links(
            owner_id=principal.user_id,
            finding_id=finding_id,
        )
        return [_response(result) for result in results]

    @router.get("/issue-links/{link_id}", response_model=IssueLinkResponse)
    def get_issue_link(link_id: UUID, principal: CurrentPrincipal) -> dict[str, object]:
        result = service(IssueProviderName.GITHUB).get_link(
            owner_id=principal.user_id,
            link_id=link_id,
        )
        return _response(result)

    return router


def build_remediation_issue_router(
    settings: AuthSettings,
    audit_recorder: AuditRecorder | None = None,
) -> APIRouter:
    """Build the remediation-scoped external issue creation route."""

    router = APIRouter()
    service, _credential_service = _issue_services(settings)

    @router.post(
        "/remediations/{remediation_id}/issue",
        response_model=IssueLinkResponse,
        status_code=201,
    )
    def create_remediation_issue(
        request: Request,
        remediation_id: UUID,
        body: RemediationIssueCreate,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        provider = body.destination.provider
        try:
            result = service(provider).create_remediation_issue(
                owner_id=principal.user_id,
                remediation_id=remediation_id,
            )
        except AuthError as error:
            _audit_issue_creation(
                request=request,
                recorder=audit_recorder,
                provider=provider,
                destination_id="unavailable",
                outcome="rejected",
                reason=error.reason,
                status_code=error.status_code,
            )
            raise
        _audit_issue_creation(
            request=request,
            recorder=audit_recorder,
            provider=result.provider,
            destination_id=result.destination_id,
            outcome="accepted",
            reason=result.state.value,
            status_code=status.HTTP_201_CREATED,
        )
        return _response(result)

    return router


def _issue_services(
    settings: AuthSettings,
) -> tuple[
    Callable[[IssueProviderName], IssueTrackingService],
    Callable[[], CredentialService],
]:
    @lru_cache
    def credential_service() -> CredentialService:
        return CredentialService(
            engine=get_engine(),
            cipher=credential_cipher_from_settings(settings),
        )

    def service(provider: IssueProviderName) -> IssueTrackingService:
        adapter: IssueProvider
        if provider is IssueProviderName.GITHUB:
            adapter = GitHubIssuesProvider(base_url=settings.github_api_url)
        else:
            adapter = LinearIssuesProvider(api_url=settings.linear_api_url)
        return IssueTrackingService(
            provider=adapter,
            engine=get_engine(),
            credential_service=credential_service(),
        )

    return service, credential_service


def _response(result: IssueLinkResult) -> dict[str, object]:
    return {
        "id": result.id,
        "finding_id": result.finding_id,
        "provider": result.provider,
        "destination_id": result.destination_id,
        "external_identifier": result.external_identifier,
        "external_url": result.external_url,
        "state": result.state,
        "failure_code": result.failure_code,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
    }


def _audit_issue_creation(
    *,
    request: Request,
    recorder: AuditRecorder | None,
    provider: IssueProviderName,
    destination_id: str,
    outcome: str,
    reason: str,
    status_code: int,
) -> None:
    request_id = getattr(request.state, "request_id", "unavailable")
    logger.info(
        "issue_tracking_event",
        extra={
            "issue_tracking": {
                "request_id": request_id,
                "provider": provider.value,
                "destination_id": destination_id,
                "outcome": outcome,
                "reason": reason,
                "status_code": status_code,
            }
        },
    )
    enqueue_audit(
        recorder,
        event_type=f"issue_tracking.create.{outcome}",
        request_id=request_id,
        owner_id=getattr(request.state, "principal_user_id", None),
        fields={
            "provider": provider.value,
            "destination_id": destination_id,
            "outcome": outcome,
            "reason": reason,
            "status_code": str(status_code),
        },
    )


def _require_csrf(
    request: Request,
    principal: CurrentPrincipal,
    settings: AuthSettings,
) -> None:
    if settings.csrf_hmac_key is None:
        raise AuthError(
            code="csrf_validation_failed",
            message="The request could not be processed.",
            status_code=403,
            event="request",
            reason="csrf_validation_failed",
        )
    key = decode_base64url_key(
        settings.csrf_hmac_key.get_secret_value(),
        name="AUTH_CSRF_HMAC_KEY",
    )
    if not validate_csrf_token(
        cookie_token=request.cookies.get(settings.csrf_cookie_name),
        header_token=request.headers.get("X-CSRF-Token"),
        session_id=principal.session_id,
        key=key,
    ):
        raise AuthError(
            code="csrf_validation_failed",
            message="The request could not be processed.",
            status_code=403,
            event="request",
            reason="csrf_validation_failed",
        )


__all__ = ["build_router"]
