"""Project route group."""

from fastapi import APIRouter

from resources.router import select_routes

router = APIRouter()


def build_router(resource_router: APIRouter) -> APIRouter:
    return select_routes(resource_router, ("/projects",))
