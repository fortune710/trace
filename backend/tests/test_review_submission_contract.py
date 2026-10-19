from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from auth.errors import ResourceConflict
from db.types import RepositorySource
from projects.models import Project
from resources.schemas import ReviewCreate
from resources.services import (
    _idempotency_key_digest,
    _resolve_review_source_revision,
    _review_request_digest,
)
from reviews.queueing import ReviewDispatchMessageInvalid, ReviewDispatchMessageV1


def test_review_create_accepts_only_explicit_project_and_agent_selection() -> None:
    agent_id = uuid4()
    request = ReviewCreate(project_id=uuid4(), agent_ids=[agent_id])

    assert request.agent_ids == [agent_id]

    for payload in (
        {"project_id": str(uuid4())},
        {"project_id": str(uuid4()), "agent_ids": []},
        {"project_id": str(uuid4()), "agent_ids": [str(agent_id), str(agent_id)]},
        {"project_id": str(uuid4()), "agent_ids": [str(uuid4()) for _ in range(101)]},
        {
            "project_id": str(uuid4()),
            "agent_ids": [str(agent_id)],
            "source_revision": "client-controlled",
        },
        {
            "project_id": str(uuid4()),
            "agent_ids": [str(agent_id)],
            "selected_categories": ["security"],
        },
    ):
        with pytest.raises(ValidationError):
            ReviewCreate.model_validate(payload)


def test_idempotency_keys_are_validated_and_agent_order_is_semantic() -> None:
    project_id = uuid4()
    first_agent, second_agent = uuid4(), uuid4()

    assert _idempotency_key_digest("submission-123") != b"submission-123"
    assert _review_request_digest(
        project_id=project_id, agent_ids=[first_agent, second_agent]
    ) == _review_request_digest(
        project_id=project_id, agent_ids=[second_agent, first_agent]
    )

    for key in (None, "", " leading", "trailing ", "line\nbreak", "x" * 256):
        with pytest.raises(ValueError):
            _idempotency_key_digest(key)


def test_review_source_is_derived_only_from_canonical_project_values() -> None:
    github = Project(
        source=RepositorySource.GITHUB,
        current_revision="A" * 40,
    )
    local = Project(source=RepositorySource.LOCAL, source_hash=b"x" * 32)

    assert _resolve_review_source_revision(github) == "a" * 40
    assert _resolve_review_source_revision(local) == (b"x" * 32).hex()

    for project in (
        Project(source=RepositorySource.GITHUB, current_revision="main"),
        Project(source=RepositorySource.LOCAL, source_hash=b"short"),
    ):
        with pytest.raises(ResourceConflict):
            _resolve_review_source_revision(project)


def test_review_dispatch_message_is_identifier_only_and_versioned() -> None:
    message = ReviewDispatchMessageV1(
        review_id=uuid4(),
        review_agent_id=uuid4(),
        owner_id=uuid4(),
        idempotency_id=uuid4(),
    )

    encoded = message.encode()
    assert ReviewDispatchMessageV1.decode(encoded) == message
    assert set(json.loads(encoded)) == {
        "idempotency_id",
        "owner_id",
        "review_agent_id",
        "review_id",
        "version",
    }
    with pytest.raises(ReviewDispatchMessageInvalid):
        ReviewDispatchMessageV1.decode(b'{"review_id":"not-a-uuid"}')


@pytest.mark.parametrize(
    "body",
    (
        b"not-json",
        b"[]",
        b'{"version":2,"review_id":"00000000-0000-7000-8000-000000000001","review_agent_id":"00000000-0000-7000-8000-000000000002","owner_id":"00000000-0000-7000-8000-000000000003","idempotency_id":"00000000-0000-7000-8000-000000000004"}',
        b'{"version":1,"review_id":"00000000-0000-7000-8000-000000000001","review_agent_id":"00000000-0000-7000-8000-000000000002","owner_id":"00000000-0000-7000-8000-000000000003"}',
        b'{"version":1,"review_id":"00000000-0000-7000-8000-000000000001","review_agent_id":"00000000-0000-7000-8000-000000000002","owner_id":"00000000-0000-7000-8000-000000000003","idempotency_id":"00000000-0000-7000-8000-000000000004","credentials":"forbidden"}',
        b'{"version":1,"review_id":"not-a-uuid","review_agent_id":"00000000-0000-7000-8000-000000000002","owner_id":"00000000-0000-7000-8000-000000000003","idempotency_id":"00000000-0000-7000-8000-000000000004"}',
    ),
)
def test_review_dispatch_message_rejects_non_allowlisted_payloads(body: bytes) -> None:
    with pytest.raises(ReviewDispatchMessageInvalid):
        ReviewDispatchMessageV1.decode(body)
