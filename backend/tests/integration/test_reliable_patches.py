"""Durable findings, exact encrypted artifacts, and protected executable reads."""

from types import SimpleNamespace
from uuid import UUID

import pytest
import sqlalchemy as sa

from agents.execution.agent import ReviewFindingOutput
from agents.execution.executor import ReviewExecutionService
from agents.execution.patches import build_patch
from artifacts.models import LocalFileBackup
from auth.credentials import (
    CredentialDecryptionError,
    CredentialEncryptionUnavailable,
    credential_cipher_from_settings,
)
from auth.errors import ResourceConflict, ResourceUnavailable
from db.rls import principal_transaction
from findings.models import Finding, FindingStatus
from notifications.models import Notification, NotificationEventType
from remediations.models import Remediation
from remediations.patch_models import patch_artifacts
from remediations.patch_store import PatchStore
from remediations.service import LocalRemediationApplyService
from reviews.models import Review, ReviewAgent

pytestmark = pytest.mark.integration


def test_encrypted_patch_preview_and_owner_endpoint(
    account_pair,
    local_project_factory,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    integration_settings,
):
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, UUID(project["id"]), UUID(agent["id"]))
    store = PatchStore(
        integration_engine, credential_cipher_from_settings(integration_settings)
    )
    secret = "sk-" + "A" * 24
    patch = build_patch(
        original={"app.py": f'token="{secret}"\nallow=True\n'},
        updated={"app.py": f'token="{secret}"\nallow=False\n'},
        snapshot={
            "source_kind": "local",
            "source_identifier": "integration-local-source",
            "revision": "a" * 64,
        },
    )
    store.save(
        owner_id=owner.user_id, remediation_id=graph["remediation_id"], patch=patch
    )
    path = f"/api/v1/remediations/{graph['remediation_id']}/patch"
    assert owner.request("GET", path).status_code == 409
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == graph["finding_id"])
            .values(status=FindingStatus.ACCEPTED)
        )
        row = (
            connection.execute(
                sa.select(Remediation).where(Remediation.id == graph["remediation_id"])
            )
            .mappings()
            .one()
        )
        assert secret not in row["proposed_diff"]
        artifact = connection.execute(sa.select(patch_artifacts)).mappings().one()
        assert secret.encode() not in artifact["ciphertext"]
    response = owner.request("GET", path)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["diff"] == patch.diff
    assert response.json()["sha256"] == patch.sha256
    assert other.request("GET", path).status_code in (403, 404)
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Review)
            .where(Review.id == graph["review_id"])
            .values(status="running")
        )
    assert owner.request("GET", path).status_code == 409
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Review)
            .where(Review.id == graph["review_id"])
            .values(status="completed")
        )
    with principal_transaction(integration_engine, other.user_id) as connection:
        assert connection.execute(sa.select(patch_artifacts)).first() is None
    with pytest.raises(ResourceConflict):
        store.load(owner_id=other.user_id, remediation_id=graph["remediation_id"])
    # A replay cannot replace a ready artifact.
    replacement = build_patch(
        original={"app.py": "old\n"},
        updated={"app.py": "different\n"},
        snapshot=patch.source_snapshot,
    )
    store.save(
        owner_id=owner.user_id,
        remediation_id=graph["remediation_id"],
        patch=replacement,
    )
    assert (
        store.load(owner_id=owner.user_id, remediation_id=graph["remediation_id"]).diff
        == patch.diff
    )
    with (
        principal_transaction(integration_engine, owner.user_id) as connection,
        pytest.raises(sa.exc.DBAPIError),
        connection.begin_nested(),
    ):
        connection.execute(
            sa.update(Remediation)
            .where(Remediation.id == graph["remediation_id"])
            .values(proposed_diff="mutated")
        )
    store._cipher = SimpleNamespace(
        decrypt_json=lambda *args, **kwargs: {**patch.model_dump(), "diff": "tampered"}
    )
    with pytest.raises(ResourceConflict):
        store.load(owner_id=owner.user_id, remediation_id=graph["remediation_id"])
    metadata = owner.request(
        "GET", f"/api/v1/remediations/{graph['remediation_id']}"
    ).json()
    assert metadata["patch_available"] is False
    assert (
        metadata["generation_failure"]["code"] == "patch_decryption_or_integrity_failed"
    )


