from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from auth.errors import ResourceConflict
from db.types import RepositorySource
from projects.models import Project
from resources.schemas import ReviewCreate
from resources.services import (
    _idempotency_key_digest,
    _local_source_identity_hash,
    _resolve_github_review_snapshot,
    _resolve_local_review_snapshot,
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


def test_local_review_snapshot_requires_a_supported_lowercase_digest_and_identity() -> (
    None
):
    source_id = uuid4()
    project = Project(
        source=RepositorySource.LOCAL,
        local_path_hash=_local_source_identity_hash(source_id),
    )
    valid = {
        "source_id": source_id,
        "integrity_algorithm": "sha256-directory-manifest-v1",
        "digest": "a" * 64,
    }

    assert _resolve_local_review_snapshot(project, valid) == (
        RepositorySource.LOCAL,
        str(source_id),
        "sha256-directory-manifest-v1",
        "a" * 64,
    )

    for invalid in (
        None,
        {**valid, "integrity_algorithm": "sha512-directory-manifest-v1"},
        {**valid, "digest": "A" * 64},
        {**valid, "digest": "a" * 63},
        {**valid, "source_id": uuid4()},
    ):
        with pytest.raises(ResourceConflict):
            _resolve_local_review_snapshot(project, invalid)


def test_github_snapshot_reresolves_the_branch_for_each_new_review() -> None:
    project = Project(
        source=RepositorySource.GITHUB,
        external_repository_id="123",
        branch_name="main",
        current_revision="a" * 40,
    )

    class RepositoryResolver:
        def __init__(self) -> None:
            self.revisions = iter(("b" * 40, "c" * 40))
            self.calls = 0

        def resolve_branch(self, **_kwargs: object):
            self.calls += 1
            return SimpleNamespace(), SimpleNamespace(commit_sha=next(self.revisions))

    resolver = RepositoryResolver()

    first = _resolve_github_review_snapshot(project, resolver, uuid4())
    second = _resolve_github_review_snapshot(project, resolver, uuid4())

    assert first == (RepositorySource.GITHUB, "123", "git-commit-sha1-v1", "b" * 40)
    assert second == (RepositorySource.GITHUB, "123", "git-commit-sha1-v1", "c" * 40)
    assert resolver.calls == 2


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
