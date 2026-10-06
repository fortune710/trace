from __future__ import annotations

from uuid import UUID

from auth.credentials import EncryptedCredential
from auth.email_delivery import (
    EmailJob,
    EmailJobConsumer,
    RetryableEmailDeliveryError,
)
from auth.queueing import (
    EMAIL_DEAD_LETTER_QUEUE,
    EMAIL_MAIN_QUEUE,
    EMAIL_RETRY_QUEUES,
    EmailQueueMessage,
    QueueUnavailable,
    RabbitMQEmailPublisher,
    declare_email_topology,
)
from db.models import EmailDeliveryKind, EmailDeliveryStatus

JOB_ID = UUID("00000000-0000-7000-8000-000000000001")
USER_ID = UUID("00000000-0000-7000-8000-000000000002")


class FakeChannel:
    def __init__(self) -> None:
        self.declarations: list[dict] = []
        self.bindings: list[dict] = []
        self.published: list[dict] = []
        self.acks: list[int] = []
        self.nacks: list[tuple[int, bool]] = []
        self.confirmed = False

    def exchange_declare(self, **kwargs):
        self.declarations.append(kwargs)

    def queue_declare(self, **kwargs):
        self.declarations.append(kwargs)

    def queue_bind(self, **kwargs):
        self.bindings.append(kwargs)

    def confirm_delivery(self):
        self.confirmed = True

    def basic_publish(self, **kwargs):
        self.published.append(kwargs)
        return True

    def basic_ack(self, *, delivery_tag: int):
        self.acks.append(delivery_tag)

    def basic_nack(self, *, delivery_tag: int, requeue: bool):
        self.nacks.append((delivery_tag, requeue))


class FakeConnection:
    def __init__(self, channel: FakeChannel) -> None:
        self._channel = channel
        self.closed = False

    def channel(self) -> FakeChannel:
        return self._channel

    def close(self) -> None:
        self.closed = True


class FakeStore:
    def __init__(self, job: EmailJob) -> None:
        self.job = job
        self.sent: list[UUID] = []
        self.retries: list[tuple[UUID, int]] = []
        self.failed: list[tuple[UUID, str]] = []

    def get(self, job_id: UUID) -> EmailJob | None:
        return self.job if job_id == self.job.id else None

    def mark_sent(self, job_id: UUID) -> bool:
        self.sent.append(job_id)
        self.job = EmailJob(**{**self.job.__dict__, "status": EmailDeliveryStatus.SENT})
        return True

    def schedule_retry(self, job_id: UUID, *, attempt_count: int) -> None:
        self.retries.append((job_id, attempt_count))
        self.job = EmailJob(**{**self.job.__dict__, "attempt_count": attempt_count})

    def mark_failed(self, job_id: UUID, *, reason: str) -> None:
        self.failed.append((job_id, reason))
        self.job = EmailJob(
            **{**self.job.__dict__, "status": EmailDeliveryStatus.FAILED}
        )


class FakeCipher:
    def decrypt_json(self, *_args, **_kwargs):
        return {
            "email": "student@example.test",
            "token": "opaque-token",
            "destination": "https://traceai.vercel.app",
        }


class SuccessfulSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        self.sent.append((recipient, subject, body))


class FailingSender:
    def send(self, **_kwargs) -> None:
        raise RetryableEmailDeliveryError("temporary failure")


class RecordingPublisher:
    def __init__(self, fail: bool = False) -> None:
        self.messages: list[tuple[EmailQueueMessage, int | None]] = []
        self.fail = fail

    def publish(
        self, message: EmailQueueMessage, *, retry_index: int | None = None
    ) -> None:
        if self.fail:
            raise QueueUnavailable("broker unavailable")
        self.messages.append((message, retry_index))


def _job(*, attempt_count: int = 0) -> EmailJob:
    return EmailJob(
        id=JOB_ID,
        user_id=USER_ID,
        kind=EmailDeliveryKind.VERIFICATION,
        status=EmailDeliveryStatus.PENDING,
        encrypted_payload=EncryptedCredential(
            ciphertext=b"ciphertext", nonce=b"nonce", key_version="v1"
        ),
        attempt_count=attempt_count,
    )


