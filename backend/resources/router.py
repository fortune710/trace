"""Compatibility adapter that exposes the resource routes as an APIRouter.

The route handlers remain behaviorally identical during the package extraction.
The public composition point is ``core.v1``; this adapter keeps the extraction
incremental and avoids duplicating security-sensitive route code.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from audit.outbox import AuditRecorder
from auth.audit import AuditHasher
from auth.config import AuthSettings
from resources.routes import install_resource_routes
from resources.services import ReviewDispatcher


def build_resource_router(
    settings: AuthSettings,
    audit_hasher: AuditHasher | None = None,
    dispatcher: ReviewDispatcher | None = None,
    audit_recorder: AuditRecorder | None = None,
) -> APIRouter:
    """Build the existing resource handlers without registering old paths.

    ``install_resource_routes`` predates the feature packages and registers
    handlers on an application.  Harvesting its APIRoute objects into a
    router lets the v1 composition layer own the public prefix while keeping
    all existing dependencies and authorization behavior unchanged.
    """

    temporary_app = FastAPI()
    install_resource_routes(
        temporary_app,
        settings,
        audit_hasher,
        dispatcher,
        audit_recorder,
    )
    router = APIRouter()
    router.routes.extend(
        route for route in temporary_app.router.routes if isinstance(route, APIRoute)
    )
    return router


def select_routes(
    resource_router: APIRouter,
    prefixes: tuple[str, ...],
    excludes: tuple[str, ...] = (),
    exact: tuple[str, ...] = (),
) -> APIRouter:
    """Return a feature router containing only its path group."""

    selected = APIRouter()
    for route in resource_router.routes:
        if not isinstance(route, APIRoute):
            continue
        matches_prefix = any(
            route.path == prefix or route.path.startswith(f"{prefix}/")
            for prefix in prefixes
        )
        matches_exact = route.path in exact
        excluded = any(
            route.path == prefix or route.path.startswith(f"{prefix}/")
            for prefix in excludes
        )
        if (matches_prefix or matches_exact) and not excluded:
            selected.routes.append(route)
    return selected
