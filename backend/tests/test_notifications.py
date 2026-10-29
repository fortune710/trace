import json
from uuid import uuid4

from notifications.models import NotificationCategory, NotificationEventType
from notifications.routes import format_notification_event
from notifications.service import _TEMPLATES
from notifications.stream import NotificationBroker


def test_notification_templates_are_complete_and_safe() -> None:
    assert set(_TEMPLATES) == set(NotificationEventType)
    for template in _TEMPLATES.values():
        assert template.category in set(NotificationCategory)
        assert template.title
        assert template.body
        assert "token" not in template.body.casefold()
        assert "credential" not in template.body.casefold()


def test_review_notifications_use_expected_presentation() -> None:
    assert (
        _TEMPLATES[NotificationEventType.REVIEW_QUEUED].category
        is NotificationCategory.INFO
    )
    assert (
        _TEMPLATES[NotificationEventType.FINDINGS_AVAILABLE].category
        is NotificationCategory.INFO
    )
    assert (
        _TEMPLATES[NotificationEventType.REVIEW_COMPLETED].category
        is NotificationCategory.INFO
    )
    assert (
        _TEMPLATES[NotificationEventType.REVIEW_FAILED].category
        is NotificationCategory.WARNING
    )
    assert (
        _TEMPLATES[NotificationEventType.ISSUE_CREATED].category
        is NotificationCategory.INFO
    )
    assert (
        _TEMPLATES[NotificationEventType.ISSUE_CREATION_FAILED].category
        is NotificationCategory.WARNING
    )
    assert (
        _TEMPLATES[NotificationEventType.PULL_REQUEST_CREATED].category
        is NotificationCategory.INFO
    )
    assert (
        _TEMPLATES[NotificationEventType.PULL_REQUEST_CREATION_FAILED].category
        is NotificationCategory.WARNING
    )


def test_notification_event_frame_uses_the_item_id_and_safe_json_payload() -> None:
    item = {
        "id": str(uuid4()),
        "category": "info",
        "title": "Review queued",
        "body": "Your review has been queued.",
        "action_path": "/reviews/review-1",
    }

    frame = format_notification_event(item)

    lines = frame.splitlines()
    assert lines[0] == f"id: {item['id']}"
    assert lines[1] == "event: notification"
    assert json.loads(lines[2].removeprefix("data: ")) == item


def test_notification_broker_delivers_only_to_the_owner_and_cleans_up() -> None:
    broker = NotificationBroker()
    owner_id = uuid4()
    other_owner_id = uuid4()
    notification_id = uuid4()
    owner_queue = broker.subscribe(owner_id)
    other_queue = broker.subscribe(other_owner_id)

    broker.publish(owner_id, notification_id)

    assert owner_queue.get_nowait() == notification_id
    assert other_queue.empty()
    broker.unsubscribe(owner_id, owner_queue)
    broker.publish(owner_id, uuid4())
    assert owner_queue.empty()


def test_notification_broker_drops_backpressured_delivery(caplog) -> None:
    broker = NotificationBroker()
    owner_id = uuid4()
    queue = broker.subscribe(owner_id)
    for _ in range(queue.maxsize):
        queue.put_nowait(uuid4())

    broker.publish(owner_id, uuid4())

    assert queue.qsize() == queue.maxsize
    assert "notification_subscriber_backpressure" in caplog.text
