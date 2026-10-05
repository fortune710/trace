import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware

from auth.audit import AuditHasher
from auth.config import AuthSettings, get_auth_settings
from auth.credentials import CredentialEncryptionUnavailable, VaultTransitClient
from auth.errors import install_auth_error_handlers
from auth.http import install_auth_cors
from auth.oauth import install_oauth_routes
from auth.routes import install_auth_routes
from auth.tokens import decode_base64url_key
from auth.uuids import uuid7
from db.session import close_redis_client, get_engine, get_redis_client


logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.request_id = str(uuid7())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


def _audit_hasher(settings: AuthSettings) -> AuditHasher | None:
    if settings.audit_hash_key is None or not settings.audit_hash_key.get_secret_value():
        return None
    try:
        return AuditHasher(
            decode_base64url_key(settings.audit_hash_key.get_secret_value(), name="AUTH_AUDIT_HASH_KEY")
        )
    except ValueError:
        return None


def _vault_client(settings: AuthSettings) -> VaultTransitClient:
    assert settings.vault_addr is not None
    assert settings.vault_token is not None
    return VaultTransitClient(
        address=settings.vault_addr,
        token=settings.vault_token.get_secret_value(),
        timeout_seconds=settings.vault_request_timeout_seconds,
    )


async def _renew_vault_token_forever(client: VaultTransitClient, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(client.renew_self)
        except CredentialEncryptionUnavailable:
            logger.error("vault_token_renewal_failed")


def create_app(settings: AuthSettings | None = None) -> FastAPI:
    auth_settings = settings or get_auth_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        auth_settings.validate_for_authentication()
        vault_renewal_task: asyncio.Task[None] | None = None
        if auth_settings.credential_encryption_provider == "vault":
            vault_client = _vault_client(auth_settings)
            await asyncio.to_thread(vault_client.renew_self)
            vault_renewal_task = asyncio.create_task(
                _renew_vault_token_forever(vault_client, auth_settings.vault_token_renewal_seconds)
            )
        try:
            yield
        finally:
            if vault_renewal_task is not None:
                vault_renewal_task.cancel()
                with suppress(asyncio.CancelledError):
                    await vault_renewal_task
            await close_redis_client()

    application = FastAPI(title="Trace API", lifespan=lifespan)
    install_auth_cors(application, auth_settings)
    application.add_middleware(RequestIdMiddleware)
    audit_hasher = _audit_hasher(auth_settings)
    install_auth_error_handlers(application, audit_hasher)
    install_auth_routes(application, auth_settings, audit_hasher)
    install_oauth_routes(application, auth_settings, audit_hasher)

    @application.get("/")
    def read_root() -> dict[str, str]:
        return {"message": "Trace API is running"}

    @application.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", response_model=None)
    async def readiness_check():
        try:
            await get_redis_client().ping()
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
        except (RuntimeError, RedisError, SQLAlchemyError):
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "unavailable"})

        return {"status": "ok"}

    return application


app = create_app()
