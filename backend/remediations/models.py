"""Remediation database models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import native_enum


class RemediationStatus(str, Enum):
    PROPOSED = "proposed"
    REJECTED = "rejected"
    APPLIED = "applied"


class RemediationPullRequestJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"


class RemediationPullRequestOutboxStatus(str, Enum):
    WAITING_FOR_ACCEPTANCE = "waiting_for_acceptance"
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class Remediation(Base):
    __tablename__ = "remediations"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="remediations_owner_id_id_key"),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["public.projects.owner_id", "public.projects.id"],
            name="remediations_owner_project_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "pull_request IS NULL OR ("
            "jsonb_typeof(pull_request) = 'object' "
            "AND pull_request ?& ARRAY['url', 'number', 'is_merged'] "
            "AND pull_request - 'url' - 'number' - 'is_merged' = '{}'::jsonb "
            "AND jsonb_typeof(pull_request -> 'url') = 'string' "
            "AND length(pull_request ->> 'url') > 0 "
            "AND jsonb_typeof(pull_request -> 'number') = 'number' "
            "AND (pull_request ->> 'number') ~ '^[1-9][0-9]*$' "
            "AND jsonb_typeof(pull_request -> 'is_merged') = 'boolean'"
            ")",
            name="remediations_pull_request_shape_check",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "finding_id"],
            ["public.findings.owner_id", "public.findings.id"],
            name="remediations_owner_finding_fkey",
            ondelete="CASCADE",
        ),
        {"schema": "public"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    finding_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    prompt_text: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    proposed_diff: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    generation_status: Mapped[str] = mapped_column(
        sa.Text(), nullable=False, server_default=sa.text("'legacy_unverified'")
    )
    generation_contract_version: Mapped[int | None] = mapped_column(
        sa.Integer(), nullable=True
    )
    generation_failure: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    patch_artifact_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    pull_request: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[RemediationStatus] = mapped_column(
        native_enum(RemediationStatus, "remediation_status", "public"),
        nullable=False,
        server_default=sa.text("'proposed'::public.remediation_status"),
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    mutation_version: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )


sa.CheckConstraint(
    "generation_status IN ('pending','running','ready','failed','legacy_unverified')",
    name="remediations_generation_status_check",
    table=cast(sa.Table, Remediation.__table__),
)
sa.CheckConstraint(
    "generation_status <> 'ready' OR (patch_artifact_id IS NOT NULL AND validated_at IS NOT NULL)",
    name="remediations_ready_artifact_check",
    table=cast(sa.Table, Remediation.__table__),
)
sa.Index(
    "remediations_owner_finding_v2_key",
    Remediation.owner_id,
    Remediation.finding_id,
    unique=True,
    postgresql_where=Remediation.generation_contract_version == 2,
)


class RemediationPullRequestJob(Base):
    """Private durable retry work for a failed pull-request publication."""

    __tablename__ = "remediation_pull_request_jobs"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id",
            "remediation_id",
            name="remediation_pull_request_jobs_owner_remediation_key",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="remediation_pull_request_jobs_attempts_check",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z0-9_]{1,64}$'",
            name="remediation_pull_request_jobs_failure_code_check",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "remediation_id"],
            ["public.remediations.owner_id", "public.remediations.id"],
            name="remediation_pull_request_jobs_owner_remediation_fkey",
            ondelete="CASCADE",
        ),
        {"schema": "private"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    remediation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    status: Mapped[RemediationPullRequestJobStatus] = mapped_column(
        native_enum(
            RemediationPullRequestJobStatus,
            "remediation_pull_request_job_status",
            "private",
        ),
        nullable=False,
        server_default=sa.text(
            "'pending'::private.remediation_pull_request_job_status"
        ),
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    succeeded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class RemediationPullRequestOutboxJob(Base):
    """Private durable intent to publish one automatic remediation PR."""

    __tablename__ = "remediation_pull_request_outbox_jobs"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id",
            "remediation_id",
            name="remediation_pr_outbox_owner_remediation_key",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="remediation_pr_outbox_attempts_check",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z0-9_]{1,64}$'",
            name="remediation_pr_outbox_failure_code_check",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "remediation_id"],
            ["public.remediations.owner_id", "public.remediations.id"],
            name="remediation_pr_outbox_owner_remediation_fkey",
            ondelete="CASCADE",
        ),
        {"schema": "private"},
    )

    idempotency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    remediation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    status: Mapped[RemediationPullRequestOutboxStatus] = mapped_column(
        native_enum(
            RemediationPullRequestOutboxStatus,
            "remediation_pull_request_outbox_status",
            "private",
        ),
        nullable=False,
        server_default=sa.text(
            "'waiting_for_acceptance'::private.remediation_pull_request_outbox_status"
        ),
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


sa.Index(
    "remediations_owner_created_idx",
    Remediation.owner_id,
    Remediation.created_at.desc(),
)
sa.Index(
    "private_remediation_pr_outbox_pending_claim_idx",
    RemediationPullRequestOutboxJob.status,
    RemediationPullRequestOutboxJob.next_attempt_at,
    RemediationPullRequestOutboxJob.created_at,
    RemediationPullRequestOutboxJob.idempotency_id,
    postgresql_where=(
        RemediationPullRequestOutboxJob.status
        == RemediationPullRequestOutboxStatus.PENDING
    ),
)
sa.Index(
    "private_remediation_pull_request_jobs_pending_claim_idx",
    RemediationPullRequestJob.status,
    RemediationPullRequestJob.next_attempt_at,
    RemediationPullRequestJob.created_at,
    RemediationPullRequestJob.id,
    postgresql_where=(
        RemediationPullRequestJob.status == RemediationPullRequestJobStatus.PENDING
    ),
)
sa.Index(
    "remediations_owner_finding_idx",
    Remediation.owner_id,
    Remediation.finding_id,
    unique=True,
)


__all__ = [
    "Remediation",
    "RemediationPullRequestJob",
    "RemediationPullRequestJobStatus",
    "RemediationPullRequestOutboxJob",
    "RemediationPullRequestOutboxStatus",
    "RemediationStatus",
]
