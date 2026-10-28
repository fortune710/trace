"""Authenticated routes for opaque desktop project handles."""

from functools import lru_cache

from fastapi import APIRouter, Request

from auth.config import AuthSettings
from auth.csrf import validate_csrf_token
from auth.errors import AuthError
from auth.principal import CurrentPrincipal
from auth.tokens import decode_base64url_key
from db.session import get_engine
from local_projects.schemas import LocalProjectHandleCreate, LocalProjectHandleResponse
from local_projects.service import LocalProjectHandleService


def build_router(settings: AuthSettings) -> APIRouter:
    router = APIRouter()

    @lru_cache
    def service() -> LocalProjectHandleService:
        return LocalProjectHandleService(get_engine())

    @router.post("/local-project-handles", response_model=LocalProjectHandleResponse)
    def ensure_handle(
        request: Request,
        body: LocalProjectHandleCreate,
        principal: CurrentPrincipal,
    ) -> dict[str, object]:
        _require_csrf(request, principal, settings)
        return service().ensure(
            owner_id=principal.user_id,
            client_project_id=body.client_project_id,
        )

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
