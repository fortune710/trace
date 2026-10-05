"""RabbitMQ worker for encrypted verification and password-recovery email jobs."""

from __future__ import annotations

import logging
import signal
from typing import Any

from auth.config import AuthSettings
from auth.credentials import email_payload_cipher_from_settings
from auth.email_delivery import EmailJobConsumer, EmailJobDispatcher, EmailJobStore, SMTPEmailSender
from auth.queueing import EMAIL_MAIN_QUEUE, RabbitMQEmailPublisher, _open_connection, declare_email_topology
from db.session import get_engine


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trace.email_worker")


def run() -> None:
    settings = AuthSettings()
    if not settings.rabbitmq_url or not settings.smtp_host:
        raise RuntimeError("Email worker configuration is incomplete")
    cipher = email_payload_cipher_from_settings(settings)
    store = EmailJobStore(get_engine())
    publisher = RabbitMQEmailPublisher(
        url=settings.rabbitmq_url,
        retry_delays_seconds=settings.email_retry_delays_seconds,
    )
    dispatcher = EmailJobDispatcher(store, publisher)
    dispatcher.dispatch_pending()
    sender = SMTPEmailSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.email_from,
        username=settings.smtp_username,
        password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
        use_starttls=settings.smtp_use_starttls,
    )
    consumer = EmailJobConsumer(
        store=store,
        cipher=cipher,
        sender=sender,
        publisher=publisher,
        max_retries=settings.email_max_retries,
    )
    connection = _open_connection(settings.rabbitmq_url)
    channel = connection.channel()
    declare_email_topology(channel, retry_delays_seconds=settings.email_retry_delays_seconds)
    channel.basic_qos(prefetch_count=1)

    def handle_delivery(active_channel: Any, method: Any, _properties: Any, body: bytes) -> None:
        consumer.consume(delivery_tag=method.delivery_tag, body=body, channel=active_channel)

    def stop(*_args: object) -> None:
        logger.info("email_worker_stopping")
        channel.stop_consuming()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    channel.basic_consume(queue=EMAIL_MAIN_QUEUE, on_message_callback=handle_delivery, auto_ack=False)
    try:
        channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    run()
