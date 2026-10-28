from types import SimpleNamespace
from uuid import uuid4

import sqlalchemy as sa

from auth.errors import ProviderUnavailable, ResourceConflict
from remediations.queueing import RemediationPullRequestMessageV1
from workers.remediation_pull_request_execution import handle_delivery


class _Channel:
    def __init__(self) -> None:
        self.actions: list[tuple[str, bool | None]] = []

    def basic_ack(self, *, delivery_tag: int) -> None:
        assert delivery_tag == 17
        self.actions.append(("ack", None))

    def basic_nack(self, *, delivery_tag: int, requeue: bool) -> None:
        assert delivery_tag == 17
        self.actions.append(("nack", requeue))

    def basic_reject(self, *, delivery_tag: int, requeue: bool) -> None:
        assert delivery_tag == 17
        self.actions.append(("reject", requeue))


class _Service:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.publish_calls: list[dict[str, object]] = []
        self.retry_calls: list[dict[str, object]] = []

    def publish_queued(self, **kwargs: object) -> dict[str, object]:
        self.publish_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {}

    def enqueue_retry(self, **kwargs: object) -> dict[str, object]:
        self.retry_calls.append(kwargs)
        return {}


def _message() -> RemediationPullRequestMessageV1:
    return RemediationPullRequestMessageV1(
        owner_id=uuid4(), remediation_id=uuid4(), idempotency_id=uuid4()
    )


def test_pr_queue_consumer_rejects_malformed_messages_without_requeueing() -> None:
    channel = _Channel()

    handle_delivery(
        channel,
        SimpleNamespace(delivery_tag=17),
        b'{"prompt_text":"never accepted"}',
        service=_Service(),  # type: ignore[arg-type]
    )

    assert channel.actions == [("reject", False)]


def test_pr_queue_consumer_acknowledges_success_and_durable_provider_retry() -> None:
    message = _message()
    success = _Service()
    success_channel = _Channel()
    handle_delivery(
        success_channel,
        SimpleNamespace(delivery_tag=17),
        message.encode(),
        service=success,  # type: ignore[arg-type]
    )
    assert success_channel.actions == [("ack", None)]
    assert success.publish_calls[0]["owner_id"] == message.owner_id
    assert success.publish_calls[0]["remediation_id"] == message.remediation_id

    retry = _Service(ProviderUnavailable())
    retry_channel = _Channel()
    handle_delivery(
        retry_channel,
        SimpleNamespace(delivery_tag=17),
        message.encode(),
        service=retry,  # type: ignore[arg-type]
    )
    assert retry_channel.actions == [("ack", None)]
    assert retry.retry_calls == retry.publish_calls


def test_pr_queue_consumer_acknowledges_terminal_work_and_redelivers_database_errors() -> (
    None
):
    message = _message()
    terminal_channel = _Channel()
    handle_delivery(
        terminal_channel,
        SimpleNamespace(delivery_tag=17),
        message.encode(),
        service=_Service(ResourceConflict()),  # type: ignore[arg-type]
    )
    assert terminal_channel.actions == [("ack", None)]

    recovery_channel = _Channel()
    handle_delivery(
        recovery_channel,
        SimpleNamespace(delivery_tag=17),
        message.encode(),
        service=_Service(sa.exc.SQLAlchemyError("database unavailable")),  # type: ignore[arg-type]
    )
    assert recovery_channel.actions == [("nack", True)]
