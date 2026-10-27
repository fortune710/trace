from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from db.rls import principal_transaction
from notifications.models import (
    Notification,
    NotificationCategory,
    NotificationEventType,
)
from notifications.service import NotificationService, create_notification

pytestmark = pytest.mark.integration


def _insert_notifications(
    engine,
    *,
    owner_id: UUID,
    count: int,
    read_indexes: set[int] | None = None,
) -> list[UUID]:
    read_indexes = read_indexes or set()
    started_at = datetime(2026, 10, 26, tzinfo=UTC)
    notification_ids = [uuid4() for _ in range(count)]
    with principal_transaction(engine, owner_id) as connection:
        connection.execute(
            sa.insert(Notification),
            [
                {
                    "id": notification_id,
                    "owner_id": owner_id,
                    "category": NotificationCategory.INFO,
                    "event_type": NotificationEventType.REVIEW_QUEUED,
                    "title": f"Notification {index}",
                    "body": "Safe notification body.",
                    "action_path": f"/reviews/{uuid4()}",
                    "data": {},
                    "dedupe_key": f"test:{notification_id}",
                    "created_at": started_at + timedelta(minutes=index),
                    "read_at": (
                        started_at + timedelta(minutes=index)
                        if index in read_indexes
                        else None
                    ),
                }
                for index, notification_id in enumerate(notification_ids)
            ],
        )
    return notification_ids


def test_notifications_list_in_newest_first_pages_with_an_unread_count(
    account_pair,
    integration_engine,
) -> None:
    owner, _ = account_pair
    notification_ids = _insert_notifications(
        integration_engine,
        owner_id=owner.user_id,
        count=3,
        read_indexes={0},
    )

    first_page = owner.request(
        "GET",
        "/api/v1/notifications?page=1&page_size=2",
    )
    second_page = owner.request(
        "GET",
        "/api/v1/notifications?page=2&page_size=2",
    )

    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json()["items"]] == [
        str(notification_ids[2]),
        str(notification_ids[1]),
    ]
    assert first_page.json()["next_offset"] == 2
    assert first_page.json()["unread_count"] == 2
    assert [item["id"] for item in second_page.json()["items"]] == [
        str(notification_ids[0]),
    ]
    assert second_page.json()["next_offset"] is None


def test_notification_reads_are_idempotent_and_require_csrf(
    account_pair,
    integration_engine,
) -> None:
    owner, _ = account_pair
    notification_ids = _insert_notifications(
        integration_engine,
        owner_id=owner.user_id,
        count=2,
    )

    missing_csrf = owner.client.patch(
        f"/api/v1/notifications/{notification_ids[0]}/read",
    )
    first_read = owner.request(
        "PATCH",
        f"/api/v1/notifications/{notification_ids[0]}/read",
    )
    second_read = owner.request(
        "PATCH",
        f"/api/v1/notifications/{notification_ids[0]}/read",
    )
    mark_all = owner.request("PATCH", "/api/v1/notifications/read")
    mark_all_again = owner.request("PATCH", "/api/v1/notifications/read")

    assert missing_csrf.status_code == 403
    assert first_read.json()["changed"] is True
    assert first_read.json()["item"]["read_at"] is not None
    assert second_read.json()["changed"] is False
    assert second_read.json()["item"]["read_at"] == first_read.json()["item"]["read_at"]
    assert mark_all.json()["marked_count"] == 1
    assert mark_all.json()["read_at"] is not None
    assert mark_all_again.json() == {"marked_count": 0, "read_at": None}


def test_notifications_are_private_and_expose_no_public_create_route(
    account_pair,
    integration_app,
    integration_engine,
) -> None:
    owner, other = account_pair
    notification_id = _insert_notifications(
        integration_engine,
        owner_id=owner.user_id,
        count=1,
    )[0]

    unauthenticated = TestClient(integration_app).get("/api/v1/notifications")
    foreign = other.request(
        "PATCH",
        f"/api/v1/notifications/{notification_id}/read",
    )
    public_create = owner.request("POST", "/api/v1/notifications", json={})
    malformed_id = owner.request(
        "PATCH",
        "/api/v1/notifications/not-a-uuid/read",
    )
    malformed_page = owner.request("GET", "/api/v1/notifications?page=0")

    assert unauthenticated.status_code == 401
    assert other.request("GET", "/api/v1/notifications").json()["items"] == []
    assert foreign.status_code == 404
    assert str(owner.user_id) not in foreign.text
    assert str(notification_id) not in foreign.text
    assert public_create.status_code == 405
    assert malformed_id.status_code == 400
    assert malformed_page.status_code == 400


