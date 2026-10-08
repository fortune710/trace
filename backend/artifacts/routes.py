"""Artifact route group."""

from fastapi import APIRouter

from resources.router import select_routes

router = APIRouter()


def build_router(resource_router: APIRouter) -> APIRouter:
    return select_routes(
        resource_router,
        ("/pull-requests", "/local-file-backups"),
        exact=(
            "/remediations/{remediation_id}/pull-request",
            "/remediations/{remediation_id}/local-file-backup",
        ),
    )
