from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, Request

from auth.errors import AuthError
from auth.tokens import InvalidAccessToken, JWTService


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: UUID
    session_id: UUID


class SessionStatusReader(Protocol):
    async def is_active(self, *, user_id: UUID, session_id: UUID) -> bool: ...


@dataclass(frozen=True)
class PrincipalDependencyContext:
    """Runtime dependencies used by the FastAPI principal dependency."""

    access_cookie_name: str
    jwt_service_factory: Callable[[], JWTService]
    session_status_reader_factory: Callable[[], SessionStatusReader]


def install_principal_context(
    app,
    *,
    access_cookie_name: str,
    jwt_service_factory: Callable[[], JWTService],
    session_status_reader_factory: Callable[[], SessionStatusReader],
) -> None:
    """Install the application-owned dependencies used by get_current_principal."""

    app.state.principal_context = PrincipalDependencyContext(
        access_cookie_name=access_cookie_name,
        jwt_service_factory=jwt_service_factory,
        session_status_reader_factory=session_status_reader_factory,
    )


async def get_current_principal(request: Request) -> AuthenticatedPrincipal:
    """Resolve the authenticated browser session or raise the generic 401 error."""

    context = getattr(request.app.state, "principal_context", None)
    if not isinstance(context, PrincipalDependencyContext):
        raise TypeError("The principal dependency is not configured")
    return await authenticate_access_token(
        request.cookies.get(context.access_cookie_name),
        jwt_service=context.jwt_service_factory(),
        session_status_reader=context.session_status_reader_factory(),
    )


CurrentPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]


async def authenticate_access_token(
    token: str | None,
    *,
    jwt_service: JWTService,
    session_status_reader: SessionStatusReader,
) -> AuthenticatedPrincipal:
    if not token:
        raise _authentication_required()

    try:
        claims = jwt_service.verify(token)
    except InvalidAccessToken as error:
        raise _authentication_required() from error

    if not await session_status_reader.is_active(
        user_id=claims.user_id, session_id=claims.session_id
    ):
        raise _authentication_required()

    return AuthenticatedPrincipal(user_id=claims.user_id, session_id=claims.session_id)


def _authentication_required() -> AuthError:
    return AuthError(
        code="authentication_required",
        message="Authentication is required to access this resource.",
        status_code=401,
        event="access",
        reason="token_invalid",
        headers={"WWW-Authenticate": "Bearer"},
    )
