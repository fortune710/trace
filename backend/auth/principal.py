from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from auth.errors import AuthError
from auth.tokens import InvalidAccessToken, JWTService


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: UUID
    session_id: UUID


class SessionStatusReader(Protocol):
    async def is_active(self, *, user_id: UUID, session_id: UUID) -> bool: ...


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