def test_staged_findings_survive_failure_and_replay(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
    integration_engine,
    integration_settings,
):
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    other_agent = agent_factory(owner, name="second-reviewer")
    review = review_factory(
        owner, project, [UUID(agent["id"]), UUID(other_agent["id"])]
    )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        assignment = (
            connection.execute(
                sa.select(ReviewAgent).where(
                    ReviewAgent.review_id == UUID(review["id"]),
                    ReviewAgent.agent_id == UUID(agent["id"]),
                )
            )
            .mappings()
            .one()
        )
    service = object.__new__(ReviewExecutionService)
    service._engine = integration_engine
    findings = [
        ReviewFindingOutput(
            severity="high",
            title=f"Risk {index}",
            explanation="Repository evidence",
            prompt_text="Fix it",
        )
        for index in range(2)
    ]
    args = {
        "owner_id": owner.user_id,
        "review": SimpleNamespace(
            id=UUID(review["id"]), project_id=UUID(project["id"])
        ),
        "review_agent": SimpleNamespace(
            agent_id=UUID(agent["id"]),
            id=assignment["id"],
            agent_specialization="security",
        ),
        "findings": findings,
    }
    staged = service._stage_findings(**args)
    assert len(staged) == 2
    store = PatchStore(
        integration_engine, credential_cipher_from_settings(integration_settings)
    )
    store.fail(
        owner_id=owner.user_id,
        remediation_id=staged[0][1],
        diagnostic={"code": "invalid_line_range", "message": "Invalid line range"},
    )
    # Only work interrupted before completion is retried on delivery replay.
    assert [item[1] for item in service._stage_findings(**args)] == [staged[1][1]]
    store.start(owner_id=owner.user_id, remediation_id=staged[1][1])
    assert [item[1] for item in service._stage_findings(**args)] == [staged[1][1]]
    store.fail(
        owner_id=owner.user_id,
        remediation_id=staged[1][1],
        diagnostic={"code": "invalid_line_range", "message": "Invalid line range"},
    )
    assert service._stage_findings(**args) == []
    other_args = {
        **args,
        "review_agent": SimpleNamespace(
            agent_id=UUID(other_agent["id"]),
            id=UUID(other_agent["id"]),
            agent_specialization="security",
        ),
        "findings": [findings[0]],
    }
    assert len(service._stage_findings(**other_args)) == 1
    with principal_transaction(integration_engine, owner.user_id) as connection:
        # Findings are visible before patches exist, announced once per review.
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(Notification)
                .where(
                    Notification.event_type == NotificationEventType.FINDINGS_AVAILABLE
                )
            ).scalar_one()
            == 1
        )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(Finding)
                .where(Finding.review_id == UUID(review["id"]))
            ).scalar_one()
            == 3
        )
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(Remediation)
                .where(Remediation.generation_status == "failed")
            ).scalar_one()
            == 2
        )


