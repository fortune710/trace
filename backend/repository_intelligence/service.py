"""Revision-keyed persistence and bounded model-facing intelligence selection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from db.types import RepositorySource
from repository_intelligence import models
from repository_intelligence.scanner import (
    ANALYZER_VERSION,
    IntelligencePack,
    scan_files,
)


def ensure_pending(
    connection: Connection,
    *,
    owner_id: UUID,
    project_id: UUID,
    source_kind: RepositorySource,
    source_identifier: str,
    revision: str,
    integrity_algorithm: str,
) -> UUID:
    """Reuse the exact analyzer revision, including under concurrent submissions."""

    identity = {
        "owner_id": owner_id,
        "source_kind": source_kind,
        "source_identifier": source_identifier,
        "source_revision": revision,
        "analyzer_version": ANALYZER_VERSION,
    }
    statement = (
        pg_insert(models.snapshot)
        .values(
            **identity,
            project_id=project_id,
            integrity_algorithm=integrity_algorithm,
            status="pending",
        )
        .on_conflict_do_nothing(constraint="intelligence_snapshots_revision_key")
    )
    connection.execute(statement)
    return connection.execute(
        sa.select(models.snapshot.c.id).where(
            *(models.snapshot.c[key] == value for key, value in identity.items())
        )
    ).scalar_one()


def persist_analysis(
    connection: Connection,
    *,
    owner_id: UUID,
    snapshot_id: UUID,
    source_kind: str,
    source_identifier: str,
    revision: str,
    files: Mapping[str, bytes],
    manifest_digest: str | None = None,
    source_truncated: bool = False,
    source_skipped_files: int = 0,
) -> IntelligencePack:
    """Atomically replace candidate metadata for a single immutable revision."""

    pack = scan_files(
        source_kind=source_kind,
        source_identifier=source_identifier,
        revision=revision,
        files=files,
    )
    digest = (
        manifest_digest
        or hashlib.sha256(
            json.dumps(
                [
                    (path, hashlib.sha256(data).hexdigest())
                    for path, data in sorted(files.items())
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    row = (
        connection.execute(
            sa.select(models.snapshot)
            .where(
                models.snapshot.c.id == snapshot_id,
                models.snapshot.c.owner_id == owner_id,
            )
            .with_for_update()
        )
        .mappings()
        .one()
    )
    if (row["source_kind"].value, row["source_identifier"], row["source_revision"]) != (
        source_kind,
        source_identifier,
        revision,
    ):
        raise ValueError("intelligence_revision_mismatch")
    if row["status"] == "ready":
        return pack
    file_ids: dict[str, UUID] = {}
    for item in pack.facts:
        result = connection.execute(
            sa.insert(models.fact)
            .values(
                owner_id=owner_id,
                snapshot_id=snapshot_id,
                kind=item.kind,
                path=item.path,
                symbol=item.symbol,
                line_start=item.line,
                line_end=item.line,
                attributes_json={"value": item.value} if item.value else {},
                evidence_digest=item.digest,
            )
            .returning(models.fact.c.id)
        )
        file_ids.setdefault(item.path, result.scalar_one())
    for edge in pack.edges:
        if edge.from_path in file_ids and edge.to_path in file_ids:
            connection.execute(
                sa.insert(models.edge).values(
                    owner_id=owner_id,
                    snapshot_id=snapshot_id,
                    from_fact_id=file_ids[edge.from_path],
                    to_fact_id=file_ids[edge.to_path],
                    relationship=edge.relationship,
                    evidence_path=edge.from_path,
                    evidence_line=edge.line,
                )
            )
    seen_hits: set[tuple[str, int, str, int]] = set()
    for hit in pack.rule_hits:
        hit_key = (hit.rule_id, hit.version, hit.path, hit.line)
        if hit_key in seen_hits:
            continue
        seen_hits.add(hit_key)
        connection.execute(
            sa.insert(models.rule_hit).values(
                owner_id=owner_id,
                snapshot_id=snapshot_id,
                rule_id=hit.rule_id,
                rule_version=hit.version,
                path=hit.path,
                line_start=hit.line,
                severity="medium",
                confidence="candidate",
                metadata_json={"symbol": hit.symbol},
                evidence_digest=hit.digest,
            )
        )
    connection.execute(
        sa.update(models.snapshot)
        .where(models.snapshot.c.id == snapshot_id)
        .values(
            status="ready",
            manifest_digest=digest,
            summary_json={
                "frameworks": pack.frameworks,
                "skipped_counts": {
                    **pack.skipped_counts,
                    "source_unreadable": source_skipped_files,
                    "source_truncated": int(source_truncated),
                },
            },
            completed_at=sa.func.current_timestamp(),
        )
    )
    return pack


def select_agent_surfaces(
    connection: Connection,
    *,
    owner_id: UUID,
    snapshot_id: UUID,
    specialty: str,
    project_category: str,
) -> tuple[str, ...]:
    """Return compact candidate paths; the agent must still inspect source."""

    rows = connection.execute(
        sa.select(models.fact.c.kind, models.fact.c.path, models.fact.c.line_start)
        .where(
            models.fact.c.owner_id == owner_id, models.fact.c.snapshot_id == snapshot_id
        )
        .order_by(models.fact.c.path)
        .limit(500)
    ).all()
    hits = connection.execute(
        sa.select(
            models.rule_hit.c.rule_id,
            models.rule_hit.c.path,
            models.rule_hit.c.line_start,
        )
        .where(
            models.rule_hit.c.owner_id == owner_id,
            models.rule_hit.c.snapshot_id == snapshot_id,
        )
        .limit(100)
    ).all()
    ranked: dict[str, int] = {}
    reasons: dict[str, str] = {}
    for kind, path, line in rows:
        score = {
            "route": 3,
            "policy_or_disclosure": 2,
            "integration_reference": 2,
            "outbound_request": 2,
        }.get(kind, 0)
        if specialty == "legal" and kind == "policy_or_disclosure":
            score += 4
        if project_category in {"finance", "e_commerce"} and any(
            term in path.lower() for term in ("billing", "payment", "price")
        ):
            score += 3
        ranked[path] = max(ranked.get(path, 0), score)
        if score > 0:
            reasons[path] = (
                f"{kind} signal at line {line}" if line else f"{kind} path signal"
            )
    for rule, path, line in hits:
        ranked[path] = ranked.get(path, 0) + 5
        reasons[path] = f"{rule} candidate at line {line}"
    return tuple(
        f"{path} ({reasons[path]}; verify in source)"
        for path, score in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))
        if score > 0
    )[:3]
