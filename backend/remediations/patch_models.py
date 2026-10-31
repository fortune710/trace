"""Private encrypted artifacts and safe generation diagnostics."""

from typing import cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base
from remediations.models import Remediation

patch_artifacts = sa.Table(
    "remediation_patch_artifacts",
    Base.metadata,
    sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    ),
    sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
    sa.Column("remediation_id", UUID(as_uuid=True), nullable=False),
    sa.Column("source_snapshot", JSONB, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("key_version", sa.Text, nullable=False),
    sa.Column("aad_version", sa.Text, nullable=False),
    sa.Column("encryption_provider", sa.Text, nullable=False),
    sa.Column("key_reference", sa.Text, nullable=False),
    sa.Column("sha256", sa.Text, nullable=False),
    sa.Column(
        "format_version", sa.Integer, nullable=False, server_default=sa.text("2")
    ),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.UniqueConstraint("owner_id", "id", name="patch_artifacts_owner_id_key"),
    sa.UniqueConstraint(
        "owner_id", "remediation_id", name="patch_artifacts_owner_remediation_key"
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "remediation_id"],
        ["public.remediations.owner_id", "public.remediations.id"],
        ondelete="CASCADE",
    ),
    schema="private",
)

generation_attempts = sa.Table(
    "remediation_generation_attempts",
    Base.metadata,
    sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    ),
    sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
    sa.Column("remediation_id", UUID(as_uuid=True), nullable=False),
    sa.Column("review_attempt_id", UUID(as_uuid=True), nullable=True),
    sa.Column("submission_number", sa.Integer, nullable=False),
    sa.Column("outcome", sa.Text, nullable=False),
    sa.Column("diagnostics_json", JSONB, nullable=True),
    sa.Column(
        "source_read_count", sa.Integer, nullable=False, server_default=sa.text("0")
    ),
    sa.Column(
        "model_call_count", sa.Integer, nullable=False, server_default=sa.text("0")
    ),
    sa.Column("elapsed_ms", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.UniqueConstraint(
        "owner_id",
        "remediation_id",
        "submission_number",
        name="generation_attempt_submission_key",
    ),
    sa.CheckConstraint(
        "submission_number BETWEEN 1 AND 3", name="generation_attempt_submission_check"
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "remediation_id"],
        ["public.remediations.owner_id", "public.remediations.id"],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "review_attempt_id"],
        ["private.review_agent_attempts.owner_id", "private.review_agent_attempts.id"],
        ondelete="CASCADE",
    ),
    schema="private",
)

sa.ForeignKeyConstraint(
    ["owner_id", "patch_artifact_id"],
    [
        "private.remediation_patch_artifacts.owner_id",
        "private.remediation_patch_artifacts.id",
    ],
    name="remediations_owner_patch_artifact_fkey",
    use_alter=True,
    table=cast(sa.Table, Remediation.__table__),
)