def test_review_completes_with_a_failed_patch_and_keeps_later_success(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
    integration_engine,
    integration_settings,
    monkeypatch,
):
    from agents.execution.agent import ReviewFindingBatch, ReviewTarget
    from agents.execution.diagnostics import PatchGenerationError
    from agents.execution.executor import SelectedAgentExecution
    from agents.execution.tools import ToolExecutionContext
    from repository_intelligence.local_source import LocalReviewSourceAccess

    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    response = review_factory(owner, project, [UUID(agent["id"])])
    review_id = UUID(response["id"])
    with principal_transaction(integration_engine, owner.user_id) as connection:
        assignment = SimpleNamespace(
            **connection.execute(
                sa.select(ReviewAgent).where(ReviewAgent.review_id == review_id)
            )
            .mappings()
            .one()
        )
        review = SimpleNamespace(
            **connection.execute(sa.select(Review).where(Review.id == review_id))
            .mappings()
            .one()
        )
    service = object.__new__(ReviewExecutionService)
    service._engine = integration_engine
    service._patch_store = PatchStore(
        integration_engine, credential_cipher_from_settings(integration_settings)
    )
    findings = [
        ReviewFindingOutput(
            severity="high",
            title=f"Risk {index}",
            explanation="Read repository evidence",
            prompt_text="Fix it",
        )
        for index in range(2)
    ]
    service._orchestrator = SimpleNamespace(
        run=lambda **kwargs: [ReviewFindingBatch(findings=findings)]
    )
    service._build_runtime_agent = lambda **kwargs: SimpleNamespace(
        provider="openai", model="fixture", api_key="unused-fixture"
    )

    def generate(self, *, finding, on_submission, **kwargs):
        with principal_transaction(integration_engine, owner.user_id) as connection:
            assert (
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(Finding)
                    .where(Finding.review_id == review_id)
                ).scalar_one()
                == 2
            )
        failed = finding.title == "Risk 0"
        diagnostic = (
            {
                "stage": "edit",
                "code": "invalid_line_range",
                "message": "Invalid line range",
                "retryable": True,
            }
            if failed
            else None
        )
        on_submission(
            submission_number=1,
            diagnostic=diagnostic,
            elapsed_ms=1,
            source_read_count=1,
            model_call_count=1,
        )
        if failed:
            raise PatchGenerationError("invalid_line_range")
        return build_patch(
            original={"app.py": "old\n"},
            updated={"app.py": "new\n"},
            snapshot={
                "source_kind": "local",
                "source_identifier": review.source_identifier,
                "revision": review.source_revision,
            },
        )

    monkeypatch.setattr("agents.execution.executor.DiffAgent.run", generate)
    service._execute_selected_agent(
        owner_id=owner.user_id,
        review=review,
        selected_agent=SelectedAgentExecution(
            review_agent=assignment, credential_snapshot=None
        ),
        review_target=ReviewTarget(
            "local", review.source_identifier, review.source_revision
        ),
        tool_context=ToolExecutionContext(
            owner_id=owner.user_id,
            source_kind="local",
            source_identifier=review.source_identifier,
            source_revision=review.source_revision,
            repository_access=LocalReviewSourceAccess({"app.py": b"old\n"}),
            review_id=review_id,
        ),
        dispatch_id=review_id,
    )
    service._finalize_review_status(owner_id=owner.user_id, review_id=review_id)
    result = owner.request("GET", f"/api/v1/reviews/{review_id}")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    with principal_transaction(integration_engine, owner.user_id) as connection:
        diagnostics = connection.execute(
            sa.select(Remediation.generation_status, Remediation.generation_failure)
            .join(Finding, Finding.id == Remediation.finding_id)
            .where(Finding.review_id == review_id)
        ).all()
    assert result.json()["remediation_generation_failed_count"] == 1, diagnostics
    assert result.json()["warnings"] == ["remediation_generation_incomplete"]
    with principal_transaction(integration_engine, owner.user_id) as connection:
        states = (
            connection.execute(
                sa.select(Remediation.generation_status)
                .join(Finding, Finding.id == Remediation.finding_id)
                .where(Finding.review_id == review_id)
            )
            .scalars()
            .all()
        )
    assert sorted(states) == ["failed", "ready"]


def test_legacy_patch_maintenance_command_validates_before_encrypting(
    account_pair,
    local_project_factory,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    integration_settings,
    monkeypatch,
    capsys,
):
    import json
    import sys

    from remediations import migrate_patches
    from repository_intelligence.local_source import LocalReviewSourceAccess

    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    valid_graph = artifact_graph_factory(owner, UUID(project["id"]), UUID(agent["id"]))
    invalid_graph = artifact_graph_factory(
        owner, UUID(project["id"]), UUID(agent["id"])
    )
    legacy = build_patch(
        original={"app.py": "old\n"}, updated={"app.py": "new\n"}, snapshot={}
    )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Remediation)
            .where(Remediation.id == valid_graph["remediation_id"])
            .values(proposed_diff=legacy.diff)
        )
        connection.execute(
            sa.update(Remediation)
            .where(Remediation.id == invalid_graph["remediation_id"])
            .values(
                proposed_diff=legacy.diff.replace("-old", "-redacted-anchor"),
            )
        )
    monkeypatch.setattr(migrate_patches, "get_engine", lambda: integration_engine)
    monkeypatch.setattr(migrate_patches, "AuthSettings", lambda: integration_settings)
    monkeypatch.setattr(migrate_patches, "CredentialService", lambda **kwargs: None)
    monkeypatch.setattr(migrate_patches, "RepositoryService", lambda **kwargs: None)
    monkeypatch.setattr(
        LocalReviewSourceAccess,
        "open",
        classmethod(
            lambda cls, **kwargs: LocalReviewSourceAccess({"app.py": b"old\n"})
        ),
    )

    def run(*flags: str) -> dict[str, dict[str, object]]:
        monkeypatch.setattr(
            sys, "argv", ["migrate_patches", "--owner", str(owner.user_id), *flags]
        )
        migrate_patches.main()
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        return {line["remediation_id"]: line for line in lines}

    def state():
        with principal_transaction(integration_engine, owner.user_id) as connection:
            return {
                row["id"]: row
                for row in connection.execute(
                    sa.select(
                        Remediation.id,
                        Remediation.generation_status,
                        Remediation.generation_failure,
                    )
                )
                .mappings()
                .all()
            }

    dry = run()
    assert dry[str(valid_graph["remediation_id"])]["outcome"] == "ready"
    assert dry[str(invalid_graph["remediation_id"])]["outcome"] == "unavailable"
    assert {row["generation_status"] for row in state().values()} == {
        "legacy_unverified"
    }
    with principal_transaction(integration_engine, owner.user_id) as connection:
        assert connection.execute(sa.select(patch_artifacts)).first() is None

    run("--apply")
    rows = state()
    assert rows[valid_graph["remediation_id"]]["generation_status"] == "ready"
    failed = rows[invalid_graph["remediation_id"]]
    assert failed["generation_status"] == "failed"
    assert failed["generation_failure"]["code"] == "git_patch_rejected"
    store = PatchStore(
        integration_engine, credential_cipher_from_settings(integration_settings)
    )
    assert (
        store.load(
            owner_id=owner.user_id, remediation_id=valid_graph["remediation_id"]
        ).diff
        == legacy.diff
    )


