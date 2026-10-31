"""OAuth authorization-code/PKCE routes with Redis-backed single-use state."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import UUID

import jwt
import sqlalchemy as sa
from fastapi import FastAPI, Response
from fastapi import Request as FastAPIRequest
from fastapi.responses import RedirectResponse
from jwt import PyJWKClient
from pydantic import BaseModel
from redis.exceptions import RedisError

from audit.emit import enqueue_audit
from audit.outbox import AuditRecorder
from auth.audit import AuditHasher, log_auth_event
from auth.config import AuthSettings
from auth.cookies import set_auth_cookies, set_csrf_cookie
from auth.credential_service import (
    CredentialNotFound,
    CredentialService,
    CredentialServiceError,
)
from auth.credentials import credential_cipher_from_settings
from auth.csrf import issue_csrf_token, validate_csrf_token
from auth.errors import AuthError
from auth.models import IdentityProvider
from auth.principal import AuthenticatedPrincipal, CurrentPrincipal
from auth.rate_limit import (
    AUTH_RATE_LIMIT_POLICIES,
    enforce_rate_limit,
    rate_limiter_from_settings,
)
from auth.service import AuthenticationUnavailable, AuthService, SessionTokens
from auth.tokens import (
    decode_base64url_key,
    generate_opaque_token,
)
from credentials.models import CredentialKind, CredentialProvider
from db.rls import principal_transaction
from db.session import get_engine, get_redis_client
from db.types import RepositoryProvider, RepositorySource
from external_repositories.models import ExternalRepository
from external_repositories.service import (
    invalidate_repository_catalog,
    provision_external_repository,
)
from notifications.models import NotificationEventType
from notifications.service import create_notification

_STATE_TTL_SECONDS = 600
OAUTH_CALLBACK_ROUTE = "/auth/oauth/{provider}/callback"
GITHUB_CONNECT_START_ROUTE = "/auth/oauth/github/connect/start"
LINEAR_CONNECT_START_ROUTE = "/auth/oauth/linear/connect/start"


class OAuthUnavailable(RuntimeError):
    pass


class OAuthRejected(ValueError):
    pass


def _notify_github_connected(owner_id: UUID, credential_id: UUID) -> None:
    """Persist the best-effort notification after a GitHub connection succeeds."""

    with principal_transaction(get_engine(), owner_id) as connection:
        create_notification(
            connection,
            owner_id=owner_id,
            event_type=NotificationEventType.GITHUB_CONNECTED,
            dedupe_key=f"github:connection:{credential_id}",
        )


class OAuthPurpose(StrEnum):
    LOGIN = "login"
    REPOSITORY_CONNECTION = "repository_connection"
    ISSUE_TRACKING_CONNECTION = "issue_tracking_connection"


class GitHubConnectionStatus(StrEnum):
    CONNECTED = "connected"
    NEVER_CONNECTED = "never_connected"
    NEEDS_RECONNECTION = "needs_reconnection"


class GitHubConnectionStatusResponse(BaseModel):
    provider: Literal["github"] = "github"
    status: GitHubConnectionStatus


class DesktopOAuthExchangeRequest(BaseModel):
    code: str
    verifier: str


@dataclass(frozen=True)
class OAuthTransaction:
    provider: str
    verifier: str
    nonce: str | None
    destination: str
    user_agent_hash: str
    purpose: OAuthPurpose = OAuthPurpose.LOGIN
    user_id: str | None = None
    session_id: str | None = None
    desktop: bool = False


@dataclass(frozen=True)
class ProviderIdentity:
    subject: str
    email: str
    display_name: str | None = None
    credential_payload: dict[str, object] | None = None


class OAuthStateStore:
    def __init__(self, *, redis_client, state_key: bytes) -> None:
        self._redis = redis_client
        self._state_key = state_key

    async def create(
        self,
        *,
        provider: str,
        destination: str,
        user_agent: str | None,
        purpose: OAuthPurpose = OAuthPurpose.LOGIN,
        user_id: UUID | None = None,
        session_id: UUID | None = None,
        verifier: str | None = None,
        desktop: bool = False,
    ) -> tuple[str, str, str | None]:
        if purpose != OAuthPurpose.LOGIN and (user_id is None or session_id is None):
            raise ValueError("OAuth connection owner and session are required")
        if purpose == OAuthPurpose.LOGIN and (
            user_id is not None or session_id is not None
        ):
            raise ValueError("OAuth login cannot carry a connection owner")
        if desktop and purpose != OAuthPurpose.LOGIN:
            raise ValueError("Desktop OAuth is only supported for login")
        state = generate_opaque_token()
        effective_verifier = verifier or generate_opaque_token()
        nonce = (
            generate_opaque_token()
            if provider == IdentityProvider.GOOGLE.value
            else None
        )
        transaction = OAuthTransaction(
            provider=provider,
            verifier=effective_verifier,
            nonce=nonce,
            destination=destination,
            user_agent_hash=self._digest(user_agent or ""),
            purpose=purpose,
            user_id=str(user_id) if user_id is not None else None,
            session_id=str(session_id) if session_id is not None else None,
            desktop=desktop,
        )
        try:
            created = await self._redis.set(
                self._key(state),
                json.dumps(asdict(transaction), separators=(",", ":")),
                ex=_STATE_TTL_SECONDS,
                nx=True,
            )
        except RedisError as error:
            raise OAuthUnavailable("OAuth state storage is unavailable") from error
        if not created:
            raise OAuthUnavailable("OAuth state storage is unavailable")
        return state, effective_verifier, nonce

    async def consume(self, state: str) -> OAuthTransaction:
        if not state or len(state) > 512:
            raise OAuthRejected("OAuth state is invalid")
        try:
            raw = await self._redis.getdel(self._key(state))
        except RedisError as error:
            raise OAuthUnavailable("OAuth state storage is unavailable") from error
        if not raw:
            raise OAuthRejected("OAuth state is invalid")
        try:
            decoded = json.loads(raw)
            transaction = OAuthTransaction(
                provider=decoded["provider"],
                verifier=decoded["verifier"],
                nonce=decoded.get("nonce"),
                destination=decoded["destination"],
                user_agent_hash=decoded["user_agent_hash"],
                purpose=OAuthPurpose(decoded.get("purpose", OAuthPurpose.LOGIN)),
                user_id=decoded.get("user_id"),
                session_id=decoded.get("session_id"),
                desktop=bool(decoded.get("desktop", False)),
            )
            if (
                transaction.provider
                not in {
                    IdentityProvider.GITHUB.value,
                    IdentityProvider.GOOGLE.value,
                    CredentialProvider.LINEAR.value,
                }
                or not transaction.verifier
                or not transaction.destination
                or (
                    transaction.purpose == OAuthPurpose.REPOSITORY_CONNECTION
                    and (
                        transaction.provider != IdentityProvider.GITHUB.value
                        or not transaction.user_id
                        or not transaction.session_id
                    )
                )
                or (
                    transaction.purpose == OAuthPurpose.ISSUE_TRACKING_CONNECTION
                    and (
                        transaction.provider != CredentialProvider.LINEAR.value
                        or not transaction.user_id
                        or not transaction.session_id
                    )
                )
                or (
                    transaction.purpose == OAuthPurpose.LOGIN
                    and (
                        transaction.user_id is not None
                        or transaction.session_id is not None
                    )
                )
                or (
                    transaction.purpose == OAuthPurpose.LOGIN
                    and transaction.provider == CredentialProvider.LINEAR.value
                )
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise OAuthRejected("OAuth state is invalid") from error
        return transaction

    def _key(self, state: str) -> str:
        return f"trace:oauth:v1:{self._digest(state)}"

    def _digest(self, value: str) -> str:
        return hmac.new(
            self._state_key, value.encode("utf-8"), hashlib.sha256
        ).hexdigest()


def install_oauth_routes(
    app: FastAPI,
    settings: AuthSettings,
    audit_hasher: AuditHasher | None,
    audit_recorder: AuditRecorder | None = None,
) -> None:
    service: AuthService | None = None
    credentials: CredentialService | None = None
    limiter = None
    store = None

    def auth_service() -> AuthService:
        nonlocal service
        if service is None:
            service = AuthService.from_settings(engine=get_engine(), settings=settings)
        return service

    def rate_limiter():
        nonlocal limiter
        if limiter is None:
            limiter = rate_limiter_from_settings(settings)
        return limiter

    def credential_service() -> CredentialService:
        nonlocal credentials
        if credentials is None:
            credentials = CredentialService(
                engine=get_engine(), cipher=credential_cipher_from_settings(settings)
            )
        return credentials

    def state_store() -> OAuthStateStore:
        nonlocal store
        if store is None:
            assert settings.token_hash_key is not None
            store = OAuthStateStore(
                redis_client=get_redis_client(),
                state_key=decode_base64url_key(
                    settings.token_hash_key.get_secret_value(),
                    name="AUTH_TOKEN_HASH_KEY",
                ),
            )
        return store

    async def create_desktop_ticket(code: str, transaction: OAuthTransaction) -> str:
        ticket = generate_opaque_token()
        try:
            created = await get_redis_client().set(
                f"trace:oauth:desktop:{ticket}",
                json.dumps(
                    {"code": code, "transaction": asdict(transaction)},
                    separators=(",", ":"),
                ),
                ex=120,
                nx=True,
            )
        except RedisError as error:
            raise OAuthUnavailable("OAuth state storage is unavailable") from error
        if not created:
            raise OAuthUnavailable("OAuth state storage is unavailable")
        return ticket

    async def consume_desktop_ticket(ticket: str) -> tuple[str, OAuthTransaction]:
        try:
            raw = await get_redis_client().getdel(f"trace:oauth:desktop:{ticket}")
        except RedisError as error:
            raise OAuthUnavailable("OAuth state storage is unavailable") from error
        if not raw:
            raise OAuthRejected("OAuth code is invalid")
        try:
            payload = json.loads(raw)
            transaction = OAuthTransaction(**payload["transaction"])
            if not transaction.desktop or transaction.purpose != OAuthPurpose.LOGIN:
                raise ValueError
            return payload["code"], transaction
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise OAuthRejected("OAuth code is invalid") from error

    def audit(
        request: FastAPIRequest,
        *,
        event: str,
        outcome: str,
        reason: str,
        status_code: int,
        provider: str,
    ) -> None:
        log_auth_event(
            event=event,
            outcome=outcome,
            reason=reason,
            request_id=getattr(request.state, "request_id", "unavailable"),
            route=request.url.path,
            status_code=status_code,
            context={"provider": provider},
            audit_hasher=audit_hasher,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        enqueue_audit(
            audit_recorder,
            event_type=f"oauth.{event}",
            request_id=getattr(request.state, "request_id", "unavailable"),
            owner_id=getattr(request.state, "principal_user_id", None),
            fields={
                "outcome": outcome,
                "reason": reason,
                "provider": provider,
                "route": request.url.path,
                "status_code": str(status_code),
            },
        )

    @app.get("/auth/oauth/{provider}/desktop/start")
    async def desktop_oauth_start(
        request: FastAPIRequest, provider: str, challenge: str
    ):
        if (
            len(challenge) < 43
            or len(challenge) > 128
            or any(
                c
                not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
                for c in challenge
            )
        ):
            raise _invalid_request()
        configuration = _provider_configuration(settings, provider)
        try:
            await enforce_rate_limit(
                rate_limiter(),
                policy=AUTH_RATE_LIMIT_POLICIES["auth.oauth_start.ip"],
                subject=request.client.host if request.client else "unknown",
            )
            state, _, nonce = await state_store().create(
                provider=provider,
                destination="trace://oauth/callback",
                user_agent=request.headers.get("user-agent"),
                verifier=challenge,
                desktop=True,
            )
        except OAuthUnavailable as error:
            raise _unavailable() from error
        except ValueError as error:
            raise _invalid_request() from error
        parameters = {
            "client_id": configuration.client_id,
            "redirect_uri": configuration.redirect_uri,
            "response_type": "code",
            "scope": configuration.scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if nonce:
            parameters["nonce"] = nonce
        return RedirectResponse(
            f"{configuration.authorize_url}?{urlencode(parameters)}", status_code=302
        )

    @app.post("/auth/oauth/desktop/exchange")
    async def desktop_oauth_exchange(
        request: FastAPIRequest, body: DesktopOAuthExchangeRequest, response: Response
    ):
        try:
            code, transaction = await consume_desktop_ticket(body.code)
            if _pkce_challenge(body.verifier) != transaction.verifier:
                raise OAuthRejected("OAuth verifier is invalid")
            transaction = OAuthTransaction(
                **{**asdict(transaction), "verifier": body.verifier}
            )
            identity = await asyncio.to_thread(
                _provider_identity,
                _provider_configuration(settings, transaction.provider),
                code,
                transaction,
            )
            result = await asyncio.to_thread(
                auth_service().oauth_login,
                provider=IdentityProvider(transaction.provider),
                subject=identity.subject,
                email=identity.email,
                display_name=identity.display_name,
            )
            if result.tokens is None:
                raise OAuthRejected("OAuth account is not eligible")
            csrf_token = _set_session(
                response,
                result.tokens.access_token,
                result.tokens.refresh_token,
                result.tokens.session_id,
                settings,
            )
            return {"message": "Authenticated.", "csrf_token": csrf_token}
        except (OAuthRejected, ValueError, AuthError) as error:
            raise _authentication_failed() from error
        except (OAuthUnavailable, AuthenticationUnavailable) as error:
            raise _unavailable() from error

    @app.get("/auth/oauth/{provider}/start")
    async def oauth_start(
        request: FastAPIRequest, provider: str, return_to: str | None = None
    ):
        provider_config = _provider_configuration(
            settings, provider, purpose=OAuthPurpose.LOGIN
        )
        try:
            await enforce_rate_limit(
                rate_limiter(),
                policy=AUTH_RATE_LIMIT_POLICIES["auth.oauth_start.ip"],
                subject=request.client.host if request.client else "unknown",
            )
            destination = _destination(settings, return_to)
            state, verifier, nonce = await state_store().create(
                provider=provider,
                destination=destination,
                user_agent=request.headers.get("user-agent"),
            )
        except OAuthUnavailable as error:
            raise _unavailable() from error
        except ValueError as error:
            raise _invalid_request() from error
        challenge = _pkce_challenge(verifier)
        parameters = {
            "client_id": provider_config.client_id,
            "redirect_uri": provider_config.redirect_uri,
            "response_type": "code",
            "scope": provider_config.scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if nonce:
            parameters["nonce"] = nonce
        audit(
            request,
            event="oauth",
            outcome="accepted",
            reason="authorization_started",
            status_code=302,
            provider=provider,
        )
        return RedirectResponse(
            f"{provider_config.authorize_url}?{urlencode(parameters)}", status_code=302
        )

    @app.post(GITHUB_CONNECT_START_ROUTE)
    async def github_connect_start(
        request: FastAPIRequest,
        principal: CurrentPrincipal,
        return_to: str | None = None,
    ):
        _require_connection_csrf(request, principal, settings)
        provider = IdentityProvider.GITHUB.value
        provider_config = _provider_configuration(
            settings, provider, purpose=OAuthPurpose.REPOSITORY_CONNECTION
        )
        try:
            await enforce_rate_limit(
                rate_limiter(),
                policy=AUTH_RATE_LIMIT_POLICIES["auth.oauth_start.ip"],
                subject=request.client.host if request.client else "unknown",
            )
            destination = _destination(settings, return_to)
            state, verifier, _nonce = await state_store().create(
                provider=provider,
                destination=destination,
                user_agent=request.headers.get("user-agent"),
                purpose=OAuthPurpose.REPOSITORY_CONNECTION,
                user_id=principal.user_id,
                session_id=principal.session_id,
            )
        except OAuthUnavailable as error:
            raise _unavailable() from error
        except ValueError as error:
            raise _invalid_request() from error
        parameters = {
            "client_id": provider_config.client_id,
            "redirect_uri": provider_config.redirect_uri,
            "response_type": "code",
            "scope": provider_config.scope,
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        audit(
            request,
            event="oauth",
            outcome="accepted",
            reason="repository_authorization_started",
            status_code=302,
            provider=provider,
        )
        return {
            "authorization_url": f"{provider_config.authorize_url}?{urlencode(parameters)}"
        }

    @app.post(LINEAR_CONNECT_START_ROUTE)
    async def linear_connect_start(
        request: FastAPIRequest,
        principal: CurrentPrincipal,
        return_to: str | None = None,
    ):
        _require_connection_csrf(request, principal, settings)
        provider = CredentialProvider.LINEAR.value
        provider_config = _provider_configuration(
            settings,
            provider,
            purpose=OAuthPurpose.ISSUE_TRACKING_CONNECTION,
        )
        try:
            await enforce_rate_limit(
                rate_limiter(),
                policy=AUTH_RATE_LIMIT_POLICIES["auth.oauth_start.ip"],
                subject=request.client.host if request.client else "unknown",
            )
            destination = _destination(settings, return_to)
            state, verifier, _nonce = await state_store().create(
                provider=provider,
                destination=destination,
                user_agent=request.headers.get("user-agent"),
                purpose=OAuthPurpose.ISSUE_TRACKING_CONNECTION,
                user_id=principal.user_id,
                session_id=principal.session_id,
            )
        except OAuthUnavailable as error:
            raise _unavailable() from error
        except ValueError as error:
            raise _invalid_request() from error
        parameters = {
            "client_id": provider_config.client_id,
            "redirect_uri": provider_config.redirect_uri,
            "response_type": "code",
            "scope": provider_config.scope,
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        audit(
            request,
            event="oauth",
            outcome="accepted",
            reason="issue_tracking_authorization_started",
            status_code=302,
            provider=provider,
        )
        return {
            "authorization_url": f"{provider_config.authorize_url}?{urlencode(parameters)}"
        }

    @app.get(
        "/auth/oauth/github/connection",
        response_model=GitHubConnectionStatusResponse,
    )
    async def github_connection_status(
        request: FastAPIRequest, principal: CurrentPrincipal
    ) -> GitHubConnectionStatusResponse:
        try:
            connection_status = await asyncio.to_thread(
                get_github_connection_status,
                engine=get_engine(),
                service=credential_service(),
                settings=settings,
                owner_id=principal.user_id,
            )
        except OAuthUnavailable as error:
            raise _unavailable() from error
        audit(
            request,
            event="oauth",
            outcome="accepted",
            reason="repository_connection_status_read",
            status_code=200,
            provider=IdentityProvider.GITHUB.value,
        )
        return GitHubConnectionStatusResponse(status=connection_status)

    @app.get(OAUTH_CALLBACK_ROUTE)
    async def oauth_callback(
        request: FastAPIRequest,
        provider: str,
        state: str | None = None,
        code: str | None = None,
        error: str | None = None,
    ):
        request_id = getattr(request.state, "request_id", "unavailable")
        fallback_destination = settings.frontend_url.rstrip("/")
        transaction: OAuthTransaction | None = None
        if error or not state or not code:
            if state:
                try:
                    transaction = await state_store().consume(state)
                    if transaction.provider != provider:
                        transaction = None
                except (OAuthRejected, OAuthUnavailable, ValueError):
                    transaction = None
            audit(
                request,
                event="oauth",
                outcome="rejected",
                reason="callback_malformed",
                status_code=400,
                provider=provider,
            )
            return _oauth_failure_redirect(
                transaction.destination if transaction else fallback_destination,
                request_id,
                purpose=transaction.purpose if transaction else OAuthPurpose.LOGIN,
            )
        session_tokens: SessionTokens | None = None
        try:
            transaction = await state_store().consume(state)
            if transaction.provider != provider:
                raise OAuthRejected("OAuth state is invalid")
            configuration = _provider_configuration(
                settings, provider, purpose=transaction.purpose
            )
            if transaction.desktop:
                ticket = await create_desktop_ticket(code, transaction)
                return RedirectResponse(
                    f"trace://oauth/callback?{urlencode({'code': ticket})}",
                    status_code=303,
                )
            identity = await asyncio.to_thread(
                _provider_identity, configuration, code, transaction
            )
            if transaction.purpose != OAuthPurpose.LOGIN:
                if (
                    not transaction.user_id
                    or not transaction.session_id
                    or identity.credential_payload is None
                    or not await asyncio.to_thread(
                        auth_service().is_session_active,
                        user_id=UUID(transaction.user_id),
                        session_id=UUID(transaction.session_id),
                    )
                ):
                    raise OAuthRejected("OAuth connection is invalid")
                credential_metadata = await asyncio.to_thread(
                    credential_service().create_or_replace,
                    owner_id=UUID(transaction.user_id),
                    provider=(
                        CredentialProvider.GITHUB
                        if transaction.purpose == OAuthPurpose.REPOSITORY_CONNECTION
                        else CredentialProvider.LINEAR
                    ),
                    kind=CredentialKind.OAUTH,
                    payload=identity.credential_payload,
                )
                if transaction.purpose == OAuthPurpose.REPOSITORY_CONNECTION:
                    await asyncio.to_thread(
                        provision_external_repository,
                        engine=get_engine(),
                        owner_id=UUID(transaction.user_id),
                        credential_id=credential_metadata.id,
                        external_user_id=identity.subject,
                    )
                    await invalidate_repository_catalog(
                        redis_client=get_redis_client(),
                        owner_id=UUID(transaction.user_id),
                        source=RepositoryProvider.GITHUB,
                    )
                    try:
                        await asyncio.to_thread(
                            _notify_github_connected,
                            UUID(transaction.user_id),
                            credential_metadata.id,
                        )
                    except sa.exc.SQLAlchemyError:
                        # The GitHub connection is already usable; this alert is best-effort.
                        pass
            else:
                result = await asyncio.to_thread(
                    auth_service().oauth_login,
                    provider=IdentityProvider(provider),
                    subject=identity.subject,
                    email=identity.email,
                    display_name=identity.display_name,
                )
                if result.tokens is None:
                    raise OAuthRejected("OAuth account is not eligible")
                session_tokens = result.tokens
        except (OAuthRejected, ValueError, AuthError):
            audit(
                request,
                event="oauth",
                outcome="rejected",
                reason="callback_rejected",
                status_code=401,
                provider=provider,
            )
            return _oauth_failure_redirect(
                transaction.destination if transaction else fallback_destination,
                request_id,
                purpose=transaction.purpose if transaction else OAuthPurpose.LOGIN,
            )
        except (
            OAuthUnavailable,
            AuthenticationUnavailable,
            CredentialServiceError,
        ):
            audit(
                request,
                event="oauth",
                outcome="rejected",
                reason="dependency_unavailable",
                status_code=503,
                provider=provider,
            )
            return _oauth_failure_redirect(
                transaction.destination if transaction else fallback_destination,
                request_id,
                purpose=transaction.purpose if transaction else OAuthPurpose.LOGIN,
            )

        if transaction.purpose != OAuthPurpose.LOGIN:
            response = _connection_redirect(
                transaction.destination,
                outcome="connected",
                request_id=request_id,
                provider=provider,
            )
            audit(
                request,
                event="oauth",
                outcome="accepted",
                reason="provider_connected",
                status_code=303,
                provider=provider,
            )
            return response

        response = RedirectResponse(
            f"{transaction.destination.rstrip('/')}/auth/callback", status_code=303
        )
        assert session_tokens is not None
        _set_session(
            response,
            session_tokens.access_token,
            session_tokens.refresh_token,
            session_tokens.session_id,
            settings,
        )
        audit(
            request,
            event="oauth",
            outcome="accepted",
            reason="session_created",
            status_code=303,
            provider=provider,
        )
        return response


@dataclass(frozen=True)
class ProviderConfiguration:
    provider: str
    client_id: str
    client_secret: str
    redirect_uri: str
    authorize_url: str
    token_url: str
    scope: str
    github_user_url: str | None = None
    github_emails_url: str | None = None
    google_jwks_url: str | None = None
    linear_api_url: str | None = None


def _provider_configuration(
    settings: AuthSettings,
    provider: str,
    *,
    purpose: OAuthPurpose = OAuthPurpose.LOGIN,
) -> ProviderConfiguration:
    if provider == IdentityProvider.GITHUB.value:
        client_id, secret, redirect_uri = (
            settings.github_client_id,
            settings.github_client_secret,
            settings.github_redirect_uri,
        )
        config = ProviderConfiguration(
            provider,
            client_id or "",
            secret.get_secret_value() if secret else "",
            redirect_uri or "",
            settings.github_authorize_url,
            settings.github_token_url,
            "read:user user:email"
            if purpose == OAuthPurpose.LOGIN
            else "read:user user:email repo",
            github_user_url=settings.github_user_url,
            github_emails_url=settings.github_emails_url,
        )
    elif provider == IdentityProvider.GOOGLE.value:
        client_id, secret, redirect_uri = (
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_redirect_uri,
        )
        config = ProviderConfiguration(
            provider,
            client_id or "",
            secret.get_secret_value() if secret else "",
            redirect_uri or "",
            settings.google_authorize_url,
            settings.google_token_url,
            "openid email profile",
            google_jwks_url=settings.google_jwks_url,
        )
    elif provider == CredentialProvider.LINEAR.value:
        if purpose != OAuthPurpose.ISSUE_TRACKING_CONNECTION:
            raise _invalid_request()
        client_id, secret, redirect_uri = (
            settings.linear_client_id,
            settings.linear_client_secret,
            settings.linear_redirect_uri,
        )
        config = ProviderConfiguration(
            provider,
            client_id or "",
            secret.get_secret_value() if secret else "",
            redirect_uri or "",
            settings.linear_authorize_url,
            settings.linear_token_url,
            "read,issues:create",
            linear_api_url=settings.linear_api_url,
        )
    else:
        raise _invalid_request()
    parsed = urlparse(config.redirect_uri)
    if (
        not config.client_id
        or not config.client_secret
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path != oauth_callback_path(provider)
    ):
        raise _unavailable()
    return config


def oauth_callback_path(provider: str) -> str:
    return OAUTH_CALLBACK_ROUTE.format(provider=provider)


def _provider_identity(
    config: ProviderConfiguration, code: str, transaction: OAuthTransaction
) -> ProviderIdentity:
    if len(code) > 2048:
        raise OAuthRejected("OAuth callback is invalid")
    token = _post_form(
        config.token_url,
        {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "redirect_uri": config.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": transaction.verifier,
        },
    )
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthRejected("OAuth exchange failed")
    if config.provider == IdentityProvider.GITHUB.value:
        assert config.github_user_url is not None
        assert config.github_emails_url is not None
        user = _get_json(config.github_user_url, access_token)
        emails = _get_json(config.github_emails_url, access_token)
        if not isinstance(user, dict) or not isinstance(emails, list):
            raise OAuthRejected("GitHub identity is invalid")
        subject = user.get("id")
        if not isinstance(subject, int):
            raise OAuthRejected("GitHub identity is invalid")
        email = next(
            (
                item.get("email")
                for item in emails
                if isinstance(item, dict)
                and item.get("primary") is True
                and item.get("verified") is True
                and isinstance(item.get("email"), str)
            ),
            None,
        )
        if not isinstance(email, str):
            raise OAuthRejected("GitHub email is unavailable")
        return ProviderIdentity(
            subject=str(subject),
            email=email,
            credential_payload=_github_credential_payload(token)
            if transaction.purpose == OAuthPurpose.REPOSITORY_CONNECTION
            else None,
        )
    if config.provider == CredentialProvider.LINEAR.value:
        assert config.linear_api_url is not None
        viewer = _linear_viewer(config.linear_api_url, access_token)
        subject = viewer.get("id") if isinstance(viewer, dict) else None
        if not isinstance(subject, str) or not subject:
            raise OAuthRejected("Linear identity is invalid")
        return ProviderIdentity(
            subject=subject,
            email="linear-connection",
            credential_payload=_oauth_credential_payload(token),
        )
    id_token = token.get("id_token")
    if not isinstance(id_token, str) or not transaction.nonce:
        raise OAuthRejected("Google identity is invalid")
    try:
        assert config.google_jwks_url is not None
        signing_key = PyJWKClient(
            config.google_jwks_url, cache_keys=True
        ).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config.client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={"require": ["aud", "exp", "iat", "iss", "sub", "nonce"]},
        )
    except jwt.PyJWTError as error:
        raise OAuthRejected("Google identity is invalid") from error
    if (
        claims.get("nonce") != transaction.nonce
        or claims.get("email_verified") is not True
    ):
        raise OAuthRejected("Google identity is invalid")
    subject, email = claims.get("sub"), claims.get("email")
    if not isinstance(subject, str) or not subject or not isinstance(email, str):
        raise OAuthRejected("Google identity is invalid")
    display_name = claims.get("name")
    if display_name is not None and (
        not isinstance(display_name, str) or len(display_name) > 120
    ):
        raise OAuthRejected("Google identity is invalid")
    return ProviderIdentity(
        subject=subject,
        email=email,
        display_name=(display_name.strip() or None)
        if isinstance(display_name, str)
        else None,
    )


def _github_credential_payload(token: dict[str, object]) -> dict[str, object]:
    return _oauth_credential_payload(token)


def _oauth_credential_payload(token: dict[str, object]) -> dict[str, object]:
    access_token = token.get("access_token")
    if (
        not isinstance(access_token, str)
        or not access_token
        or len(access_token) > 8192
    ):
        raise OAuthRejected("OAuth exchange failed")

    payload: dict[str, object] = {"access_token": access_token}
    for field in ("refresh_token", "token_type", "scope"):
        value = token.get(field)
        if isinstance(value, str) and value and len(value) <= 8192:
            payload[field] = value
    for field in ("expires_in", "refresh_token_expires_in"):
        value = token.get(field)
        if isinstance(value, int) and 0 < value <= 31_536_000:
            payload[field] = value
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, int):
        payload["access_token_expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=expires_in)
        ).isoformat()
    refresh_expires_in = payload.get("refresh_token_expires_in")
    if isinstance(refresh_expires_in, int):
        payload["refresh_token_expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=refresh_expires_in)
        ).isoformat()
    return payload


def _linear_viewer(api_url: str, access_token: str) -> dict | list:
    request = Request(
        api_url,
        data=b'{"query":"query { viewer { id } }"}',
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    result = _read_json(request)
    if not isinstance(result, dict):
        raise OAuthRejected("Linear identity is invalid")
    data = result.get("data")
    if not isinstance(data, dict):
        raise OAuthRejected("Linear identity is invalid")
    viewer = data.get("viewer")
    if not isinstance(viewer, dict):
        raise OAuthRejected("Linear identity is invalid")
    return viewer


def refresh_github_credential(
    *,
    service: CredentialService,
    settings: AuthSettings,
    owner_id: UUID,
    credential_id: UUID,
) -> dict[str, object]:
    """Refresh and atomically replace one owner's GitHub OAuth payload."""
    payload = service.decrypt_for_provider_call(
        owner_id=owner_id, credential_id=credential_id
    )
    refresh_token = payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise OAuthRejected("GitHub credential cannot be refreshed")
    configuration = _provider_configuration(
        settings,
        IdentityProvider.GITHUB.value,
        purpose=OAuthPurpose.REPOSITORY_CONNECTION,
    )
    token = _post_form(
        configuration.token_url,
        {
            "client_id": configuration.client_id,
            "client_secret": configuration.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    refreshed = _github_credential_payload(token)
    if "refresh_token" not in refreshed:
        refreshed["refresh_token"] = refresh_token
    service.replace_payload(
        owner_id=owner_id,
        credential_id=credential_id,
        payload=refreshed,
    )
    return refreshed


def get_github_connection_status(
    *,
    engine,
    service: CredentialService,
    settings: AuthSettings,
    owner_id: UUID,
    now: datetime | None = None,
) -> GitHubConnectionStatus:
    """Return a safe, owner-scoped GitHub connection state.

    This intentionally never returns credential metadata or provider payload values.
    A token is refreshed only after its explicitly stored access-token expiry passes.
    """

    connection = _latest_github_connection(engine=engine, owner_id=owner_id)
    if connection is None:
        return GitHubConnectionStatus.NEVER_CONNECTED
    if connection["revoked_at"] is not None:
        return GitHubConnectionStatus.NEEDS_RECONNECTION

    credential_id = connection["credential_id"]
    try:
        metadata = service.metadata(owner_id=owner_id, credential_id=credential_id)
    except CredentialNotFound:
        return GitHubConnectionStatus.NEEDS_RECONNECTION
    except CredentialServiceError as error:
        raise OAuthUnavailable("GitHub credential service is unavailable") from error

    if (
        metadata.revoked_at is not None
        or metadata.provider is not CredentialProvider.GITHUB
        or metadata.kind is not CredentialKind.OAUTH
    ):
        return GitHubConnectionStatus.NEEDS_RECONNECTION

    try:
        payload = service.decrypt_for_provider_call(
            owner_id=owner_id, credential_id=credential_id
        )
    except CredentialNotFound:
        return GitHubConnectionStatus.NEEDS_RECONNECTION
    except CredentialServiceError as error:
        raise OAuthUnavailable("GitHub credential service is unavailable") from error

    if not isinstance(payload.get("access_token"), str) or not payload["access_token"]:
        return GitHubConnectionStatus.NEEDS_RECONNECTION

    expiration = _github_access_token_expiration(payload)
    if expiration is _INVALID_TOKEN_EXPIRATION:
        return GitHubConnectionStatus.NEEDS_RECONNECTION
    if expiration is None:
        return GitHubConnectionStatus.CONNECTED
    assert isinstance(expiration, datetime)
    if expiration > (now or datetime.now(UTC)):
        return GitHubConnectionStatus.CONNECTED

    try:
        refresh_github_credential(
            service=service,
            settings=settings,
            owner_id=owner_id,
            credential_id=credential_id,
        )
    except OAuthRejected:
        return GitHubConnectionStatus.NEEDS_RECONNECTION
    except CredentialServiceError as error:
        raise OAuthUnavailable("GitHub credential service is unavailable") from error
    return GitHubConnectionStatus.CONNECTED


class _InvalidTokenExpiration:
    pass


_INVALID_TOKEN_EXPIRATION = _InvalidTokenExpiration()


def _github_access_token_expiration(
    payload: dict[str, object],
) -> datetime | _InvalidTokenExpiration | None:
    value = payload.get("access_token_expires_at")
    if value is None:
        return None
    if not isinstance(value, str):
        return _INVALID_TOKEN_EXPIRATION
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return _INVALID_TOKEN_EXPIRATION
    if parsed.tzinfo is None:
        return _INVALID_TOKEN_EXPIRATION
    return parsed.astimezone(UTC)


def _latest_github_connection(*, engine, owner_id: UUID):
    try:
        with principal_transaction(engine, owner_id) as connection:
            return (
                connection.execute(
                    sa.select(ExternalRepository.__table__)
                    .where(
                        ExternalRepository.owner_id == owner_id,
                        ExternalRepository.source == RepositorySource.GITHUB,
                    )
                    .order_by(
                        ExternalRepository.updated_at.desc(),
                        ExternalRepository.created_at.desc(),
                        ExternalRepository.id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
    except sa.exc.SQLAlchemyError as error:
        raise OAuthUnavailable("GitHub connection storage is unavailable") from error


def _post_form(url: str, values: dict[str, str]) -> dict[str, object]:
    request = Request(
        url,
        data=urlencode(values).encode("ascii"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    payload = _read_json(request)
    if not isinstance(payload, dict):
        raise OAuthRejected("OAuth exchange failed")
    return payload


def _get_json(url: str, access_token: str) -> dict | list:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    return _read_json(request)


def _read_json(request: Request) -> dict | list:
    try:
        with urlopen(request, timeout=5) as response:
            payload = response.read(1_048_577)
            if len(payload) > 1_048_576:
                raise OAuthRejected("Provider response is too large")
    except (HTTPError, URLError, TimeoutError) as error:
        raise OAuthUnavailable("OAuth provider is unavailable") from error
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OAuthRejected("Provider response is invalid") from error
    if not isinstance(decoded, (dict, list)):
        raise OAuthRejected("Provider response is invalid")
    return decoded


def _pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


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


def _set_session(
    response: Response,
    access_token: str,
    refresh_token: str,
    session_id: UUID,
    settings: AuthSettings,
) -> str:
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
    csrf_token = issue_csrf_token(session_id=session_id, key=csrf_key)
    set_csrf_cookie(
        response,
        csrf_token=csrf_token,
        settings=settings,
    )
    return csrf_token


def _oauth_failure_redirect(
    destination: str,
    request_id: str,
    *,
    purpose: OAuthPurpose = OAuthPurpose.LOGIN,
) -> RedirectResponse:
    if destination.startswith("trace://oauth/callback"):
        return RedirectResponse(
            f"trace://oauth/callback?{urlencode({'error': 'oauth_failed', 'request_id': request_id})}",
            status_code=303,
        )
    if purpose != OAuthPurpose.LOGIN:
        return _connection_redirect(
            destination,
            outcome="failed",
            request_id=request_id,
            provider=(
                CredentialProvider.GITHUB.value
                if purpose == OAuthPurpose.REPOSITORY_CONNECTION
                else CredentialProvider.LINEAR.value
            ),
        )
    return RedirectResponse(
        f"{destination.rstrip('/')}/auth/callback?{urlencode({'error': 'oauth_failed', 'request_id': request_id})}",
        status_code=303,
    )


def _repository_connection_redirect(
    destination: str, *, outcome: Literal["connected", "failed"], request_id: str
) -> RedirectResponse:
    return RedirectResponse(
        f"{destination.rstrip('/')}/integrations?{urlencode({'github': outcome, 'request_id': request_id})}",
        status_code=303,
    )


def _connection_redirect(
    destination: str,
    *,
    outcome: Literal["connected", "failed"],
    request_id: str,
    provider: str,
) -> RedirectResponse:
    if provider == CredentialProvider.GITHUB.value:
        return _repository_connection_redirect(
            destination,
            outcome=outcome,
            request_id=request_id,
        )
    return RedirectResponse(
        f"{destination.rstrip('/')}/integrations?{urlencode({'linear': outcome, 'request_id': request_id})}",
        status_code=303,
    )


def _unavailable() -> AuthError:
    return AuthError(
        code="auth_temporarily_unavailable",
        message="Authentication is temporarily unavailable.",
        status_code=503,
        event="dependency",
        reason="dependency_unavailable",
    )


def _invalid_request() -> AuthError:
    return AuthError(
        code="invalid_request",
        message="The request could not be processed.",
        status_code=400,
        event="request",
        reason="invalid_input",
    )


def _authentication_failed() -> AuthError:
    return AuthError(
        code="authentication_failed",
        message="Authentication failed.",
        status_code=401,
        event="authentication",
        reason="oauth_rejected",
    )


def _require_connection_csrf(
    request: FastAPIRequest,
    principal: AuthenticatedPrincipal,
    settings: AuthSettings,
) -> None:
    if settings.csrf_hmac_key is None:
        raise _unavailable()
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
            reason="csrf_invalid",
        )
