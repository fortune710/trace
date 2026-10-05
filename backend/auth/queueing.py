"""Durable RabbitMQ transport for encrypted email-delivery job identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Protocol
from uuid import UUID


try:  # Keeps unit-test imports useful before the optional runtime is constructed.
    import pika
    from pika.exceptions import AMQPError, AMQPConnectionError
except ImportError:  # pragma: no cover - exercised only in an incomplete environment
    pika = None  # type: ignore[assignment]
    AMQPError = AMQPConnectionError = Exception


EMAIL_EXCHANGE = "trace.email"
EMAIL_MAIN_QUEUE = "trace.email.send"
EMAIL_DLX = "trace.email.dlx"
EMAIL_DEAD_LETTER_QUEUE = "trace.email.dead-letter"
EMAIL_RETRY_QUEUES = ("trace.email.retry.1", "trace.email.retry.2", "trace.email.retry.3")


class QueueUnavailable(RuntimeError):
    """Raised when RabbitMQ cannot durably accept or process work."""


class QueueMessageInvalid(ValueError):
    """Raised for a message that cannot be safely processed."""


class Channel(Protocol):
    def exchange_declare(self, **kwargs: Any) -> Any: ...
    def queue_declare(self, **kwargs: Any) -> Any: ...
    def queue_bind(self, **kwargs: Any) -> Any: ...
    def confirm_delivery(self) -> Any: ...
    def basic_publish(self, **kwargs: Any) -> bool | None: ...
    def basic_ack(self, delivery_tag: int) -> Any: ...
    def basic_nack(self, delivery_tag: int, requeue: bool) -> Any: ...


@dataclass(frozen=True)
class EmailQueueMessage:
    job_id: UUID
    attempt: int = 0
    version: int = 1

    def encode(self) -> bytes:
        return json.dumps(
            {"job_id": str(self.job_id), "attempt": self.attempt, "version": self.version},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")

    @classmethod
    def decode(cls, body: bytes) -> "EmailQueueMessage":
        try:
            decoded = json.loads(body)
            if set(decoded) != {"attempt", "job_id", "version"}:
                raise ValueError
            job_id = UUID(decoded["job_id"])
            attempt = decoded["attempt"]
            version = decoded["version"]
            if not isinstance(attempt, int) or not 0 <= attempt <= 100:
                raise ValueError
            if version != 1:
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise QueueMessageInvalid("Email queue message is invalid") from error
        return cls(job_id=job_id, attempt=attempt, version=version)


def declare_email_topology(channel: Channel, *, retry_delays_seconds: tuple[int, int, int]) -> None:
    """Declare the fixed, durable topology before publish or consume."""
    if len(retry_delays_seconds) != len(EMAIL_RETRY_QUEUES) or any(delay <= 0 for delay in retry_delays_seconds):
        raise ValueError("Exactly three positive retry delays are required")

    channel.exchange_declare(exchange=EMAIL_EXCHANGE, exchange_type="direct", durable=True)
    channel.exchange_declare(exchange=EMAIL_DLX, exchange_type="direct", durable=True)
    channel.queue_declare(
        queue=EMAIL_MAIN_QUEUE,
        durable=True,
        arguments={"x-dead-letter-exchange": EMAIL_DLX, "x-dead-letter-routing-key": "dead"},
    )
    channel.queue_bind(queue=EMAIL_MAIN_QUEUE, exchange=EMAIL_EXCHANGE, routing_key="send")
    channel.queue_declare(queue=EMAIL_DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(queue=EMAIL_DEAD_LETTER_QUEUE, exchange=EMAIL_DLX, routing_key="dead")
    for retry_queue, delay in zip(EMAIL_RETRY_QUEUES, retry_delays_seconds, strict=True):
        channel.queue_declare(
            queue=retry_queue,
            durable=True,
            arguments={
                "x-message-ttl": delay * 1000,
                "x-dead-letter-exchange": EMAIL_EXCHANGE,
                "x-dead-letter-routing-key": "send",
            },
        )
        channel.queue_bind(queue=retry_queue, exchange=EMAIL_EXCHANGE, routing_key=retry_queue.rsplit(".", 1)[-1])


class RabbitMQEmailPublisher:
    """Publishes only a job UUID after receiving a broker publisher confirmation."""

    def __init__(
        self,
        *,
        url: str,
        retry_delays_seconds: tuple[int, int, int],
        connection_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not url or len(url) > 2048:
            raise ValueError("RabbitMQ URL is invalid")
        self._url = url
        self._retry_delays_seconds = retry_delays_seconds
        self._connection_factory = connection_factory or _open_connection

    def publish(self, message: EmailQueueMessage, *, retry_index: int | None = None) -> None:
        connection = None
        try:
            connection = self._connection_factory(self._url)
            channel = connection.channel()
            declare_email_topology(channel, retry_delays_seconds=self._retry_delays_seconds)
            channel.confirm_delivery()
            routing_key = "send" if retry_index is None else str(retry_index + 1)
            if retry_index is not None and not 0 <= retry_index < len(EMAIL_RETRY_QUEUES):
                raise ValueError("Email retry queue does not exist")
            delivered = channel.basic_publish(
                exchange=EMAIL_EXCHANGE,
                routing_key=routing_key,
                body=message.encode(),
                properties=_persistent_properties(),
                mandatory=True,
            )
            if delivered is False:
                raise QueueUnavailable("RabbitMQ did not confirm delivery")
        except (AMQPError, AMQPConnectionError, OSError) as error:
            raise QueueUnavailable("RabbitMQ is unavailable") from error
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (AMQPError, OSError):
                    pass


def _open_connection(url: str) -> Any:
    if pika is None:
        raise QueueUnavailable("RabbitMQ client is not installed")
    parameters = pika.URLParameters(url)
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 5
    parameters.connection_attempts = 1
    parameters.retry_delay = 0
    return pika.BlockingConnection(parameters)


def _persistent_properties() -> Any:
    if pika is None:
        return {"delivery_mode": 2, "content_type": "application/json"}
    return pika.BasicProperties(delivery_mode=2, content_type="application/json")
