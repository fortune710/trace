"""Process-local SSE fan-out backed by PostgreSQL transaction notifications."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from uuid import UUID

from db.session import DatabaseSettings

logger = logging.getLogger(__name__)


class NotificationBroker:
    def __init__(self) -> None:
        self._subscribers: defaultdict[UUID, set[asyncio.Queue[UUID]]] = defaultdict(
            set
        )
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        running_loop = asyncio.get_running_loop()
        if self._task is not None and (
            self._task.done() or self._task.get_loop() is not running_loop
        ):
            self._task.cancel()
            self._task = None
        if self._task is None:
            self._task = asyncio.create_task(
                self._listen(), name="notification-listener"
            )

    async def stop(self) -> None:
        if self._task is not None:
            task = self._task
            self._task = None
            task.cancel()
            if task.get_loop() is not asyncio.get_running_loop():
                return
            try:
                await task
            except asyncio.CancelledError:
                pass

    def subscribe(self, owner_id: UUID) -> asyncio.Queue[UUID]:
        queue: asyncio.Queue[UUID] = asyncio.Queue(maxsize=100)
        self._subscribers[owner_id].add(queue)
        return queue

    def unsubscribe(self, owner_id: UUID, queue: asyncio.Queue[UUID]) -> None:
        self._subscribers[owner_id].discard(queue)
        if not self._subscribers[owner_id]:
            self._subscribers.pop(owner_id, None)

    def publish(self, owner_id: UUID, notification_id: UUID) -> None:
        """Fan out one committed notification to the owning account's streams."""
        for queue in tuple(self._subscribers.get(owner_id, ())):
            try:
                queue.put_nowait(notification_id)
            except asyncio.QueueFull:
                logger.warning("notification_subscriber_backpressure")

    async def _listen(self) -> None:
        settings = DatabaseSettings()
        if not settings.database_url:
            return
        dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        while True:
            try:
                # Import lazily: test and migration environments may not ship
                # libpq, while the production backend image provides it.
                import psycopg

                async with await psycopg.AsyncConnection.connect(
                    dsn, autocommit=True
                ) as connection:
                    await connection.execute("LISTEN trace_notifications")
                    async for notice in connection.notifies():
                        try:
                            payload = json.loads(notice.payload)
                            owner_id = UUID(payload["owner_id"])
                            notification_id = UUID(payload["notification_id"])
                        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                            logger.warning("notification_notice_invalid")
                            continue
                        self.publish(owner_id, notification_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("notification_listener_unavailable")
                await asyncio.sleep(1)


broker = NotificationBroker()
