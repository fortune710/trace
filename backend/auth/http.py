from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.config import AuthSettings


def install_auth_cors(app: FastAPI, settings: AuthSettings) -> None:
    """Install credentialed CORS only for explicit frontend origins."""
    allowed_origins = list(
        dict.fromkeys([*settings.allowed_origins, *settings.desktop_allowed_origins])
    )
    if not allowed_origins:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
