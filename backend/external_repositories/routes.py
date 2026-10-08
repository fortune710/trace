"""Owner-scoped repository browsing routes."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, Query

from auth.config import AuthSettings
from auth.credential_service import CredentialService
from auth.credentials import credential_cipher_from_settings
from auth.principal import CurrentPrincipal
from auth.rate_limit import (
    AUTH_RATE_LIMIT_POLICIES,
    enforce_rate_limit,
    rate_limiter_from_settings,
)
from db.session import get_engine
from resources.schemas import BranchPage, RepositoryPage

from .service import RepositoryService


def build_router(
    settings: AuthSettings,
    *,
    prefix: str = "/repositories",
) -> APIRouter:
    router = APIRouter(prefix=prefix)

    @lru_cache
    def repository_service() -> RepositoryService:
        return RepositoryService(
            engine=get_engine(),
            credential_service=CredentialService(
                engine=get_engine(),
                cipher=credential_cipher_from_settings(settings),
            ),
            settings=settings,
        )

    @lru_cache
    def repository_rate_limiter():
        return rate_limiter_from_settings(settings)

    async def require_repository_read_limit(
        principal: CurrentPrincipal,
    ) -> None:
        await enforce_rate_limit(
            repository_rate_limiter(),
            policy=AUTH_RATE_LIMIT_POLICIES["resource.repository_read.user"],
            subject=str(principal.user_id),
        )

    @router.get(
        "",
        response_model=RepositoryPage,
        dependencies=[Depends(require_repository_read_limit)],
    )
    def list_repositories(
        principal: CurrentPrincipal,
        source: str = Query(..., min_length=1, max_length=32),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, object]:
        result = repository_service().list_repositories(
            owner_id=principal.user_id,
            source=source,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [
                {
                    "source": source,
                    "repository_id": item.repository_id,
                    "owner_login": item.owner_login,
                    "name": item.name,
                    "full_name": item.full_name,
                    "visibility": item.visibility,
                    "private": item.private,
                    "default_branch": item.default_branch,
                    "web_url": item.web_url,
                }
                for item in result.items
            ],
            "next_page": result.next_page,
        }

    @router.get(
        "/{repository_identifier}/branches",
        response_model=BranchPage,
        dependencies=[Depends(require_repository_read_limit)],
    )
    def list_branches(
        principal: CurrentPrincipal,
        repository_identifier: str,
        source: str = Query(..., min_length=1, max_length=32),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, object]:
        result = repository_service().list_branches(
            owner_id=principal.user_id,
            source=source,
            repository_identifier=repository_identifier,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [
                {
                    "source": source,
                    "repository_id": item.repository_id,
                    "name": item.name,
                    "commit_sha": item.commit_sha,
                    "protected": item.protected,
                }
                for item in result.items
            ],
            "next_page": result.next_page,
        }

    return router
