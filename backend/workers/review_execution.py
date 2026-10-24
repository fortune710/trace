"""RabbitMQ consumer that executes selected review agents."""

from __future__ import annotations

import logging
import signal
from typing import Any

from agents.execution.executor import ReviewExecutionService
from auth.config import AuthSettings
from auth.credential_service import CredentialService
from auth.credentials import credential_cipher_from_settings
from db.session import get_engine
from reviews.config import AgentExecutionSettings
from reviews.dispatch import (
    REVIEW_DISPATCH_QUEUE,
    _open_connection,
    declare_review_dispatch_topology,
)
from reviews.queueing import ReviewDispatchMessageInvalid, ReviewDispatchMessageV1

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trace.review_execution_worker")


def run() -> None:
    execution_settings = AgentExecutionSettings()
    execution_settings.validate_for_execution()
    auth_settings = AuthSettings()
    engine = get_engine()
    credentials = CredentialService(
        engine=engine, cipher=credential_cipher_from_settings(auth_settings)
    )
    service = ReviewExecutionService(
        engine=engine,
        credential_service=credentials,
        settings=execution_settings,
    )
    connection = _open_connection(execution_settings.rabbitmq_url or "")
    channel = connection.channel()
    declare_review_dispatch_topology(channel)
    channel.basic_qos(prefetch_count=1)

    def handle_delivery(
        active_channel: Any, method: Any, _properties: Any, body: bytes
    ) -> None:
        try:
            message = ReviewDispatchMessageV1.decode(body)
        except ReviewDispatchMessageInvalid:
            logger.warning("queue_message_invalid")
            active_channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
            return
        try:
            service.execute(
                owner_id=message.owner_id,
                review_id=message.review_id,
                dispatch_id=message.idempotency_id,
            )
        except Exception:  # Database failures must redeliver instead of losing work.
            logger.exception("review_execution_recovery_required")
            active_channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            return
        active_channel.basic_ack(delivery_tag=method.delivery_tag)

    def stop(*_args: object) -> None:
        logger.info("review_execution_worker_stopping")
        channel.stop_consuming()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    channel.basic_consume(
        queue=REVIEW_DISPATCH_QUEUE,
        on_message_callback=handle_delivery,
        auto_ack=False,
    )
    try:
        channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    run()
