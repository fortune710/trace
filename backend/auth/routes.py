"""Cookie-based email/password authentication endpoints."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from urllib.parse import urlparse

from fastapi import Cookie, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from auth.audit import AuditHasher, log_auth_event
from auth.config import AuthSettings
from auth.cookies import clear_auth_cookies, set_auth_cookies, set_csrf_cookie
from auth.csrf import issue_csrf_token, validate_csrf_token
from auth.errors import AuthError
from auth.rate_limit import (
    AUTH_RATE_LIMIT_POLICIES,
    enforce_rate_limit,
    rate_limiter_from_settings,
)
from auth.service import AuthenticationUnavailable, AuthService
from auth.tokens import decode_base64url_key
from db.session import get_engine


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(_RequestModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, max_length=120)
    return_to: str | None = Field(default=None, max_length=2048)


class LoginRequest(_RequestModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenRequest(_RequestModel):
    token: str = Field(min_length=1, max_length=512)


class PasswordRecoveryRequest(_RequestModel):
    email: str = Field(min_length=3, max_length=320)
    return_to: str | None = Field(default=None, max_length=2048)


class PasswordResetRequest(TokenRequest):
    password: str = Field(min_length=1, max_length=1024)


def install_auth_routes(
    app: FastAPI, settings: AuthSettings, audit_hasher: AuditHasher | None
) -> None:
    @lru_cache
    def service() -> AuthService:
        return AuthService.from_settings(engine=get_engine(), settings=settings)

    @lru_cache
    def limiter():
        return rate_limiter_from_settings(settings)

    async def rate_limit(request: Request, policy_name: str, subject: str) -> None:
        await enforce_rate_limit(
            limiter(), policy=AUTH_RATE_LIMIT_POLICIES[policy_name], subject=subject
        )

    def audit(
        request: Request,
        *,
        event: str,
        outcome: str,
        reason: str,
        status_code: int,
        identity: str | None = None,
    ) -> None:
        log_auth_event(
            event=event,
            outcome=outcome,
            reason=reason,
            request_id=getattr(request.state, "request_id", "unavailable"),
            route=request.url.path,
            status_code=status_code,
            audit_hasher=audit_hasher,
            identity=identity,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

    @app.post("/auth/register", status_code=202)
    async def register(request: Request, body: RegisterRequest) -> dict[str, str]:
        await rate_limit(request, "auth.registration.ip", _ip_subject(request))
        try:
            await asyncio.to_thread(
                service().register,
                email=body.email,
                password=body.password,
                display_name=body.display_name or None,
                destination=_destination(settings, body.return_to),
            )
        except (AuthenticationUnavailable, ValueError) as error:
            if isinstance(error, ValueError):
                raise _invalid_request() from error
            raise _unavailable() from error
        audit(
            request,
            event="registration",
            outcome="accepted",
            reason="verification_requested",
            status_code=202,
            identity=body.email,
        )
        return {
            "message": "If the account can be created, a verification email will be sent."
        }

    @app.post("/auth/verify-email")
    async def verify_email(request: Request, body: TokenRequest) -> dict[str, str]:
        try:
            verified = await asyncio.to_thread(service().verify_email, token=body.token)
        except AuthenticationUnavailable as error:
            raise _unavailable() from error
        if not verified:
            audit(
                request,
                event="email_verification",
                outcome="rejected",
                reason="one_time_token_invalid",
                status_code=400,
            )
            raise _invalid_token()
        audit(
            request,
            event="email_verification",
            outcome="accepted",
            reason="email_confirmed",
            status_code=200,
        )
        return {"message": "Email verified."}

    @app.post("/auth/login")
    async def login(
        request: Request, body: LoginRequest, response: Response
    ) -> dict[str, str]:
        await rate_limit(request, "auth.login.ip", _ip_subject(request))
        await rate_limit(request, "auth.login.identity", body.email.casefold())
        try:
            result = await asyncio.to_thread(
                service().login, email=body.email, password=body.password
            )
        except AuthenticationUnavailable as error:
            raise _unavailable() from error
        if result.tokens is None:
            audit(
                request,
                event="login",
                outcome="rejected",
                reason="invalid_credentials",
                status_code=401,
                identity=body.email,
            )
            raise _authentication_failed()
        _set_session(
            response,
            result.tokens.access_token,
            result.tokens.refresh_token,
            result.tokens.session_id,
            settings,
        )
        audit(
            request,
            event="login",
            outcome="accepted",
            reason="session_created",
            status_code=200,
            identity=body.email,
        )
        return {"message": "Authenticated."}

    @app.post("/auth/refresh")
    async def refresh(
        request: Request,
        response: Response,
        refresh_token: str | None = Cookie(
            default=None, alias=settings.refresh_cookie_name
        ),
        csrf_cookie: str | None = Cookie(default=None, alias=settings.csrf_cookie_name),
    ) -> dict[str, str]:
        session_id = await asyncio.to_thread(
            service().session_id_for_refresh, refresh_token
        )
        _require_csrf(request, csrf_cookie, session_id, settings)
        await rate_limit(request, "auth.refresh.session", str(session_id))
        try:
            result = await asyncio.to_thread(
                service().refresh, refresh_token=refresh_token or ""
            )
        except AuthenticationUnavailable as error:
            raise _unavailable() from error
        if result.tokens is None:
            audit(
                request,
                event="refresh",
                outcome="rejected",
                reason="refresh_invalid_or_reused",
                status_code=401,
            )
            raise _session_expired()
        _set_session(
            response,
            result.tokens.access_token,
            result.tokens.refresh_token,
            result.tokens.session_id,
            settings,
        )
        audit(
            request,
            event="refresh",
            outcome="accepted",
            reason="session_rotated",
            status_code=200,
        )
        return {"message": "Session refreshed."}

    @app.post("/auth/logout", status_code=204)
    async def logout(
        request: Request,
        response: Response,
        refresh_token: str | None = Cookie(
            default=None, alias=settings.refresh_cookie_name
        ),
        csrf_cookie: str | None = Cookie(default=None, alias=settings.csrf_cookie_name),
    ) -> Response:
        session_id = await asyncio.to_thread(
            service().session_id_for_refresh, refresh_token
        )
        if session_id is not None:
            _require_csrf(request, csrf_cookie, session_id, settings)
            try:
                await asyncio.to_thread(service().logout, refresh_token=refresh_token)
            except AuthenticationUnavailable as error:
                raise _unavailable() from error
        clear_auth_cookies(response, settings)
        audit(
            request,
            event="logout",
            outcome="accepted",
            reason="session_revoked",
            status_code=204,
        )
        return response

    @app.get("/auth/session")
    async def session(
        request: Request,
        access_token: str | None = Cookie(
            default=None, alias=settings.access_cookie_name
        ),
    ) -> dict[str, str]:
        try:
            claims = await asyncio.to_thread(service().access_claims, access_token)
        except AuthenticationUnavailable as error:
            raise _unavailable() from error
        if claims is None:
            raise AuthError(
                code="authentication_required",
                message="Authentication is required to access this resource.",
                status_code=401,
                event="access",
                reason="token_invalid",
                headers={"WWW-Authenticate": "Bearer"},
            )
        audit(
            request,
            event="access",
            outcome="accepted",
            reason="session_active",
            status_code=200,
        )
        return {"user_id": str(claims.user_id), "session_id": str(claims.session_id)}

    @app.post("/auth/password-recovery", status_code=202)
    async def password_recovery(
        request: Request, body: PasswordRecoveryRequest
    ) -> dict[str, str]:
        await rate_limit(request, "auth.password_recovery.ip", _ip_subject(request))
        await rate_limit(
            request, "auth.password_recovery.identity", body.email.casefold()
        )
        try:
            await asyncio.to_thread(
                service().recover_password,
                email=body.email,
                destination=_destination(settings, body.return_to),
            )
        except AuthenticationUnavailable as error:
            raise _unavailable() from error
        audit(
            request,
            event="password_recovery",
            outcome="accepted",
            reason="request_received",
            status_code=202,
            identity=body.email,
        )
        return {
            "message": "If an eligible account exists, recovery instructions will be sent."
        }

    @app.post("/auth/password-recovery/confirm")
    async def password_recovery_confirm(
        request: Request, body: PasswordResetRequest
    ) -> dict[str, str]:
        try:
            reset = await asyncio.to_thread(
                service().reset_password, token=body.token, password=body.password
            )
        except AuthenticationUnavailable as error:
            raise _unavailable() from error
        if not reset:
            audit(
                request,
                event="password_recovery",
                outcome="rejected",
                reason="one_time_token_invalid",
                status_code=400,
            )
            raise _invalid_token()
        audit(
            request,
            event="password_recovery",
            outcome="accepted",
            reason="password_reset",
            status_code=200,
        )
        return {"message": "Password reset. Please sign in again."}


def _set_session(
    response: Response,
    access_token: str,
    refresh_token: str,
    session_id,
    settings: AuthSettings,
) -> None:
    set_auth_cookies(
        response,
        access_token=access_token,
        refresh_token=refresh_token,
        settings=settings,
    )
    assert settings.csrf_hmac_key is not None
    csrf_key = decode_base64url_key(
        settings.csrf_hmac_key.get_secret_value(), name="AUTH_CSRF_HMAC_KEY"
    )
    set_csrf_cookie(
        response,
        csrf_token=issue_csrf_token(session_id=session_id, key=csrf_key),
        settings=settings,
    )


def _require_csrf(
    request: Request, csrf_cookie: str | None, session_id, settings: AuthSettings
) -> None:
    header = request.headers.get("X-CSRF-Token")
    if session_id is None or settings.csrf_hmac_key is None:
        raise _csrf_invalid()
    csrf_key = decode_base64url_key(
        settings.csrf_hmac_key.get_secret_value(), name="AUTH_CSRF_HMAC_KEY"
    )
    if not validate_csrf_token(
        cookie_token=csrf_cookie,
        header_token=header,
        session_id=session_id,
        key=csrf_key,
    ):
        raise _csrf_invalid()


def _destination(settings: AuthSettings, requested: str | None) -> str:
    destination = requested or settings.frontend_url
    parsed = urlparse(destination)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = set(settings.allowed_origins) or {settings.frontend_url.rstrip("/")}
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or origin not in allowed
    ):
        raise ValueError("Return URL is invalid")
    return origin


def _ip_subject(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _authentication_failed() -> AuthError:
    return AuthError(
        code="authentication_failed",
        message="Unable to complete authentication.",
        status_code=401,
        event="login",
        reason="invalid_credentials",
    )


def _session_expired() -> AuthError:
    return AuthError(
        code="session_expired",
        message="Your session has expired. Please sign in again.",
        status_code=401,
        event="refresh",
        reason="refresh_invalid_or_reused",
    )


def _invalid_token() -> AuthError:
    return AuthError(
        code="invalid_token",
        message="The token is invalid or has expired.",
        status_code=400,
        event="one_time_token",
        reason="one_time_token_invalid",
    )


def _invalid_request() -> AuthError:
    return AuthError(
        code="invalid_request",
        message="The request could not be processed.",
        status_code=400,
        event="request",
        reason="invalid_input",
    )


def _unavailable() -> AuthError:
    return AuthError(
        code="auth_temporarily_unavailable",
        message="Authentication is temporarily unavailable.",
        status_code=503,
        event="dependency",
        reason="dependency_unavailable",
    )


def _csrf_invalid() -> AuthError:
    return AuthError(
        code="csrf_validation_failed",
        message="The request could not be processed.",
        status_code=403,
        event="csrf",
        reason="csrf_invalid",
    )