def test_publisher_adds_only_a_persistent_job_identifier_to_the_main_queue() -> None:
    channel = FakeChannel()
    connection = FakeConnection(channel)
    publisher = RabbitMQEmailPublisher(
        url="amqp://queue.test",
        retry_delays_seconds=(30, 300, 1800),
        connection_factory=lambda _url: connection,
    )

    publisher.publish(EmailQueueMessage(job_id=JOB_ID))

    assert channel.confirmed
    assert channel.published[0]["routing_key"] == "send"
    assert EmailQueueMessage.decode(channel.published[0]["body"]) == EmailQueueMessage(
        job_id=JOB_ID
    )
    assert connection.closed


def test_topology_defines_the_main_retry_and_dead_letter_queues() -> None:
    channel = FakeChannel()

    declare_email_topology(channel, retry_delays_seconds=(30, 300, 1800))

    queues = {item["queue"] for item in channel.declarations if "queue" in item}
    assert {EMAIL_MAIN_QUEUE, EMAIL_DEAD_LETTER_QUEUE, *EMAIL_RETRY_QUEUES} <= queues


def test_successful_delivery_marks_the_job_sent_and_acknowledges_it() -> None:
    store = FakeStore(_job())
    sender = SuccessfulSender()
    channel = FakeChannel()
    consumer = EmailJobConsumer(
        store=store,
        cipher=FakeCipher(),
        sender=sender,
        publisher=RecordingPublisher(),
        max_retries=3,
    )

    consumer.consume(
        delivery_tag=7, body=EmailQueueMessage(job_id=JOB_ID).encode(), channel=channel
    )

    assert store.sent == [JOB_ID]
    assert channel.acks == [7]
    assert channel.nacks == []
    assert len(sender.sent) == 1


def test_transient_failure_requeues_to_the_next_delay_after_confirming_publish() -> (
    None
):
    store = FakeStore(_job())
    publisher = RecordingPublisher()
    channel = FakeChannel()
    consumer = EmailJobConsumer(
        store=store,
        cipher=FakeCipher(),
        sender=FailingSender(),
        publisher=publisher,
        max_retries=3,
    )

    consumer.consume(
        delivery_tag=8, body=EmailQueueMessage(job_id=JOB_ID).encode(), channel=channel
    )

    assert publisher.messages == [(EmailQueueMessage(job_id=JOB_ID, attempt=1), 0)]
    assert store.retries == [(JOB_ID, 1)]
    assert channel.acks == [8]


def test_exhausted_retries_are_removed_from_work_and_sent_to_the_dead_letter_queue() -> (
    None
):
    store = FakeStore(_job(attempt_count=3))
    channel = FakeChannel()
    consumer = EmailJobConsumer(
        store=store,
        cipher=FakeCipher(),
        sender=FailingSender(),
        publisher=RecordingPublisher(),
        max_retries=3,
    )

    consumer.consume(
        delivery_tag=9,
        body=EmailQueueMessage(job_id=JOB_ID, attempt=3).encode(),
        channel=channel,
    )

    assert store.failed == [(JOB_ID, "retry_limit_exceeded")]
    assert channel.acks == []
    assert channel.nacks == [(9, False)]


def test_broker_failure_returns_the_original_message_to_the_work_queue() -> None:
    store = FakeStore(_job())
    channel = FakeChannel()
    consumer = EmailJobConsumer(
        store=store,
        cipher=FakeCipher(),
        sender=FailingSender(),
        publisher=RecordingPublisher(fail=True),
        max_retries=3,
    )

    consumer.consume(
        delivery_tag=10, body=EmailQueueMessage(job_id=JOB_ID).encode(), channel=channel
    )

    assert store.retries == []
    assert channel.acks == []
    assert channel.nacks == [(10, True)]
