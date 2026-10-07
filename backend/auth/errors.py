from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
    app: FastAPI, audit_hasher: AuditHasher | None = None
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
        return _error_response(
            code="invalid_request",
            message="The request could not be processed.",
            request_id=_request_id(request),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
