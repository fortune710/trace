"""Remediation route group."""

from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from audit.outbox import AuditRecorder
from auth.config import AuthSettings
from auth.credential_service import CredentialService
from auth.credentials import credential_cipher_from_settings
from auth.csrf import validate_csrf_token
from auth.errors import AuthError
from auth.principal import CurrentPrincipal
from auth.tokens import decode_base64url_key
from db.session import get_engine
from external_repositories.service import RepositoryService
from issue_tracking.routes import build_remediation_issue_router
from remediations.patch_store import PatchStore
from remediations.service import (
    LocalRemediationApplyService,
    RemediationPullRequestService,
)
from resources.router import select_routes
from resources.schemas import LocalRemediationApply, RemediationResponse

router = APIRouter()


def build_router(
    resource_router: APIRouter,
    settings: AuthSettings,
    audit_recorder: AuditRecorder | None = None,
) -> APIRouter:
    router = select_routes(
        resource_router,
        (),
        exact=(
            "/findings/{finding_id}/remediations",
            "/remediations/{remediation_id}",
            "/remediations/{remediation_id}/prompt",
            "/remediations/{remediation_id}/patch",
            "/remediations/{remediation_id}/reject",
        ),
    )
    router.include_router(build_remediation_issue_router(settings, audit_recorder))

    @lru_cache
    def pull_request_service() -> RemediationPullRequestService:
        repository_service = RepositoryService(
            engine=get_engine(),
            credential_service=CredentialService(
                engine=get_engine(), cipher=credential_cipher_from_settings(settings)
            ),
            settings=settings,
        )
        return RemediationPullRequestService(
            get_engine(),
            repository_service,
            audit_recorder,
            patch_store=PatchStore(
                get_engine(), credential_cipher_from_settings(settings)
            ),
        )

    @lru_cache
    def local_apply_service() -> LocalRemediationApplyService:
        return LocalRemediationApplyService(
            get_engine(),
            audit_recorder,
            patch_store=PatchStore(
                get_engine(), credential_cipher_from_settings(settings)
            ),
        )

    @router.post(
        "/remediations/{remediation_id}/apply-local",
        response_model=RemediationResponse,
    )
    def complete_local_apply(
        request: Request,
        remediation_id: UUID,
        body: LocalRemediationApply,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        return local_apply_service().complete(
            owner_id=principal.user_id,
            remediation_id=remediation_id,
            **body.model_dump(),
            request_id=request.headers.get("X-Request-ID", "unknown"),
        )

    @router.post(
        "/remediations/{remediation_id}/pull-request",
        response_model=RemediationResponse,
    )
    async def create_pull_request(
        request: Request,
        response: Response,
        remediation_id: UUID,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        if await request.body():
            raise HTTPException(
                status_code=422, detail="This endpoint does not accept a body."
            )
        _require_csrf(request, principal, settings)
        remediation, queued = pull_request_service().create(
            owner_id=principal.user_id,
            remediation_id=remediation_id,
            request_id=request.headers.get("X-Request-ID", "unknown"),
        )
        if queued:
            response.status_code = status.HTTP_202_ACCEPTED
        return remediation

    return router


def _require_csrf(
    request: Request, principal: CurrentPrincipal, settings: AuthSettings
) -> None:
    if settings.csrf_hmac_key is None:
        raise AuthError(
            code="csrf_validation_failed",
            message="The request could not be validated.",
            status_code=403,
            event="csrf",
            reason="configuration_missing",
        )
    if not validate_csrf_token(
        cookie_token=request.cookies.get(settings.csrf_cookie_name),
        header_token=request.headers.get("X-CSRF-Token"),
        session_id=principal.session_id,
        key=decode_base64url_key(
            settings.csrf_hmac_key.get_secret_value(), name="AUTH_CSRF_HMAC_KEY"
        ),
    ):
        raise AuthError(
            code="csrf_validation_failed",
            message="The request could not be validated.",
            status_code=403,
            event="csrf",
            reason="token_invalid",
        )
