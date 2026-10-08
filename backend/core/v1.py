"""Version-one API composition.

Feature routers are assembled here so the application has one explicit public
API boundary.  The feature modules select their own route groups from the
shared compatibility router while the extraction is completed.
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter

from agents.routes import build_router as build_agents_router
from artifacts.routes import build_router as build_artifacts_router
from audit.outbox import AuditRecorder
from auth.audit import AuditHasher
from auth.config import AuthSettings
from credentials.routes import build_router as build_credentials_router
from findings.routes import build_router as build_findings_router
from projects.routes import build_router as build_projects_router
from remediations.routes import build_router as build_remediations_router
from resources.router import build_resource_router
from resources.services import ReviewDispatcher
from reviews.routes import build_router as build_reviews_router

# Exported for introspection and for callers that only need the public prefix.
# Runtime dependencies are installed by ``build_router`` below.
router = APIRouter(prefix="/api/v1")


def build_router(
    settings: AuthSettings,
    audit_hasher: AuditHasher | None = None,
    dispatcher: ReviewDispatcher | None = None,
    audit_recorder: AuditRecorder | None = None,
) -> APIRouter:
    """Build the configured v1 router for one application instance."""

    resource_router = build_resource_router(
        settings,
        audit_hasher,
        dispatcher,
        audit_recorder,
    )
    version_router = APIRouter(prefix="/api/v1")

    router_tags: list[tuple[APIRouter, list[str | Enum]]] = [
        (build_projects_router(resource_router), ["projects"]),
        (build_agents_router(resource_router), ["agents"]),
        (build_reviews_router(resource_router), ["reviews"]),
        (build_findings_router(resource_router), ["findings"]),
        (build_remediations_router(resource_router), ["remediations"]),
        (build_artifacts_router(resource_router), ["artifacts"]),
        (build_credentials_router(resource_router), ["credentials"]),
    ]
    for feature_router, tags in router_tags:
        version_router.include_router(feature_router, tags=tags)

    return version_router


def configure_router(
    settings: AuthSettings,
    audit_hasher: AuditHasher | None = None,
    dispatcher: ReviewDispatcher | None = None,
    audit_recorder: AuditRecorder | None = None,
) -> APIRouter:
    """Install one application's configured routes into the exported router.

    ``main`` includes the exported ``router`` as the single v1 boundary.  The
    route objects are copied from a per-application build so settings and
    audit dependencies are not created at import time.
    """

    configured = build_router(settings, audit_hasher, dispatcher, audit_recorder)
    router.routes.clear()
    router.routes.extend(configured.routes)
    return router
