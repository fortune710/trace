from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from db.rls import principal_transaction
from findings.models import Finding, FindingSeverity, FindingStatus
from reviews.models import ReviewAgent, ReviewAgentStatus

pytestmark = pytest.mark.integration


def _add_review_findings(
    engine,
    *,
    owner_id: UUID,
    review_id: UUID,
    agent_id: UUID,
) -> list[UUID]:
    finding_ids = [uuid4(), uuid4()]
    created_at = datetime(2026, 10, 26, tzinfo=UTC)
    with principal_transaction(engine, owner_id) as connection:
        connection.execute(
            sa.insert(ReviewAgent).values(
                owner_id=owner_id,
                review_id=review_id,
                agent_id=agent_id,
                agent_display_name="Snapshot reviewer",
                agent_specialization="engineering",
                agent_model_provider="openai",
                agent_model_name="gpt-6.1-sol",
                agent_skills=[],
                agent_configuration_version=2,
                status=ReviewAgentStatus.COMPLETED,
            )
        )
        connection.execute(
            sa.insert(Finding),
            [
                {
                    "id": finding_ids[0],
                    "owner_id": owner_id,
                    "review_id": review_id,
                    "agent_id": agent_id,
                    "category": "engineering",
                    "severity": FindingSeverity.LOW,
                    "title": "Older engineering finding",
                    "explanation": "A bounded explanation.",
                    "status": FindingStatus.RESOLVED,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
                {
                    "id": finding_ids[1],
                    "owner_id": owner_id,
                    "review_id": review_id,
                    "agent_id": agent_id,
                    "category": "engineering",
                    "severity": FindingSeverity.CRITICAL,
                    "title": "Newer engineering finding",
                    "explanation": "A bounded explanation.",
                    "status": FindingStatus.OPEN,
                    "created_at": created_at + timedelta(minutes=1),
                    "updated_at": created_at + timedelta(minutes=1),
                },
            ],
        )
    return finding_ids


def test_findings_support_combined_filters_pagination_and_snapshot_reviewer_data(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    local_project_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    first_agent = agent_factory(owner)
    second_agent = agent_factory(
        owner, name="Current mutable agent", category="engineering"
    )
    graph = artifact_graph_factory(owner, project["id"], first_agent["id"])
    older_id, newer_id = _add_review_findings(
        integration_engine,
        owner_id=owner.user_id,
        review_id=graph["review_id"],
        agent_id=UUID(second_agent["id"]),
    )

    first_page = owner.request(
        "GET",
        f"/api/v1/reviews/{graph['review_id']}/findings?category=engineering&page_size=1",
    )
    filtered = owner.request(
        "GET",
        (
            f"/api/v1/reviews/{graph['review_id']}/findings?category=engineering"
            f"&severity=critical&status=open&agent_id={second_agent['id']}"
        ),
    )

    assert first_page.status_code == 200
    assert first_page.json()["items"][0]["id"] == str(newer_id)
    assert first_page.json()["next_offset"] == 1
    filtered_items = filtered.json()["items"]
    assert len(filtered_items) == 1
    assert filtered_items[0]["id"] == str(newer_id)
    assert filtered_items[0]["reviewing_agent"] == {
        "assignment_id": filtered_items[0]["reviewing_agent"]["assignment_id"],
        "agent_id": second_agent["id"],
        "display_name": "Snapshot reviewer",
        "specialization": "engineering",
    }
    second_page = owner.request(
        "GET",
        f"/api/v1/reviews/{graph['review_id']}/findings?category=engineering&page_size=1&page=2",
    )
    assert second_page.json()["items"][0]["id"] == str(older_id)
    assert second_page.json()["next_offset"] is None


def test_findings_query_validation_and_foreign_review_access_are_safe(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    local_project_factory,
) -> None:
    owner, other = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])

    invalid_page = owner.request(
        "GET",
        f"/api/v1/reviews/{graph['review_id']}/findings?page=0",
    )
    invalid_filter = owner.request(
        "GET",
        f"/api/v1/reviews/{graph['review_id']}/findings?severity=urgent",
    )
    conflicting_status_filters = owner.request(
        "GET",
        f"/api/v1/reviews/{graph['review_id']}/findings?status=open&exclude_status=dismissed",
    )
    malformed_id = owner.request("GET", "/api/v1/findings/not-a-uuid")
    foreign = other.request(
        "GET",
        f"/api/v1/reviews/{graph['review_id']}/findings",
    )

    assert invalid_page.status_code == 400
    assert invalid_filter.status_code == 400
    assert conflicting_status_filters.status_code == 400
    assert malformed_id.status_code == 400
    assert foreign.status_code == 403
    assert str(owner.user_id) not in foreign.text


def test_owner_review_status_query_uses_the_triage_index(
    account_pair,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
    local_project_factory,
) -> None:
    owner, _ = account_pair
    project = local_project_factory(owner)
    agent = agent_factory(owner)
    graph = artifact_graph_factory(owner, project["id"], agent["id"])

    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            connection.execute(
                sa.text(
                    "EXPLAIN (COSTS OFF) "
                    "SELECT id FROM public.findings "
                    "WHERE owner_id = :owner_id "
                    "AND review_id = :review_id "
                    "AND status = 'open'::public.finding_status "
                    "ORDER BY created_at DESC, id DESC"
                ),
                {"owner_id": owner.user_id, "review_id": graph["review_id"]},
            ).scalars()
        )
        index_definition = connection.execute(
            sa.text(
                "SELECT pg_get_indexdef("
                "'public.findings_owner_review_status_created_idx'::regclass)"
            )
        ).scalar_one()

    assert "Index Scan" in plan
    assert index_definition == (
        "CREATE INDEX findings_owner_review_status_created_idx ON public.findings "
        "USING btree (owner_id, review_id, status, created_at DESC, id DESC)"
    )
