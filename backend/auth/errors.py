from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from audit.emit import enqueue_audit
from audit.outbox import AuditRecorder
from auth.audit import AuditHasher, log_auth_event


class AuthError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        event: str,
        reason: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.event = event
        self.reason = reason
        self.headers = dict(headers or {})
        super().__init__(code)


class RateLimitExceeded(AuthError):
    def __init__(self, retry_after_seconds: int, policy: str) -> None:
        super().__init__(
            code="rate_limited",
            message="Too many requests. Please try again later.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            event="rate_limit",
            reason="policy_exceeded",
            headers={"Retry-After": str(retry_after_seconds)},
        )
        self.policy = policy


class AuthorizationDenied(AuthError):
    """Generic authorization failure that does not disclose resource ownership."""

    def __init__(self) -> None:
        super().__init__(
            code="authorization_denied",
            message="You are not authorized to access this resource.",
            status_code=status.HTTP_403_FORBIDDEN,
            event="authorization",
            reason="owner_mismatch",
        )


class ResourceNotFound(AuthError):
    """Safe absence response for owner-scoped resources."""

    def __init__(self) -> None:
        super().__init__(
            code="resource_not_found",
            message="The requested resource was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            event="resource",
            reason="not_found",
        )


class ResourceConflict(AuthError):
    """Safe response for a valid request that conflicts with resource state."""

    def __init__(self, reason: str = "state_conflict") -> None:
        super().__init__(
            code="resource_conflict",
            message="The requested resource operation conflicts with its current state.",
            status_code=status.HTTP_409_CONFLICT,
            event="resource",
            reason=reason,
        )


class ResourceUnavailable(AuthError):
    """Safe response when a required downstream resource is unavailable."""

    def __init__(self) -> None:
        super().__init__(
            code="resource_unavailable",
            message="The resource operation is temporarily unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            event="resource",
            reason="dependency_unavailable",
        )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unavailable")


def _error_response(
    *,
    code: str,
    message: str,
    request_id: str,
    status_code: int,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers=headers,
    )


def install_auth_error_handlers(
    app: FastAPI,
    audit_hasher: AuditHasher | None = None,
    audit_recorder: AuditRecorder | None = None,
) -> None:
    @app.exception_handler(AuthError)
    async def auth_error_handler(request: Request, error: AuthError) -> JSONResponse:
        context = (
            {"policy": error.policy} if isinstance(error, RateLimitExceeded) else None
        )
        log_auth_event(
            event=error.event,
            outcome="rejected",
            reason=error.reason,
            request_id=_request_id(request),
            route=request.url.path,
            status_code=error.status_code,
            context=context,
            audit_hasher=audit_hasher,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        enqueue_audit(
            audit_recorder,
            event_type=f"{error.event}.rejected",
            request_id=_request_id(request),
            owner_id=getattr(request.state, "principal_user_id", None),
            fields={
                "outcome": "rejected",
                "reason": error.reason,
                "route": request.url.path,
                "status_code": str(error.status_code),
            },
        )
        return _error_response(
            code=error.code,
            message=error.message,
            request_id=_request_id(request),
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        log_auth_event(
            event="request",
            outcome="rejected",
            reason="invalid_input",
            request_id=_request_id(request),
            route=request.url.path,
            status_code=status.HTTP_400_BAD_REQUEST,
            audit_hasher=audit_hasher,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        enqueue_audit(
            audit_recorder,
            event_type="request.rejected",
            request_id=_request_id(request),
            owner_id=getattr(request.state, "principal_user_id", None),
            fields={
                "outcome": "rejected",
                "reason": "invalid_input",
                "route": request.url.path,
                "status_code": str(status.HTTP_400_BAD_REQUEST),
            },
        )
        return _error_response(
            code="invalid_request",
            message="The request could not be processed.",
            request_id=_request_id(request),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
