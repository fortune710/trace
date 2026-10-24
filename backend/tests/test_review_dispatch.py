from __future__ import annotations

import json
import logging
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import Body, FastAPI, Request
from fastapi.testclient import TestClient

from audit.emit import enqueue_audit
from auth.errors import install_auth_error_handlers
from resources.routes import _audit as audit_resource_operation
from reviews.config import ReviewDispatchSettings
from reviews.dispatch import (
    REVIEW_DISPATCH_EXCHANGE,
    REVIEW_DISPATCH_QUEUE,
    REVIEW_DISPATCH_ROUTING_KEY,
    REVIEW_EXECUTION_DEAD_LETTER_QUEUE,
    REVIEW_EXECUTION_DLX,
    RabbitMQReviewPublisher,
    ReviewDispatchWorker,
    ReviewQueueUnavailable,
    _Claim,
    declare_review_dispatch_topology,
)
from reviews.queueing import ReviewDispatchMessageV1

REVIEW_ID = UUID("00000000-0000-7000-8000-000000000001")
ASSIGNMENT_ID = UUID("00000000-0000-7000-8000-000000000002")
OWNER_ID = UUID("00000000-0000-7000-8000-000000000003")
IDEMPOTENCY_ID = UUID("00000000-0000-7000-8000-000000000004")


class FakeChannel:
    def __init__(self, *, delivered: bool | None = True) -> None:
        self.declarations: list[dict[str, object]] = []
        self.bindings: list[dict[str, object]] = []
        self.published: list[dict[str, object]] = []
        self.confirmed = False
        self._delivered = delivered

    def exchange_declare(self, **kwargs: object) -> None:
        self.declarations.append(kwargs)

    def queue_declare(self, **kwargs: object) -> None:
        self.declarations.append(kwargs)

    def queue_bind(self, **kwargs: object) -> None:
        self.bindings.append(kwargs)

    def confirm_delivery(self) -> None:
        self.confirmed = True

    def basic_publish(self, **kwargs: object) -> bool | None:
        self.published.append(kwargs)
        return self._delivered


class FakeConnection:
    def __init__(self, channel: FakeChannel) -> None:
        self._channel = channel
        self.closed = False

    def channel(self) -> FakeChannel:
        return self._channel

    def close(self) -> None:
        self.closed = True


class RecordingAuditRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def create_event(self, **kwargs: object) -> None:
        self.events.append(kwargs)


def _message() -> ReviewDispatchMessageV1:
    return ReviewDispatchMessageV1(
        review_id=REVIEW_ID,
        review_agent_id=ASSIGNMENT_ID,
        owner_id=OWNER_ID,
        idempotency_id=IDEMPOTENCY_ID,
    )


def test_review_dispatch_publisher_uses_confirmed_persistent_identifier_only_message() -> (
    None
):
    channel = FakeChannel()
    connection = FakeConnection(channel)
    publisher = RabbitMQReviewPublisher(
        url="amqp://queue.test",
        connection_factory=lambda _url: connection,
    )

    publisher.publish(_message())

    assert channel.confirmed
    assert channel.published[0]["exchange"] == REVIEW_DISPATCH_EXCHANGE
    assert channel.published[0]["routing_key"] == REVIEW_DISPATCH_ROUTING_KEY
    assert channel.published[0]["mandatory"] is True
    assert ReviewDispatchMessageV1.decode(channel.published[0]["body"]) == _message()
    assert connection.closed


def test_review_dispatch_topology_is_durable_and_versioned() -> None:
    channel = FakeChannel()

    declare_review_dispatch_topology(channel)

    assert {item.get("exchange") for item in channel.declarations} == {
        REVIEW_DISPATCH_EXCHANGE,
        REVIEW_EXECUTION_DLX,
        None,
    }
    assert channel.declarations[2] == {
        "queue": REVIEW_DISPATCH_QUEUE,
        "durable": True,
        "arguments": {"x-dead-letter-exchange": REVIEW_EXECUTION_DLX},
    }
    assert channel.bindings == [
        {
            "queue": REVIEW_EXECUTION_DEAD_LETTER_QUEUE,
            "exchange": REVIEW_EXECUTION_DLX,
            "routing_key": "",
        },
        {
            "queue": REVIEW_DISPATCH_QUEUE,
            "exchange": REVIEW_DISPATCH_EXCHANGE,
            "routing_key": REVIEW_DISPATCH_ROUTING_KEY,
        },
    ]


def test_review_dispatch_publisher_rejects_unconfirmed_delivery() -> None:
    channel = FakeChannel(delivered=False)
    publisher = RabbitMQReviewPublisher(
        url="amqp://queue.test",
        connection_factory=lambda _url: FakeConnection(channel),
    )

    with pytest.raises(ReviewQueueUnavailable):
        publisher.publish(_message())


def test_review_dispatch_settings_reject_invalid_runtime_configuration() -> None:
    with pytest.raises(RuntimeError):
        ReviewDispatchSettings().validate_for_dispatch()

    with pytest.raises(RuntimeError):
        ReviewDispatchSettings(
            rabbitmq_url="amqp://queue.test",
            retry_base_seconds=10,
            retry_max_seconds=5,
        ).validate_for_dispatch()


def _request(path: str, *, owner_id: UUID) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": path,
            "headers": [],
        }
    )
    request.state.request_id = "review-request-1"
    request.state.principal_user_id = owner_id
    return request


def _assert_review_audit_payload_is_safe(value: object) -> None:
    encoded = json.dumps(value, default=str, sort_keys=True)
    for forbidden in (
        "raw-review-key",
        "provider-token",
        "/private/repository",
        "source-contents",
        "broker failure details",
    ):
        assert forbidden not in encoded


