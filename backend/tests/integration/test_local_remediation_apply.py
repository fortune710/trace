from __future__ import annotations

import hashlib

import pytest
import sqlalchemy as sa

from agents.execution.patches import build_patch
from artifacts.models import LocalFileBackup
from auth.credentials import CredentialCipher
from db.rls import principal_transaction
from findings.models import Finding, FindingStatus
from remediations.models import Remediation, RemediationStatus
from remediations.patch_store import PatchStore
from reviews.models import Review, ReviewStatus

pytestmark = pytest.mark.integration


def _files(remediation_id: object, *paths: str) -> list[dict[str, str]]:
    return [
        {
            "file_path": path,
            "backup_reference": f"local-remediation-backups/{remediation_id}/{path}",
            "source_hash": hashlib.sha256(b"before\n").hexdigest(),
            "applied_hash": hashlib.sha256(b"after\n").hexdigest(),
        }
        for path in paths
    ]


def _prepare_accepted_multi_file_remediation(
    *, account, graph, integration_engine
) -> None:
    with principal_transaction(integration_engine, account.user_id) as connection:
        connection.execute(
            sa.delete(LocalFileBackup).where(
                LocalFileBackup.owner_id == account.user_id,
                LocalFileBackup.remediation_id == graph["remediation_id"],
            )
        )
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == graph["finding_id"])
            .values(status=FindingStatus.ACCEPTED)
        )
        connection.execute(
            sa.update(Remediation)
            .where(Remediation.id == graph["remediation_id"])
            .values(
                proposed_diff=(
                    "diff --git a/src/first.txt b/src/first.txt\n"
                    "--- a/src/first.txt\n+++ b/src/first.txt\n"
                    "@@ -1 +1 @@\n-before\n+after\n"
                    "diff --git a/src/second.txt b/src/second.txt\n"
                    "--- a/src/second.txt\n+++ b/src/second.txt\n"
                    "@@ -1 +1 @@\n-before\n+after\n"
                )
            )
        )

    patch = build_patch(
        original={"src/first.txt": "before\n", "src/second.txt": "before\n"},
        updated={"src/first.txt": "after\n", "src/second.txt": "after\n"},
        snapshot={
            "source_kind": "local",
            "source_identifier": "integration-local-source",
            "revision": "a" * 64,
        },
    )
    PatchStore(
        integration_engine, CredentialCipher(key=b"c" * 32, key_version="local-v1")
    ).save(
        owner_id=account.user_id, remediation_id=graph["remediation_id"], patch=patch
    )


def test_owner_records_every_local_file_and_audits_once(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    local_project_factory,
    recording_audit_recorder,
) -> None:
    owner, _other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    _prepare_accepted_multi_file_remediation(
        account=owner, graph=graph, integration_engine=integration_engine
    )

    response = owner.request(
        "POST",
        f"/api/v1/remediations/{graph['remediation_id']}/apply-local",
        json={
            "files": _files(graph["remediation_id"], "src/first.txt", "src/second.txt")
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "applied"
    assert response.json()["approved_at"] is not None
    with principal_transaction(integration_engine, owner.user_id) as connection:
        backups = (
            connection.execute(
                sa.select(LocalFileBackup).where(
                    LocalFileBackup.remediation_id == graph["remediation_id"]
                )
            )
            .mappings()
            .all()
        )
    assert {backup["file_path"] for backup in backups} == {
        "src/first.txt",
        "src/second.txt",
    }
    assert all(
        backup["source_hash"] == hashlib.sha256(b"before\n").digest()
        for backup in backups
    )
    assert all(
        backup["applied_hash"] == hashlib.sha256(b"after\n").digest()
        for backup in backups
    )
    local_apply_events = [
        event
        for event in recording_audit_recorder.events
        if event["event_type"] == "remediation.local_file.applied"
    ]
    assert len(local_apply_events) == 1
    assert local_apply_events[0]["fields"] == {
        "remediation_id": str(graph["remediation_id"]),
        "file_count": "2",
    }

    replay = owner.request(
        "POST",
        f"/api/v1/remediations/{graph['remediation_id']}/apply-local",
        json={
            "files": _files(graph["remediation_id"], "src/first.txt", "src/second.txt")
        },
    )
    assert replay.status_code == 200
    assert (
        len(
            [
                event
                for event in recording_audit_recorder.events
                if event["event_type"] == "remediation.local_file.applied"
            ]
        )
        == 1
    )


def test_local_apply_rejects_bad_authorization_and_mismatched_paths(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    local_project_factory,
    recording_audit_recorder,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])
    _prepare_accepted_multi_file_remediation(
        account=owner, graph=graph, integration_engine=integration_engine
    )
    path = f"/api/v1/remediations/{graph['remediation_id']}/apply-local"

    assert (
        owner.client.post(
            path,
            json={
                "files": _files(
                    graph["remediation_id"], "src/first.txt", "src/second.txt"
                )
            },
        ).status_code
        == 403
    )
    assert (
        other.request(
            "POST",
            path,
            json={
                "files": _files(
                    graph["remediation_id"], "src/first.txt", "src/second.txt"
                )
            },
        ).status_code
        == 403
    )
    mismatch = owner.request(
        "POST", path, json={"files": _files(graph["remediation_id"], "src/first.txt")}
    )
    assert mismatch.status_code == 409
    wrong_backup = _files(graph["remediation_id"], "src/first.txt", "src/second.txt")
    wrong_backup[0]["backup_reference"] = "other-backup"
    assert owner.request("POST", path, json={"files": wrong_backup}).status_code == 409
    unsafe = owner.request(
        "POST", path, json={"files": _files(graph["remediation_id"], "../private.txt")}
    )
    assert unsafe.status_code == 400
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == graph["finding_id"])
            .values(status=FindingStatus.OPEN)
        )
    assert (
        owner.request(
            "POST",
            path,
            json={
                "files": _files(
                    graph["remediation_id"], "src/first.txt", "src/second.txt"
                )
            },
        ).status_code
        == 409
    )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.update(Finding)
            .where(Finding.id == graph["finding_id"])
            .values(status=FindingStatus.ACCEPTED)
        )
        connection.execute(
            sa.update(Review)
            .where(Review.id == graph["review_id"])
            .values(status=ReviewStatus.FAILED)
        )
    assert (
        owner.request(
            "POST",
            path,
            json={
                "files": _files(
                    graph["remediation_id"], "src/first.txt", "src/second.txt"
                )
            },
        ).status_code
        == 409
    )
    with principal_transaction(integration_engine, owner.user_id) as connection:
        status = connection.execute(
            sa.select(Remediation.status).where(
                Remediation.id == graph["remediation_id"]
            )
        ).scalar_one()
        backups = connection.execute(
            sa.select(sa.func.count())
            .select_from(LocalFileBackup)
            .where(LocalFileBackup.remediation_id == graph["remediation_id"])
        ).scalar_one()
    assert status is RemediationStatus.PROPOSED
    assert backups == 0
    assert not any(
        event["event_type"] == "remediation.local_file.applied"
        for event in recording_audit_recorder.events
    )
