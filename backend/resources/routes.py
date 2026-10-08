from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response, status

from audit.emit import enqueue_audit
from audit.outbox import AuditRecorder
from auth.audit import AuditHasher, log_auth_event
from auth.config import AuthSettings
from auth.credential_service import (
    CredentialConflict,
    CredentialNotFound,
    CredentialPayloadError,
    CredentialService,
    CredentialServiceError,
)
from auth.credentials import credential_cipher_from_settings
from auth.csrf import validate_csrf_token
from auth.errors import (
    AuthError,
    ResourceConflict,
    ResourceNotFound,
    ResourceUnavailable,
)
from auth.principal import CurrentPrincipal
from auth.rate_limit import (
    AUTH_RATE_LIMIT_POLICIES,
    enforce_rate_limit,
    rate_limiter_from_settings,
)
from auth.tokens import decode_base64url_key
from db.session import get_engine
from db.types import RepositorySource
from external_repositories.service import RepositoryService
from findings.models import FindingSeverity, FindingStatus
from projects.models import ProjectCategory
from remediations.models import RemediationStatus
from resources.schemas import (
    AgentCreate,
    AgentPage,
    AgentResponse,
    AgentUpdate,
    CredentialCreate,
    CredentialPage,
    CredentialResponse,
    FindingPage,
    FindingResponse,
    FindingUpdate,
    LocalFileBackupResponse,
    ProjectCreate,
    ProjectPage,
    ProjectResponse,
    ProjectUpdate,
    PullRequestResponse,
    RemediationCreate,
    RemediationResponse,
    ReviewCreate,
    ReviewPage,
    ReviewResponse,
)
from resources.services import (
    AgentService,
    ArtifactService,
    FindingService,
    ProjectService,
    ReviewDispatcher,
    ReviewDispatchUnavailable,
    ReviewService,
)
from reviews.models import ReviewCategory, ReviewStatus