def test_notification_factory_is_deduplicated_and_uses_the_review_action_path(
    account_pair,
    integration_engine,
) -> None:
    owner, _ = account_pair
    review_id = uuid4()

    with principal_transaction(integration_engine, owner.user_id) as connection:
        first = create_notification(
            connection,
            owner_id=owner.user_id,
            event_type=NotificationEventType.FINDINGS_AVAILABLE,
            dedupe_key=f"review:{review_id}:findings_available",
            review_id=review_id,
        )
        duplicate = create_notification(
            connection,
            owner_id=owner.user_id,
            event_type=NotificationEventType.FINDINGS_AVAILABLE,
            dedupe_key=f"review:{review_id}:findings_available",
            review_id=review_id,
        )

    assert first is not None
    assert first["action_path"] == f"/reviews/{review_id}?tab=findings"
    assert first["data"] == {"review_id": str(review_id)}
    assert duplicate is None
    response = owner.request("GET", "/api/v1/notifications")
    assert [item["id"] for item in response.json()["items"]] == [first["id"]]


def test_review_submission_creates_a_durable_queued_notification(
    account_pair,
    agent_factory,
    local_project_factory,
    review_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)

    review = review_factory(owner, project, [UUID(agent["id"])])

    response = owner.request("GET", "/api/v1/notifications")
    queued = next(
        item
        for item in response.json()["items"]
        if item["event_type"] == NotificationEventType.REVIEW_QUEUED.value
    )
    assert queued["action_path"] == f"/reviews/{review['id']}"
    assert queued["data"] == {"review_id": review["id"]}


def test_concurrent_notification_read_operations_change_each_row_once(
    account_pair,
    integration_engine,
) -> None:
    owner, _ = account_pair
    service = NotificationService(integration_engine)
    notification_id = _insert_notifications(
        integration_engine,
        owner_id=owner.user_id,
        count=1,
    )[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: service.mark_read(
                    owner_id=owner.user_id,
                    notification_id=notification_id,
                ),
                range(2),
            )
        )

    assert sorted(changed for _, changed in results) == [False, True]
    timestamps = [item["read_at"] for item, _ in results if item is not None]
    assert timestamps[0] == timestamps[1]


def test_concurrent_mark_all_and_single_read_leave_no_unread_notifications(
    account_pair,
    integration_engine,
) -> None:
    owner, _ = account_pair
    service = NotificationService(integration_engine)
    notification_id, *_ = _insert_notifications(
        integration_engine,
        owner_id=owner.user_id,
        count=2,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        single_read = executor.submit(
            service.mark_read,
            owner_id=owner.user_id,
            notification_id=notification_id,
        )
        mark_all = executor.submit(service.mark_all_read, owner_id=owner.user_id)
        single_read.result()
        mark_all.result()

    items, _, unread_count = service.list(owner_id=owner.user_id, limit=10, offset=0)
    assert unread_count == 0
    assert all(item["read_at"] is not None for item in items)
    assert service.mark_all_read(owner_id=owner.user_id) == (0, None)


def test_concurrent_mark_all_requests_only_mark_each_notification_once(
    account_pair,
    integration_engine,
) -> None:
    owner, _ = account_pair
    service = NotificationService(integration_engine)
    _insert_notifications(
        integration_engine,
        owner_id=owner.user_id,
        count=2,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: service.mark_all_read(owner_id=owner.user_id),
                range(2),
            )
        )

    assert sorted(count for count, _ in results) == [0, 2]
    assert sum(read_at is not None for _, read_at in results) == 1
