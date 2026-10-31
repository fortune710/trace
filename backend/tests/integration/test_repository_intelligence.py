"""Revision binding, encrypted local upload, and owner isolation."""

import base64
import hashlib
import json
import os
from uuid import UUID

import pytest
import sqlalchemy as sa

from auth.credentials import credential_cipher_from_settings
from db.rls import principal_transaction
from repository_intelligence import models
from repository_intelligence.local_source import LocalReviewSourceAccess
from repository_intelligence.service import select_agent_surfaces
from repository_intelligence.worker import IntelligenceWorker
from reviews.models import Review

pytestmark = pytest.mark.integration


def _digest(path: str, content: bytes) -> str:
    digest = hashlib.sha256(b"trace-local-source-snapshot\0v1\0")
    digest.update(b"F")
    digest.update(len(path.encode()).to_bytes(8, "big"))
    digest.update(path.encode())
    digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def test_local_upload_is_encrypted_revision_bound_and_owner_scoped(
    account_pair,
    local_project_factory,
    agent_factory,
    integration_engine,
    integration_settings,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    content = b"export function POST() { return eval(input); }\n"
    revision = _digest("route.ts", content)
    response = owner.request(
        "POST",
        "/api/v1/reviews",
        headers={"Idempotency-Key": "intelligence-local-upload"},
        json={
            "project_id": project["id"],
            "agent_ids": [agent["id"]],
            "local_source_snapshot": {
                "source_id": project["_local_source_id"],
                "integrity_algorithm": "sha256-directory-manifest-v1",
                "digest": revision,
            },
            "local_source_upload": {
                "digest": revision,
                "entries": [
                    {
                        "path": "route.ts",
                        "directory": False,
                        "content_base64": base64.b64encode(content).decode(),
                    }
                ],
            },
        },
    )
    assert response.status_code == 202, response.text
    review_id = UUID(response.json()["id"])
    reused = owner.request(
        "POST",
        "/api/v1/reviews",
        headers={"Idempotency-Key": "intelligence-local-upload-second"},
        json=json.loads(response.request.content),
    )
    assert reused.status_code == 202, reused.text
    reader = LocalReviewSourceAccess.open(
        engine=integration_engine,
        owner_id=owner.user_id,
        review_id=review_id,
        revision=revision,
        cipher=credential_cipher_from_settings(integration_settings),
    )
    assert reader.read_file(path="route.ts", log_context=None) == content.decode()
    with pytest.raises(ValueError, match="local_source_snapshot_unavailable"):
        LocalReviewSourceAccess.open(
            engine=integration_engine,
            owner_id=owner.user_id,
            review_id=review_id,
            revision="0" * 64,
            cipher=credential_cipher_from_settings(integration_settings),
        )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        snapshot_id = connection.execute(
            sa.select(Review.intelligence_snapshot_id).where(Review.id == review_id)
        ).scalar_one()
        assert snapshot_id is not None
        second_snapshot_id = connection.execute(
            sa.select(Review.intelligence_snapshot_id).where(
                Review.id == UUID(reused.json()["id"])
            )
        ).scalar_one()
        assert second_snapshot_id == snapshot_id
        snapshot = (
            connection.execute(
                sa.select(models.snapshot).where(models.snapshot.c.id == snapshot_id)
            )
            .mappings()
            .one()
        )
        assert snapshot["source_revision"] == revision
        assert snapshot["status"] == "ready"
        surfaces = select_agent_surfaces(
            connection,
            owner_id=owner.user_id,
            snapshot_id=snapshot_id,
            specialty="security",
            project_category="productivity",
        )
        assert len(surfaces) == 1
        assert "route.ts" in surfaces[0]
        blob = (
            connection.execute(
                sa.select(models.local_source).where(
                    models.local_source.c.review_id == review_id
                )
            )
            .mappings()
            .one()
        )
        assert content not in blob["ciphertext"]
    with (
        pytest.raises(sa.exc.DBAPIError),
        principal_transaction(integration_engine, owner.user_id) as connection,
    ):
        connection.execute(
            sa.update(Review)
            .where(Review.id == review_id)
            .values(intelligence_snapshot_id=None)
        )
    with principal_transaction(integration_engine, other.user_id) as connection:
        assert (
            connection.execute(
                sa.select(models.local_source).where(
                    models.local_source.c.review_id == review_id
                )
            ).first()
            is None
        )


def test_github_worker_analyzes_pinned_commit_without_a_model(
    account_pair,
    credential_factory,
    external_repository_factory,
    github_stub,
    integration_engine,
) -> None:
    owner, _ = account_pair
    credential = credential_factory(owner, access_token="intelligence-token")
    external_repository_factory(owner, credential["id"])
    github_stub.repositories_by_token["intelligence-token"] = [
        {
            "id": 771234,
            "owner": {"login": "example"},
            "name": "repo",
            "full_name": "example/repo",
            "private": True,
            "visibility": "private",
            "default_branch": "main",
            "html_url": "https://github.com/example/repo",
        }
    ]
    revision = "b" * 40
    github_stub.branches_by_repository["771234"] = [
        {
            "name": "main",
            "commit": {"sha": revision},
            "protected": False,
        }
    ]
    created = owner.request(
        "POST",
        "/api/v1/projects",
        json={
            "name": "intelligence-project",
            "source": "github",
            "repository_id": "771234",
            "branch_name": "main",
            "category": "business",
        },
    )
    assert created.status_code == 201, created.text

    class FakeReader:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_paths(self, **_kwargs):
            return ["app/api/route.ts"], False, 0

        def read_file(self, **_kwargs):
            return "export function POST() { eval(input); }"

    class FakeRepositoryService:
        calls = 0

        def open_review_github_source_access(self, **kwargs):
            assert kwargs["revision"] == revision
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary source outage")
            return FakeReader()

    internal_url = sa.engine.make_url(os.environ["MIGRATION_DATABASE_URL"]).set(
        username="trace_internal",
        password=os.environ["TRACE_INTERNAL_PASSWORD"],
    )
    internal_engine = sa.create_engine(internal_url)
    try:
        worker = IntelligenceWorker(internal_engine, FakeRepositoryService())
        assert worker.run_once()
        with principal_transaction(integration_engine, owner.user_id) as connection:
            status = connection.execute(
                sa.select(models.snapshot.c.status).where(
                    models.snapshot.c.project_id == UUID(created.json()["id"])
                )
            ).scalar_one()
            assert status == "pending"
        assert worker.run_once()
    finally:
        internal_engine.dispose()
    with principal_transaction(integration_engine, owner.user_id) as connection:
        snapshot = (
            connection.execute(
                sa.select(models.snapshot).where(
                    models.snapshot.c.project_id == UUID(created.json()["id"])
                )
            )
            .mappings()
            .one()
        )
        assert snapshot["status"] == "ready"
        assert snapshot["source_revision"] == revision
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(models.rule_hit)
                .where(models.rule_hit.c.snapshot_id == snapshot["id"])
            ).scalar_one()
            == 1
        )