def install_resource_routes(
    app: FastAPI,
    settings: AuthSettings,
    audit_hasher: AuditHasher | None = None,
    dispatcher: ReviewDispatcher | None = None,
    audit_recorder: AuditRecorder | None = None,
) -> None:
    @lru_cache
    def repository_service() -> RepositoryService:
        return RepositoryService(
            engine=get_engine(),
            credential_service=CredentialService(
                engine=get_engine(),
                cipher=credential_cipher_from_settings(settings),
            ),
            settings=settings,
        )

    @lru_cache
    def project_service() -> ProjectService:
        return ProjectService(get_engine(), repository_service=repository_service())

    @lru_cache
    def agent_service() -> AgentService:
        return AgentService(get_engine())

    @lru_cache
    def review_service() -> ReviewService:
        return ReviewService(get_engine(), dispatcher)

    @lru_cache
    def finding_service() -> FindingService:
        return FindingService(get_engine())

    @lru_cache
    def artifact_service() -> ArtifactService:
        return ArtifactService(get_engine())

    @lru_cache
    def credential_service() -> CredentialService:
        return CredentialService(
            engine=get_engine(), cipher=credential_cipher_from_settings(settings)
        )

    @lru_cache
    def resource_rate_limiter():
        return rate_limiter_from_settings(settings)

    async def require_project_write_limit(principal: CurrentPrincipal) -> None:
        await enforce_rate_limit(
            resource_rate_limiter(),
            policy=AUTH_RATE_LIMIT_POLICIES["resource.project_write.user"],
            subject=str(principal.user_id),
        )

    async def require_review_submit_limit(principal: CurrentPrincipal) -> None:
        await enforce_rate_limit(
            resource_rate_limiter(),
            policy=AUTH_RATE_LIMIT_POLICIES["resource.review_submit.user"],
            subject=str(principal.user_id),
        )

    async def require_credential_write_limit(principal: CurrentPrincipal) -> None:
        await enforce_rate_limit(
            resource_rate_limiter(),
            policy=AUTH_RATE_LIMIT_POLICIES["resource.credential_write.user"],
            subject=str(principal.user_id),
        )

    @app.get("/projects", response_model=ProjectPage)
    def list_projects(
        principal: CurrentPrincipal,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
        source: RepositorySource | None = None,
        category: ProjectCategory | None = None,
        archived: bool = False,
    ) -> dict[str, object]:
        items, next_offset = project_service().list(
            owner_id=principal.user_id,
            source=source,
            category=category,
            archived=archived,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {"items": items, "next_offset": next_offset}

    @app.post(
        "/projects",
        response_model=ProjectResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_project_write_limit)],
    )
    def create_project(
        request: Request, body: ProjectCreate, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = project_service().create(
            owner_id=principal.user_id,
            values=body.model_dump(exclude_unset=True),
        )
        _audit(request, audit_hasher, audit_recorder, "project", "created")
        return result

    @app.get("/projects/{project_id}", response_model=ProjectResponse)
    def get_project(project_id: UUID, principal: CurrentPrincipal) -> dict[str, object]:
        return project_service().get(owner_id=principal.user_id, project_id=project_id)

    @app.patch(
        "/projects/{project_id}",
        response_model=ProjectResponse,
        dependencies=[Depends(require_project_write_limit)],
    )
    def update_project(
        request: Request,
        project_id: UUID,
        body: ProjectUpdate,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = project_service().update(
            owner_id=principal.user_id,
            project_id=project_id,
            values=body.model_dump(exclude_unset=True),
        )
        _audit(request, audit_hasher, audit_recorder, "project", "updated")
        return result

    @app.delete(
        "/projects/{project_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_project_write_limit)],
    )
    def archive_project(
        request: Request, project_id: UUID, principal: CurrentPrincipal
    ) -> Response:
        _require_csrf(request, principal, settings)
        project_service().archive(owner_id=principal.user_id, project_id=project_id)
        _audit(request, audit_hasher, audit_recorder, "project", "archived")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/projects/{project_id}/restore",
        response_model=ProjectResponse,
        dependencies=[Depends(require_project_write_limit)],
    )
    def restore_project(
        request: Request, project_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = project_service().restore(
            owner_id=principal.user_id, project_id=project_id
        )
        _audit(request, audit_hasher, audit_recorder, "project", "restored")
        return result

    @app.get("/agents", response_model=AgentPage)
    def list_agents(
        principal: CurrentPrincipal,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
        include_disabled: bool = False,
    ) -> dict[str, object]:
        items, next_offset = agent_service().list(
            owner_id=principal.user_id,
            include_disabled=include_disabled,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {"items": items, "next_offset": next_offset}

    @app.post(
        "/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED
    )
    def create_agent(
        request: Request, body: AgentCreate, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = agent_service().create(
            owner_id=principal.user_id,
            values=body.model_dump(),
        )
        _audit(request, audit_hasher, audit_recorder, "agent", "created")
        return result

    @app.get("/agents/{agent_id}", response_model=AgentResponse)
    def get_agent(agent_id: UUID, principal: CurrentPrincipal) -> dict[str, object]:
        return agent_service().get(owner_id=principal.user_id, agent_id=agent_id)

    @app.patch("/agents/{agent_id}", response_model=AgentResponse)
    def update_agent(
        request: Request,
        agent_id: UUID,
        body: AgentUpdate,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = agent_service().update(
            owner_id=principal.user_id,
            agent_id=agent_id,
            values=body.model_dump(exclude_unset=True),
        )
        _audit(request, audit_hasher, audit_recorder, "agent", "updated")
        return result

    @app.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
    def disable_agent(
        request: Request, agent_id: UUID, principal: CurrentPrincipal
    ) -> Response:
        _require_csrf(request, principal, settings)
        agent_service().disable(owner_id=principal.user_id, agent_id=agent_id)
        _audit(request, audit_hasher, audit_recorder, "agent", "disabled")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/reviews",
        response_model=ReviewResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_review_submit_limit)],
    )
    def create_review(
        request: Request, body: ReviewCreate, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        try:
            result = review_service().create(
                owner_id=principal.user_id, values=body.model_dump()
            )
        except ReviewDispatchUnavailable as error:
            raise ResourceUnavailable() from error
        _audit(request, audit_hasher, audit_recorder, "review", "queued")
        return result

    @app.get("/reviews", response_model=ReviewPage)
    def list_reviews(
        principal: CurrentPrincipal,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
        project_id: UUID | None = None,
        status: ReviewStatus | None = None,
    ) -> dict[str, object]:
        items, next_offset = review_service().list(
            owner_id=principal.user_id,
            project_id=project_id,
            status=status,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {"items": items, "next_offset": next_offset}

    @app.get("/reviews/{review_id}", response_model=ReviewResponse)
    def get_review(review_id: UUID, principal: CurrentPrincipal) -> dict[str, object]:
        return review_service().get(owner_id=principal.user_id, review_id=review_id)

    @app.post("/reviews/{review_id}/cancel", response_model=ReviewResponse)
    def cancel_review(
        request: Request, review_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = review_service().cancel(
            owner_id=principal.user_id, review_id=review_id
        )
        _audit(request, audit_hasher, audit_recorder, "review", "cancelled")
        return result

    @app.post("/reviews/{review_id}/retry", response_model=ReviewResponse)
    def retry_review(
        request: Request, review_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        try:
            result = review_service().retry(
                owner_id=principal.user_id, review_id=review_id
            )
        except ReviewDispatchUnavailable as error:
            raise ResourceUnavailable() from error
        _audit(request, audit_hasher, audit_recorder, "review", "retried")
        return result

    @app.get("/reviews/{review_id}/findings", response_model=FindingPage)
    def list_findings(
        review_id: UUID,
        principal: CurrentPrincipal,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
        category: ReviewCategory | None = None,
        severity: FindingSeverity | None = None,
        status: FindingStatus | None = None,
        agent_id: UUID | None = None,
    ) -> dict[str, object]:
        items, next_offset = finding_service().list_for_review(
            owner_id=principal.user_id,
            review_id=review_id,
            filters={
                "category": category,
                "severity": severity,
                "status": status,
                "agent_id": agent_id,
            },
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {"items": items, "next_offset": next_offset}

    @app.get("/findings/{finding_id}", response_model=FindingResponse)
    def get_finding(finding_id: UUID, principal: CurrentPrincipal) -> dict[str, object]:
        return finding_service().get(owner_id=principal.user_id, finding_id=finding_id)

    @app.patch("/findings/{finding_id}", response_model=FindingResponse)
    def update_finding(
        request: Request,
        finding_id: UUID,
        body: FindingUpdate,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = finding_service().update_status(
            owner_id=principal.user_id, finding_id=finding_id, status=body.status
        )
        _audit(request, audit_hasher, audit_recorder, "finding", "triaged")
        return result

    @app.post(
        "/findings/{finding_id}/remediations",
        response_model=RemediationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_remediation(
        request: Request,
        finding_id: UUID,
        body: RemediationCreate,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = artifact_service().create_remediation(
            owner_id=principal.user_id,
            finding_id=finding_id,
            proposed_diff=body.proposed_diff,
        )
        _audit(request, audit_hasher, audit_recorder, "remediation", "created")
        return result

    @app.get(
        "/findings/{finding_id}/remediations", response_model=list[RemediationResponse]
    )
    def list_remediations(
        finding_id: UUID, principal: CurrentPrincipal
    ) -> list[dict[str, object]]:
        return artifact_service().list_remediations(
            owner_id=principal.user_id, finding_id=finding_id
        )

    @app.get("/remediations/{remediation_id}", response_model=RemediationResponse)
    def get_remediation(
        remediation_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        return artifact_service().get_remediation(
            owner_id=principal.user_id, remediation_id=remediation_id
        )

    @app.post(
        "/remediations/{remediation_id}/approve", response_model=RemediationResponse
    )
    def approve_remediation(
        request: Request, remediation_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = artifact_service().set_remediation_status(
            owner_id=principal.user_id,
            remediation_id=remediation_id,
            status=RemediationStatus.APPROVED,
        )
        _audit(request, audit_hasher, audit_recorder, "remediation", "approved")
        return result

    @app.post(
        "/remediations/{remediation_id}/reject", response_model=RemediationResponse
    )
    def reject_remediation(
        request: Request, remediation_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = artifact_service().set_remediation_status(
            owner_id=principal.user_id,
            remediation_id=remediation_id,
            status=RemediationStatus.REJECTED,
        )
        _audit(request, audit_hasher, audit_recorder, "remediation", "rejected")
        return result

    @app.get(
        "/remediations/{remediation_id}/pull-request",
        response_model=PullRequestResponse,
    )
    def get_remediation_pull_request(
        remediation_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        return artifact_service().get_pull_request(
            owner_id=principal.user_id, remediation_id=remediation_id
        )

    @app.get(
        "/remediations/{remediation_id}/local-file-backup",
        response_model=LocalFileBackupResponse,
    )
    def get_remediation_local_backup(
        remediation_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        return artifact_service().get_local_backup(
            owner_id=principal.user_id, remediation_id=remediation_id
        )

    @app.get("/pull-requests/{artifact_id}", response_model=PullRequestResponse)
    def get_pull_request(
        artifact_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        return artifact_service().get_pull_request_by_id(
            owner_id=principal.user_id, artifact_id=artifact_id
        )

    @app.get(
        "/local-file-backups/{artifact_id}", response_model=LocalFileBackupResponse
    )
    def get_local_backup(
        artifact_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        return artifact_service().get_local_backup_by_id(
            owner_id=principal.user_id, artifact_id=artifact_id
        )

    @app.get("/credentials", response_model=CredentialPage)
    def list_credentials(
        principal: CurrentPrincipal,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, object]:
        items, next_offset = credential_service().list_metadata(
            owner_id=principal.user_id,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {
            "items": [_credential_response(item) for item in items],
            "next_offset": next_offset,
        }

    @app.post(
        "/credentials",
        response_model=CredentialResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_credential_write_limit)],
    )
    def create_credential(
        request: Request, body: CredentialCreate, principal: CurrentPrincipal
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        result = _credential_operation(
            lambda: credential_service().create_or_replace(
                owner_id=principal.user_id,
                provider=body.provider,
                kind=body.kind,
                payload=body.payload,
            )
        )
        _audit(request, audit_hasher, audit_recorder, "credential", "created")
        return _credential_response(result)

    @app.get("/credentials/{credential_id}", response_model=CredentialResponse)
    def get_credential(
        credential_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        return _credential_response(
            _credential_operation(
                lambda: credential_service().metadata(
                    owner_id=principal.user_id, credential_id=credential_id
                )
            )
        )

    @app.post(
        "/credentials/{credential_id}/rotate",
        response_model=CredentialResponse,
        dependencies=[Depends(require_credential_write_limit)],
    )
    def rotate_credential(
        request: Request,
        credential_id: UUID,
        body: CredentialCreate,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        metadata = _credential_operation(
            lambda: credential_service().metadata(
                owner_id=principal.user_id, credential_id=credential_id
            )
        )
        if metadata.provider != body.provider or metadata.kind != body.kind:
            raise AuthError(
                code="invalid_request",
                message="The request could not be processed.",
                status_code=400,
                event="request",
                reason="invalid_input",
            )
        result = _credential_operation(
            lambda: credential_service().replace_payload(
                owner_id=principal.user_id,
                credential_id=credential_id,
                payload=body.payload,
            )
        )
        _audit(request, audit_hasher, audit_recorder, "credential", "rotated")
        return _credential_response(result)

    @app.delete(
        "/credentials/{credential_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_credential_write_limit)],
    )
    def revoke_credential(
        request: Request, credential_id: UUID, principal: CurrentPrincipal
    ) -> Response:
        _require_csrf(request, principal, settings)
        _credential_operation(
            lambda: credential_service().revoke(
                owner_id=principal.user_id, credential_id=credential_id
            )
        )
        _audit(request, audit_hasher, audit_recorder, "credential", "revoked")
        return Response(status_code=status.HTTP_204_NO_CONTENT)


def _require_csrf(request: Request, principal, settings: AuthSettings) -> None:
    if settings.csrf_hmac_key is None:
        raise AuthError(
            code="csrf_validation_failed",
            message="The request could not be validated.",
            status_code=403,
            event="csrf",
            reason="configuration_missing",
        )
    key = decode_base64url_key(
        settings.csrf_hmac_key.get_secret_value(), name="AUTH_CSRF_HMAC_KEY"
    )
    if not validate_csrf_token(
        cookie_token=request.cookies.get(settings.csrf_cookie_name),
        header_token=request.headers.get("X-CSRF-Token"),
        session_id=principal.session_id,
        key=key,
    ):
        raise AuthError(
            code="csrf_validation_failed",
            message="The request could not be validated.",
            status_code=403,
            event="csrf",
            reason="token_invalid",
        )


def _audit(
    request: Request,
    hasher: AuditHasher | None,
    recorder: AuditRecorder | None,
    event: str,
    reason: str,
) -> None:
    log_auth_event(
        event=event,
        outcome="accepted",
        reason=reason,
        request_id=getattr(request.state, "request_id", "unavailable"),
        route=request.url.path,
        status_code=200,
        audit_hasher=hasher,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    enqueue_audit(
        recorder,
        event_type=f"resource.{event}.{reason}",
        request_id=getattr(request.state, "request_id", "unavailable"),
        owner_id=getattr(request.state, "principal_user_id", None),
        fields={
            "resource": event,
            "operation": reason,
            "route": request.url.path,
            "status_code": "200",
        },
    )


def _credential_response(metadata) -> dict[str, object]:
    return {
        "id": metadata.id,
        "provider": metadata.provider,
        "kind": metadata.kind,
        "active": metadata.revoked_at is None,
        "created_at": metadata.created_at,
        "updated_at": metadata.updated_at,
        "revoked_at": metadata.revoked_at,
    }


def _credential_operation(operation):
    try:
        return operation()
    except CredentialNotFound as error:
        raise ResourceNotFound() from error
    except CredentialConflict as error:
        raise ResourceConflict("credential_conflict") from error
    except CredentialPayloadError as error:
        raise AuthError(
            code="invalid_request",
            message="The request could not be processed.",
            status_code=400,
            event="request",
            reason="invalid_input",
        ) from error
    except CredentialServiceError as error:
        raise ResourceUnavailable() from error