@pytest.fixture
def worker_engine():
    """The review execution worker connects as trace_internal, not trace_app."""
    import os

    url = os.environ.get("INTERNAL_DATABASE_URL")
    if not url:
        pytest.skip("The isolated internal database role is not configured")
    engine = sa.create_engine(url, pool_pre_ping=True)
    with engine.connect() as connection:
        role = connection.execute(sa.text("SELECT current_user")).scalar_one()
    if role != "trace_internal":
        engine.dispose()
        pytest.skip("The isolated internal database role is not configured")
    yield engine
    engine.dispose()


def test_worker_role_can_stage_replay_and_store_remediations(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
    integration_engine,
    integration_settings,
    worker_engine,
):
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    review = review_factory(owner, project, [UUID(agent["id"])])
    with principal_transaction(integration_engine, owner.user_id) as connection:
        assignment = (
            connection.execute(
                sa.select(ReviewAgent).where(
                    ReviewAgent.review_id == UUID(review["id"])
                )
            )
            .mappings()
            .one()
        )
    service = object.__new__(ReviewExecutionService)
    service._engine = worker_engine
    args = {
        "owner_id": owner.user_id,
        "review": SimpleNamespace(
            id=UUID(review["id"]), project_id=UUID(project["id"])
        ),
        "review_agent": SimpleNamespace(
            agent_id=UUID(agent["id"]),
            id=assignment["id"],
            agent_specialization="security",
        ),
        "findings": [
            ReviewFindingOutput(
                severity="high",
                title="Missing privacy policy",
                explanation="Repository evidence",
                prompt_text="Add the policy",
            )
        ],
    }
    store = PatchStore(
        worker_engine, credential_cipher_from_settings(integration_settings)
    )

    staged = service._stage_findings(**args)
    assert len(staged) == 1
    remediation_id = staged[0][1]
    # A redelivered message finds the saved finding again instead of failing.
    assert [item[1] for item in service._stage_findings(**args)] == [remediation_id]

    store.start(owner_id=owner.user_id, remediation_id=remediation_id)
    store.record_submission(
        owner_id=owner.user_id,
        remediation_id=remediation_id,
        review_attempt_id=None,
        submission_number=1,
        diagnostic=None,
        elapsed_ms=5,
        source_read_count=1,
        model_call_count=1,
    )
    patch = build_patch(
        original={"app.py": "old\n"},
        updated={"app.py": "new\n"},
        snapshot={
            "source_kind": "local",
            "source_identifier": "integration-local-source",
            "revision": "a" * 64,
        },
    )
    store.save(owner_id=owner.user_id, remediation_id=remediation_id, patch=patch)
    assert (
        store.load(owner_id=owner.user_id, remediation_id=remediation_id).diff
        == patch.diff
    )


