"""Owner-scoped source intelligence persistence."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base
from db.types import RepositorySource, native_enum

snapshot = sa.Table(
    "repository_intelligence_snapshots",
    Base.metadata,
    sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    ),
    sa.Column(
        "owner_id",
        UUID(as_uuid=True),
        sa.ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("project_id", UUID(as_uuid=True), nullable=False),
    sa.Column(
        "source_kind",
        native_enum(RepositorySource, "repository_source", "public"),
        nullable=False,
    ),
    sa.Column("source_identifier", sa.Text(), nullable=False),
    sa.Column("source_revision", sa.Text(), nullable=False),
    sa.Column("integrity_algorithm", sa.Text(), nullable=False),
    sa.Column("analyzer_version", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column(
        "attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")
    ),
    sa.Column("claimed_at", sa.DateTime(timezone=True)),
    sa.Column("manifest_digest", sa.Text()),
    sa.Column(
        "summary_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    ),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "attempt_count >= 0", name="intelligence_snapshot_attempt_count_check"
    ),
    sa.UniqueConstraint("owner_id", "id", name="intelligence_snapshots_owner_id_key"),
    sa.UniqueConstraint(
        "owner_id",
        "source_kind",
        "source_identifier",
        "source_revision",
        "analyzer_version",
        name="intelligence_snapshots_revision_key",
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "project_id"],
        ["public.projects.owner_id", "public.projects.id"],
        ondelete="CASCADE",
    ),
    sa.CheckConstraint(
        "status IN ('pending', 'running', 'ready', 'failed')",
        name="intelligence_snapshot_status_check",
    ),
    schema="private",
)

fact = sa.Table(
    "repository_intelligence_facts",
    Base.metadata,
    sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    ),
    sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
    sa.Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("path", sa.Text(), nullable=False),
    sa.Column("symbol", sa.Text()),
    sa.Column("line_start", sa.Integer()),
    sa.Column("line_end", sa.Integer()),
    sa.Column(
        "attributes_json",
        JSONB(),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ),
    sa.Column("evidence_digest", sa.Text(), nullable=False),
    sa.UniqueConstraint(
        "owner_id", "snapshot_id", "id", name="intelligence_facts_owner_snapshot_id_key"
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "snapshot_id"],
        [snapshot.c.owner_id, snapshot.c.id],
        ondelete="CASCADE",
    ),
    schema="private",
)
sa.Index("intelligence_facts_lookup_idx", fact.c.snapshot_id, fact.c.kind, fact.c.path)

edge = sa.Table(
    "repository_intelligence_edges",
    Base.metadata,
    sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    ),
    sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
    sa.Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    sa.Column("from_fact_id", UUID(as_uuid=True), nullable=False),
    sa.Column("to_fact_id", UUID(as_uuid=True), nullable=False),
    sa.Column("relationship", sa.Text(), nullable=False),
    sa.Column("evidence_path", sa.Text(), nullable=False),
    sa.Column("evidence_line", sa.Integer()),
    sa.ForeignKeyConstraint(
        ["owner_id", "snapshot_id"],
        [snapshot.c.owner_id, snapshot.c.id],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "snapshot_id", "from_fact_id"],
        [fact.c.owner_id, fact.c.snapshot_id, fact.c.id],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "snapshot_id", "to_fact_id"],
        [fact.c.owner_id, fact.c.snapshot_id, fact.c.id],
        ondelete="CASCADE",
    ),
    schema="private",
)

rule_hit = sa.Table(
    "repository_static_rule_hits",
    Base.metadata,
    sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    ),
    sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
    sa.Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    sa.Column("rule_id", sa.Text(), nullable=False),
    sa.Column("rule_version", sa.Integer(), nullable=False),
    sa.Column("path", sa.Text(), nullable=False),
    sa.Column("line_start", sa.Integer(), nullable=False),
    sa.Column("line_end", sa.Integer()),
    sa.Column("severity", sa.Text(), nullable=False),
    sa.Column("confidence", sa.Text(), nullable=False),
    sa.Column(
        "metadata_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    ),
    sa.Column("evidence_digest", sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(
        ["owner_id", "snapshot_id"],
        [snapshot.c.owner_id, snapshot.c.id],
        ondelete="CASCADE",
    ),
    sa.UniqueConstraint(
        "snapshot_id",
        "rule_id",
        "rule_version",
        "path",
        "line_start",
        name="intelligence_rule_hit_key",
    ),
    schema="private",
)

local_source = sa.Table(
    "local_review_source_snapshots",
    Base.metadata,
    sa.Column("review_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
    sa.Column("source_revision", sa.Text(), nullable=False),
    sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
    sa.Column("nonce", sa.LargeBinary(), nullable=False),
    sa.Column("key_version", sa.Text(), nullable=False),
    sa.Column("encryption_provider", sa.Text(), nullable=False),
    sa.Column("key_reference", sa.Text(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "review_id"],
        ["public.reviews.owner_id", "public.reviews.id"],
        ondelete="CASCADE",
    ),
    schema="private",
)
