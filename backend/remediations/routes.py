"""Remediation route group."""

from fastapi import APIRouter

from resources.router import select_routes

router = APIRouter()


def build_router(resource_router: APIRouter) -> APIRouter:
    return select_routes(
        resource_router,
        (),
        exact=(
            "/findings/{finding_id}/remediations",
            "/remediations/{remediation_id}",
            "/remediations/{remediation_id}/approve",
            "/remediations/{remediation_id}/reject",
        ),
    )