def test_cipher_failures_do_not_mark_a_ready_patch_unverifiable(
    account_pair,
    local_project_factory,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    integration_settings,
):
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, UUID(project["id"]), UUID(agent["id"]))
    cipher = credential_cipher_from_settings(integration_settings)
    store = PatchStore(integration_engine, cipher)
    patch = build_patch(
        original={"app.py": "old\n"},
        updated={"app.py": "new\n"},
        snapshot={
            "source_kind": "local",
            "source_identifier": "integration-local-source",
            "revision": "a" * 64,
        },
    )
    store.save(
        owner_id=owner.user_id, remediation_id=graph["remediation_id"], patch=patch
    )

    def failing_cipher(error: Exception) -> SimpleNamespace:
        def decrypt_json(*args, **kwargs):
            raise error

        return SimpleNamespace(decrypt_json=decrypt_json)

    for error in (
        CredentialEncryptionUnavailable("key provider is down"),
        CredentialDecryptionError("key version is not available"),
        RuntimeError("unexpected provider failure"),
    ):
        store._cipher = failing_cipher(error)
        with pytest.raises(ResourceUnavailable):
            store.load(owner_id=owner.user_id, remediation_id=graph["remediation_id"])

    with principal_transaction(integration_engine, owner.user_id) as connection:
        row = (
            connection.execute(
                sa.select(
                    Remediation.generation_status, Remediation.generation_failure
                ).where(Remediation.id == graph["remediation_id"])
            )
            .mappings()
            .one()
        )
    assert row["generation_status"] == "ready"
    assert row["generation_failure"] is None
    # Once the key provider recovers, the same artifact is retrievable and exact.
    store._cipher = cipher
    assert (
        store.load(owner_id=owner.user_id, remediation_id=graph["remediation_id"]).diff
        == patch.diff
    )


def test_apply_decrypts_before_locking_and_defers_key_provider_failures(
    account_pair,
    local_project_factory,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    integration_settings,
):
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, UUID(project["id"]), UUID(agent["id"]))
    remediation_id = graph["remediation_id"]
    cipher = credential_cipher_from_settings(integration_settings)
    patch = build_patch(
        original={"app.py": "old\n"},
        updated={"app.py": "new\n"},
        snapshot={
            "source_kind": "local",
            "source_identifier": "integration-local-source",
            "revision": "a" * 64,
        },
    )
    PatchStore(integration_engine, cipher).save(
        owner_id=owner.user_id, remediation_id=remediation_id, patch=patch
    )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == graph["finding_id"])
            .values(status=FindingStatus.ACCEPTED)
        )

    # Waiting on a lock this test's own apply holds fails fast instead of hanging.
    lock_engine = sa.create_engine(
        integration_engine.url, connect_args={"options": "-c lock_timeout=3000"}
    )

    def service_with(decrypt) -> LocalRemediationApplyService:
        store = PatchStore(lock_engine, SimpleNamespace(decrypt_json=decrypt))
        return LocalRemediationApplyService(integration_engine, None, patch_store=store)

    def provider_down(*args, **kwargs):
        raise CredentialEncryptionUnavailable("key provider is down")

    def tampered(*args, **kwargs):
        return {**patch.model_dump(), "diff": "tampered"}

    def apply(service: LocalRemediationApplyService):
        return service.complete(
            owner_id=owner.user_id,
            remediation_id=remediation_id,
            files=[],
            request_id="request",
        )

    try:
        # The fixture already recorded a local apply. Replaying it never needs the
        # key provider, as before the patch moved outside the lock.
        replayed = apply(service_with(provider_down))
        assert replayed["id"] == remediation_id

        with principal_transaction(integration_engine, owner.user_id) as connection:
            connection.execute(
                sa.delete(LocalFileBackup).where(
                    LocalFileBackup.remediation_id == remediation_id
                )
            )

        # A key-provider failure is reported where the patch is first needed and
        # leaves the artifact untouched.
        with pytest.raises(ResourceUnavailable):
            apply(service_with(provider_down))
        with principal_transaction(integration_engine, owner.user_id) as connection:
            failure = connection.execute(
                sa.select(Remediation.generation_failure).where(
                    Remediation.id == remediation_id
                )
            ).scalar_one()
        assert failure is None

        # Recording an integrity failure updates the remediation row, which would
        # block on this apply's own lock had the patch been loaded inside it.
        with pytest.raises(ResourceConflict):
            apply(service_with(tampered))
        with principal_transaction(integration_engine, owner.user_id) as connection:
            failure = connection.execute(
                sa.select(Remediation.generation_failure).where(
                    Remediation.id == remediation_id
                )
            ).scalar_one()
        assert failure["code"] == "patch_decryption_or_integrity_failed"
    finally:
        lock_engine.dispose()