def test_review_resource_audit_events_are_allowlisted_for_submission_and_cancellation() -> (
    None
):
    recorder = RecordingAuditRecorder()
    request = _request("/api/v1/reviews", owner_id=OWNER_ID)

    audit_resource_operation(
        request,
        hasher=None,
        recorder=cast(Any, recorder),
        event="review",
        reason="queued",
        status_code=202,
    )
    audit_resource_operation(
        request,
        hasher=None,
        recorder=cast(Any, recorder),
        event="review",
        reason="cancelled",
    )

    assert recorder.events == [
        {
            "event_type": "resource.review.queued",
            "request_id": "review-request-1",
            "owner_id": OWNER_ID,
            "fields": {
                "resource": "review",
                "operation": "queued",
                "route": "/api/v1/reviews",
                "status_code": "202",
            },
        },
        {
            "event_type": "resource.review.cancelled",
            "request_id": "review-request-1",
            "owner_id": OWNER_ID,
            "fields": {
                "resource": "review",
                "operation": "cancelled",
                "route": "/api/v1/reviews",
                "status_code": "200",
            },
        },
    ]
    _assert_review_audit_payload_is_safe(recorder.events)


def test_review_submission_rejection_audit_is_allowlisted() -> None:
    recorder = RecordingAuditRecorder()
    app = FastAPI()
    install_auth_error_handlers(app, audit_recorder=cast(Any, recorder))

    @app.post("/api/v1/reviews")
    def create_review(payload: int = Body()) -> dict[str, int]:
        return {"payload": payload}

    response = TestClient(app).post(
        "/api/v1/reviews",
        json={
            "source_revision": "source-contents",
            "idempotency_key": "raw-review-key",
        },
    )

    assert response.status_code == 422
    assert recorder.events == [
        {
            "event_type": "review.submission.rejected",
            "request_id": recorder.events[0]["request_id"],
            "owner_id": None,
            "fields": {
                "outcome": "rejected",
                "reason": "invalid_input",
                "route": "/api/v1/reviews",
                "status_code": "422",
                "resource": "review",
            },
        }
    ]
    _assert_review_audit_payload_is_safe([response.json(), recorder.events])


def test_review_dispatch_audit_events_contain_only_allowlisted_operational_data() -> (
    None
):
    recorder = RecordingAuditRecorder()
    worker = ReviewDispatchWorker(
        engine=cast(Any, object()),
        publisher=cast(Any, object()),
        audit_recorder=cast(Any, recorder),
    )
    claim = _Claim(
        idempotency_id=IDEMPOTENCY_ID,
        owner_id=OWNER_ID,
        review_id=REVIEW_ID,
        review_agent_id=ASSIGNMENT_ID,
        attempt_count=2,
    )

    for event_type, fields in (
        ("review.dispatch.published", {}),
        (
            "review.dispatch.retry_scheduled",
            {"delay_seconds": "5", "failure_code": "broker_unavailable"},
        ),
        ("review.dispatch.dead_letter", {"failure_code": "publish_exhausted"}),
        ("review.dispatch.cancelled", {"failure_code": "review_cancelled"}),
    ):
        worker._audit(event_type, claim, fields)

    assert recorder.events == [
        {
            "event_type": "review.dispatch.published",
            "request_id": f"review-dispatch:{IDEMPOTENCY_ID}",
            "owner_id": OWNER_ID,
            "fields": {
                "review_id": str(REVIEW_ID),
                "review_agent_id": str(ASSIGNMENT_ID),
                "attempt_count": "2",
            },
        },
        {
            "event_type": "review.dispatch.retry_scheduled",
            "request_id": f"review-dispatch:{IDEMPOTENCY_ID}",
            "owner_id": OWNER_ID,
            "fields": {
                "review_id": str(REVIEW_ID),
                "review_agent_id": str(ASSIGNMENT_ID),
                "attempt_count": "2",
                "delay_seconds": "5",
                "failure_code": "broker_unavailable",
            },
        },
        {
            "event_type": "review.dispatch.dead_letter",
            "request_id": f"review-dispatch:{IDEMPOTENCY_ID}",
            "owner_id": OWNER_ID,
            "fields": {
                "review_id": str(REVIEW_ID),
                "review_agent_id": str(ASSIGNMENT_ID),
                "attempt_count": "2",
                "failure_code": "publish_exhausted",
            },
        },
        {
            "event_type": "review.dispatch.cancelled",
            "request_id": f"review-dispatch:{IDEMPOTENCY_ID}",
            "owner_id": OWNER_ID,
            "fields": {
                "review_id": str(REVIEW_ID),
                "review_agent_id": str(ASSIGNMENT_ID),
                "attempt_count": "2",
                "failure_code": "review_cancelled",
            },
        },
    ]
    _assert_review_audit_payload_is_safe(recorder.events)


def test_review_audit_enqueue_failure_never_logs_dispatch_details(caplog) -> None:
    class FailingRecorder:
        def create_event(self, **_: object) -> None:
            raise RuntimeError("broker failure details raw-review-key")

    caplog.set_level(logging.ERROR, logger="trace.audit")
    enqueue_audit(
        cast(Any, FailingRecorder()),
        event_type="review.dispatch.dead_letter",
        request_id=f"review-dispatch:{IDEMPOTENCY_ID}",
        owner_id=OWNER_ID,
        fields={"failure_code": "publish_exhausted"},
    )

    assert "audit_enqueue_failed" in caplog.text
    _assert_review_audit_payload_is_safe(caplog.text)
