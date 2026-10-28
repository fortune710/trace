"""RabbitMQ consumer that starts automatic remediation pull-request publication."""

from __future__ import annotations

import logging
import signal
from typing import Any

import sqlalchemy as sa

from audit.outbox import AuditRecorder
from auth.config import AuthSettings
from auth.credential_service import CredentialService
from auth.credentials import credential_cipher_from_settings
from auth.errors import AuthError, ProviderRateLimited, ProviderUnavailable
from db.session import get_engine
from external_repositories.service import RepositoryService
from remediations.config import RemediationPullRequestDispatchSettings
from remediations.dispatch import (
    REMEDIATION_PR_QUEUE,
    _open_connection,
    declare_remediation_pull_request_topology,
)
from remediations.queueing import (
    RemediationPullRequestMessageInvalid,
    RemediationPullRequestMessageV1,
)
from remediations.service import RemediationPullRequestService

logger = logging.getLogger("trace.remediation_pr_execution")


def handle_delivery(
    active_channel: Any,
    method: Any,
    body: bytes,
    *,
    service: RemediationPullRequestService,
) -> None:
    """Handle one identifier-only message without exposing remediation content."""
    try:
        message = RemediationPullRequestMessageV1.decode(body)
    except RemediationPullRequestMessageInvalid:
        logger.warning("queue_message_invalid")
        active_channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
        return
    try:
        service.publish_queued(
            owner_id=message.owner_id,
            remediation_id=message.remediation_id,
            request_id=f"remediation-pr-queue:{message.idempotency_id}",
        )
    except (ProviderRateLimited, ProviderUnavailable):
        service.enqueue_retry(
            owner_id=message.owner_id,
            remediation_id=message.remediation_id,
            request_id=f"remediation-pr-queue:{message.idempotency_id}",
        )
    except AuthError:
        logger.info("remediation_pr_queue_terminal")
    except sa.exc.SQLAlchemyError:
        logger.warning("remediation_pr_queue_recovery_required")
        active_channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        return
    active_channel.basic_ack(delivery_tag=method.delivery_tag)


def run() -> None:
    dispatch_settings = RemediationPullRequestDispatchSettings()
    dispatch_settings.validate_for_dispatch()
    auth_settings = AuthSettings()
    engine = get_engine()
    service = RemediationPullRequestService(
        engine,
        RepositoryService(
            engine=engine,
            credential_service=CredentialService(
                engine=engine,
                cipher=credential_cipher_from_settings(
                    auth_settings, validate_authentication=False
                ),
            ),
            settings=auth_settings,
        ),
        AuditRecorder(engine),
    )
    connection = _open_connection(dispatch_settings.rabbitmq_url or "", heartbeat=0)
    channel = connection.channel()
    declare_remediation_pull_request_topology(channel)
    channel.basic_qos(prefetch_count=1)

    def on_delivery(
        active_channel: Any, method: Any, _properties: Any, body: bytes
    ) -> None:
        handle_delivery(
            active_channel,
            method,
            body,
            service=service,
        )

    def stop(*_args: object) -> None:
        channel.stop_consuming()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    channel.basic_consume(
        queue=REMEDIATION_PR_QUEUE,
        on_message_callback=on_delivery,
        auto_ack=False,
    )
    try:
        channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    run()
