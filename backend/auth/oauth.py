"""OAuth authorization-code/PKCE routes with Redis-backed single-use state."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, asdict
import hashlib
import hmac
import json
import secrets
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import UUID

import jwt
from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.responses import RedirectResponse
from jwt import PyJWKClient
from redis.exceptions import RedisError

from auth.audit import AuditHasher, log_auth_event
from auth.config import AuthSettings
from auth.cookies import set_auth_cookies, set_csrf_cookie
from auth.csrf import issue_csrf_token
from auth.errors import AuthError
from auth.rate_limit import AUTH_RATE_LIMIT_POLICIES, enforce_rate_limit, rate_limiter_from_settings
from auth.service import AuthService, AuthenticationUnavailable
from auth.tokens import decode_base64url_key, generate_opaque_token
from db.models import IdentityProvider
from db.session import get_engine, get_redis_client


_STATE_TTL_SECONDS = 600
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_GITHUB_EMAILS_URL = "https://api.github.com/user/emails"
_GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
OAUTH_CALLBACK_ROUTE = "/auth/oauth/{provider}/callback"


class OAuthUnavailable(RuntimeError):
    pass


class OAuthRejected(ValueError):
    pass


@dataclass(frozen=True)
class OAuthTransaction:
    provider: str
    verifier: str
    nonce: str | None
    destination: str
    user_agent_hash: str


class OAuthStateStore:
    def __init__(self, *, redis_client, state_key: bytes) -> None:
        self._redis = redis_client
        self._state_key = state_key

    async def create(self, *, provider: str, destination: str, user_agent: str | None) -> tuple[str, str, str | None]:
        state = generate_opaque_token()
        verifier = generate_opaque_token()
        nonce = generate_opaque_token() if provider == IdentityProvider.GOOGLE.value else None
        transaction = OAuthTransaction(
            provider=provider,
            verifier=verifier,
            nonce=nonce,
            destination=destination,
            user_agent_hash=self._digest(user_agent or ""),
        )
        try:
            created = await self._redis.set(self._key(state), json.dumps(asdict(transaction), separators=(",", ":")), ex=_STATE_TTL_SECONDS, nx=True)
        except RedisError as error:
            raise OAuthUnavailable("OAuth state storage is unavailable") from error
        if not created:
            raise OAuthUnavailable("OAuth state storage is unavailable")
        return state, verifier, nonce

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
            transaction = OAuthTransaction(**decoded)
            if (
                transaction.provider not in {IdentityProvider.GITHUB.value, IdentityProvider.GOOGLE.value}
                or not transaction.verifier
                or not transaction.destination
            ):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise OAuthRejected("OAuth state is invalid") from error
        return transaction

    def _key(self, state: str) -> str:
        return f"trace:oauth:v1:{self._digest(state)}"

    def _digest(self, value: str) -> str:
        return hmac.new(self._state_key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def install_oauth_routes(app: FastAPI, settings: AuthSettings, audit_hasher: AuditHasher | None) -> None:
    service: AuthService | None = None
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

    def state_store() -> OAuthStateStore:
        nonlocal store
        if store is None:
            assert settings.token_hash_key is not None
            store = OAuthStateStore(
                redis_client=get_redis_client(),
                state_key=decode_base64url_key(settings.token_hash_key.get_secret_value(), name="AUTH_TOKEN_HASH_KEY"),
            )
        return store

    def audit(request: FastAPIRequest, *, event: str, outcome: str, reason: str, status_code: int, provider: str) -> None:
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

    @app.get("/auth/oauth/{provider}/start")
    async def oauth_start(request: FastAPIRequest, provider: str, return_to: str | None = None):
        provider_config = _provider_configuration(settings, provider)
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
        audit(request, event="oauth", outcome="accepted", reason="authorization_started", status_code=302, provider=provider)
        return RedirectResponse(f"{provider_config.authorize_url}?{urlencode(parameters)}", status_code=302)

    @app.get(OAUTH_CALLBACK_ROUTE)
    async def oauth_callback(request: FastAPIRequest, provider: str, state: str | None = None, code: str | None = None, error: str | None = None):
        request_id = getattr(request.state, "request_id", "unavailable")
        fallback_destination = settings.frontend_url.rstrip("/")
        if error or not state or not code:
            audit(request, event="oauth", outcome="rejected", reason="callback_malformed", status_code=400, provider=provider)
            return _oauth_failure_redirect(fallback_destination, request_id)
        try:
            transaction = await state_store().consume(state)
            if transaction.provider != provider:
                raise OAuthRejected("OAuth state is invalid")
            configuration = _provider_configuration(settings, provider)
            subject, email = await asyncio.to_thread(_provider_identity, configuration, code, transaction)
            result = await asyncio.to_thread(auth_service().oauth_login, provider=IdentityProvider(provider), subject=subject, email=email)
            if result.tokens is None:
                raise OAuthRejected("OAuth account is not eligible")
        except (OAuthRejected, ValueError, AuthError):
            audit(request, event="oauth", outcome="rejected", reason="callback_rejected", status_code=401, provider=provider)
            return _oauth_failure_redirect(fallback_destination, request_id)
        except (OAuthUnavailable, AuthenticationUnavailable) as error:
            audit(request, event="oauth", outcome="rejected", reason="dependency_unavailable", status_code=503, provider=provider)
            return _oauth_failure_redirect(fallback_destination, request_id)

        response = RedirectResponse(f"{transaction.destination.rstrip('/')}/auth/callback", status_code=303)
        _set_session(response, result.tokens.access_token, result.tokens.refresh_token, result.tokens.session_id, settings)
        audit(request, event="oauth", outcome="accepted", reason="session_created", status_code=303, provider=provider)
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


def _provider_configuration(settings: AuthSettings, provider: str) -> ProviderConfiguration:
    if provider == IdentityProvider.GITHUB.value:
        client_id, secret, redirect_uri = settings.github_client_id, settings.github_client_secret, settings.github_redirect_uri
        config = ProviderConfiguration(provider, client_id or "", secret.get_secret_value() if secret else "", redirect_uri or "", _GITHUB_AUTHORIZE_URL, _GITHUB_TOKEN_URL, "read:user user:email")
    elif provider == IdentityProvider.GOOGLE.value:
        client_id, secret, redirect_uri = settings.google_client_id, settings.google_client_secret, settings.google_redirect_uri
        config = ProviderConfiguration(provider, client_id or "", secret.get_secret_value() if secret else "", redirect_uri or "", _GOOGLE_AUTHORIZE_URL, _GOOGLE_TOKEN_URL, "openid email profile")
    else:
        raise _invalid_request()
    parsed = urlparse(config.redirect_uri)
    if not config.client_id or not config.client_secret or parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path != oauth_callback_path(provider):
        raise _unavailable()
    return config


def oauth_callback_path(provider: str) -> str:
    return OAUTH_CALLBACK_ROUTE.format(provider=provider)


def _provider_identity(config: ProviderConfiguration, code: str, transaction: OAuthTransaction) -> tuple[str, str]:
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
        user = _get_json(_GITHUB_USER_URL, access_token)
        emails = _get_json(_GITHUB_EMAILS_URL, access_token)
        if not isinstance(user, dict) or not isinstance(emails, list):
            raise OAuthRejected("GitHub identity is invalid")
        subject = user.get("id")
        if not isinstance(subject, int):
            raise OAuthRejected("GitHub identity is invalid")
        email = next(
            (
                item.get("email")
                for item in emails
                if isinstance(item, dict) and item.get("primary") is True and item.get("verified") is True and isinstance(item.get("email"), str)
            ),
            None,
        )
        if not isinstance(email, str):
            raise OAuthRejected("GitHub email is unavailable")
        return str(subject), email
    id_token = token.get("id_token")
    if not isinstance(id_token, str) or not transaction.nonce:
        raise OAuthRejected("Google identity is invalid")
    try:
        signing_key = PyJWKClient(_GOOGLE_JWKS_URL, cache_keys=True).get_signing_key_from_jwt(id_token)
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
    if claims.get("nonce") != transaction.nonce or claims.get("email_verified") is not True:
        raise OAuthRejected("Google identity is invalid")
    subject, email = claims.get("sub"), claims.get("email")
    if not isinstance(subject, str) or not subject or not isinstance(email, str):
        raise OAuthRejected("Google identity is invalid")
    return subject, email


def _post_form(url: str, values: dict[str, str]) -> dict[str, object]:
    request = Request(
        url,
        data=urlencode(values).encode("ascii"),
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return _read_json(request)


def _get_json(url: str, access_token: str) -> dict | list:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {access_token}"})
    return _read_json(request)


def _read_json(request: Request) -> dict | list:
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310 -- provider URLs are module constants
            payload = response.read(1_048_577)
            if len(payload) > 1_048_576:
                raise OAuthRejected("Provider response is too large")
    except (HTTPError, URLError, TimeoutError, socket.timeout) as error:
        raise OAuthUnavailable("OAuth provider is unavailable") from error
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OAuthRejected("Provider response is invalid") from error
    if not isinstance(decoded, (dict, list)):
        raise OAuthRejected("Provider response is invalid")
    return decoded


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _destination(settings: AuthSettings, requested: str | None) -> str:
    destination = requested or settings.frontend_url
    parsed = urlparse(destination)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = set(settings.allowed_origins) or {settings.frontend_url.rstrip("/")}
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or origin not in allowed:
        raise ValueError("Return URL is invalid")
    return origin


def _set_session(response: RedirectResponse, access_token: str, refresh_token: str, session_id: UUID, settings: AuthSettings) -> None:
    set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token, settings=settings)
    assert settings.csrf_hmac_key is not None
    csrf_key = decode_base64url_key(settings.csrf_hmac_key.get_secret_value(), name="AUTH_CSRF_HMAC_KEY")
    set_csrf_cookie(response, csrf_token=issue_csrf_token(session_id=session_id, key=csrf_key), settings=settings)


def _oauth_failure_redirect(destination: str, request_id: str) -> RedirectResponse:
    return RedirectResponse(f"{destination.rstrip('/')}/auth/callback?{urlencode({'error': 'oauth_failed', 'request_id': request_id})}", status_code=303)


def _unavailable() -> AuthError:
    return AuthError(code="auth_temporarily_unavailable", message="Authentication is temporarily unavailable.", status_code=503, event="dependency", reason="dependency_unavailable")


def _invalid_request() -> AuthError:
    return AuthError(code="invalid_request", message="The request could not be processed.", status_code=400, event="request", reason="invalid_input")
