from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from auth.config import AuthSettings
from auth.csrf import validate_csrf_token
from auth.errors import ResourceNotFound
from auth.principal import CurrentPrincipal
from auth.tokens import decode_base64url_key
from db.session import get_engine
from notifications.schemas import (
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationPage,
)
from notifications.service import NotificationService
from notifications.stream import broker


def format_notification_event(item: dict[str, object]) -> str:
    """Return one compact SSE event for an already validated response DTO."""
    return (
        f"id: {item['id']}\n"
        "event: notification\n"
        f"data: {json.dumps(item, default=str, separators=(',', ':'))}\n\n"
    )


def build_router(settings: AuthSettings) -> APIRouter:
    router = APIRouter(prefix="/notifications")

    @lru_cache
    def service() -> NotificationService:
        return NotificationService(get_engine())

    def require_csrf(request: Request, principal: CurrentPrincipal) -> None:
        if settings.csrf_hmac_key is None:
            raise ResourceNotFound()
        if not validate_csrf_token(
            cookie_token=request.cookies.get(settings.csrf_cookie_name),
            header_token=request.headers.get("X-CSRF-Token"),
            session_id=principal.session_id,
            key=decode_base64url_key(
                settings.csrf_hmac_key.get_secret_value(), name="AUTH_CSRF_HMAC_KEY"
            ),
        ):
            from auth.errors import AuthError

            raise AuthError(
                code="csrf_validation_failed",
                message="The request could not be processed.",
                status_code=403,
                event="csrf",
                reason="csrf_invalid",
            )

    @router.get("", response_model=NotificationPage)
    def list_notifications(
        principal: CurrentPrincipal,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, object]:
        items, next_offset, unread_count = service().list(
            owner_id=principal.user_id, limit=page_size, offset=(page - 1) * page_size
        )
        return {
            "items": items,
            "next_offset": next_offset,
            "unread_count": unread_count,
        }

    @router.patch("/read", response_model=MarkAllReadResponse)
    def mark_all_read(
        request: Request, principal: CurrentPrincipal
    ) -> dict[str, object]:
        require_csrf(request, principal)
        count, read_at = service().mark_all_read(owner_id=principal.user_id)
        return {"marked_count": count, "read_at": read_at}

    @router.patch("/{notification_id}/read", response_model=MarkReadResponse)
    def mark_read(
        request: Request, notification_id: UUID, principal: CurrentPrincipal
    ) -> dict[str, object]:
        require_csrf(request, principal)
        item, changed = service().mark_read(
            owner_id=principal.user_id, notification_id=notification_id
        )
        if item is None:
            raise ResourceNotFound()
        return {"item": item, "changed": changed}

    @router.get("/stream")
    async def stream_notifications(
        request: Request, principal: CurrentPrincipal
    ) -> StreamingResponse:
        queue = broker.subscribe(principal.user_id)

        async def events() -> AsyncIterator[str]:
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        notification_id = await asyncio.wait_for(
                            queue.get(), timeout=15
                        )
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    item = await asyncio.to_thread(
                        service().get,
                        owner_id=principal.user_id,
                        notification_id=notification_id,
                    )
                    if item is not None:
                        yield format_notification_event(item)
            finally:
                broker.unsubscribe(principal.user_id, queue)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
