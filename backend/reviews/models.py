"""Review persistence and durable dispatch-outbox models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import RepositorySource, ReviewCategory, native_enum


class ReviewStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewAgentStatus(str, Enum):
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewDispatchStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    DEAD_LETTER = "dead_letter"


class ReviewAgentAttemptStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="reviews_owner_id_id_key"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_id", name="reviews_owner_idempotency_id_key"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["public.projects.owner_id", "public.projects.id"],
            name="reviews_owner_project_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(source_kind = 'github' AND integrity_algorithm = 'git-commit-sha1-v1' "
            "AND source_revision ~ '^[0-9a-f]{40}$') OR "
            "(source_kind = 'local' AND integrity_algorithm = 'sha256-directory-manifest-v1' "
            "AND source_revision ~ '^[0-9a-f]{64}$')",
            name="reviews_source_snapshot_check",
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
    source_revision: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_kind: Mapped[RepositorySource] = mapped_column(
        native_enum(RepositorySource, "repository_source", "public"), nullable=False
    )
    source_identifier: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    integrity_algorithm: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_captured_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    status: Mapped[ReviewStatus] = mapped_column(
        native_enum(ReviewStatus, "review_status", "public"),
        nullable=False,
        server_default=sa.text("'queued'::public.review_status"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
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
    retry_version: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    idempotency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
        server_default=sa.text("public.uuidv7()"),
    )
    idempotency_key_digest: Mapped[bytes | None] = mapped_column(
        sa.LargeBinary(), nullable=True
    )
    request_digest: Mapped[bytes | None] = mapped_column(
        sa.LargeBinary(), nullable=True
    )


class ReviewAgent(Base):
    __tablename__ = "review_agents"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id", "review_id", "agent_id", name="review_agents_owner_tuple_key"
        ),
        sa.UniqueConstraint("owner_id", "id", name="review_agents_owner_id_id_key"),
        sa.UniqueConstraint(
            "owner_id", "review_id", "id", name="review_agents_owner_review_id_id_key"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_id"],
            ["public.reviews.owner_id", "public.reviews.id"],
            name="review_agents_owner_review_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "agent_id"],
            ["public.agents.owner_id", "public.agents.id"],
            name="review_agents_owner_agent_fkey",
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
    review_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    agent_display_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    agent_specialization: Mapped[ReviewCategory] = mapped_column(
        native_enum(ReviewCategory, "review_category", "public"), nullable=False
    )
    agent_model_provider: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    agent_model_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    agent_personality: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    agent_skills: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    agent_configuration_version: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False
    )
    status: Mapped[ReviewAgentStatus] = mapped_column(
        native_enum(ReviewAgentStatus, "review_agent_status", "public"),
        nullable=False,
        server_default=sa.text("'assigned'::public.review_agent_status"),
    )
    error_reason: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class ReviewDispatchJob(Base):
    """Internal identifier-only work item for a future queue publisher."""

    __tablename__ = "review_dispatch_jobs"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id", "review_agent_id", name="review_dispatch_jobs_owner_agent_key"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="review_dispatch_jobs_attempts_check"
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z0-9_]{1,64}$'",
            name="review_dispatch_jobs_failure_code_check",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_id", "review_agent_id"],
            [
                "public.review_agents.owner_id",
                "public.review_agents.review_id",
                "public.review_agents.id",
            ],
            name="review_dispatch_jobs_owner_assignment_fkey",
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
    review_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    review_agent_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    status: Mapped[ReviewDispatchStatus] = mapped_column(
        native_enum(ReviewDispatchStatus, "review_dispatch_status", "private"),
        nullable=False,
        server_default=sa.text("'pending'::private.review_dispatch_status"),
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


class ReviewAgentAttempt(Base):
    """Private contract reserved for future provider execution."""

    __tablename__ = "review_agent_attempts"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id",
            "review_agent_id",
            "attempt_number",
            name="review_agent_attempts_owner_number_key",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1", name="review_agent_attempts_number_check"
        ),
        sa.CheckConstraint(
            "retry_count >= 0", name="review_agent_attempts_retry_check"
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z0-9_]{1,64}$'",
            name="review_agent_attempts_failure_code_check",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_id", "review_agent_id"],
            [
                "public.review_agents.owner_id",
                "public.review_agents.review_id",
                "public.review_agents.id",
            ],
            name="review_agent_attempts_owner_assignment_fkey",
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
    review_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    review_agent_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    status: Mapped[ReviewAgentAttemptStatus] = mapped_column(
        native_enum(ReviewAgentAttemptStatus, "review_agent_attempt_status", "private"),
        nullable=False,
    )
    provider_request_id: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    retry_count: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    failure_code: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
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


class ReviewAgentExecutionConfig(Base):
    """Private immutable credential reference for one review-agent snapshot."""

    __tablename__ = "review_agent_execution_configs"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["owner_id", "review_id", "review_agent_id"],
            [
                "public.review_agents.owner_id",
                "public.review_agents.review_id",
                "public.review_agents.id",
            ],
            name="review_agent_execution_configs_owner_assignment_fkey",
            ondelete="CASCADE",
        ),
        {"schema": "private"},
    )

    review_agent_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    review_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    credential_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


sa.Index("reviews_owner_created_idx", Review.owner_id, Review.created_at.desc())
sa.Index("reviews_owner_project_idx", Review.owner_id, Review.project_id)
sa.Index(
    "reviews_owner_source_revision_idx",
    Review.owner_id,
    Review.source_kind,
    Review.source_revision,
)
sa.Index(
    "reviews_owner_idempotency_key_unique",
    Review.owner_id,
    Review.idempotency_key_digest,
    unique=True,
    postgresql_where=Review.idempotency_key_digest.is_not(None),
)
sa.Index("review_agents_owner_review_idx", ReviewAgent.owner_id, ReviewAgent.review_id)
sa.Index("review_agents_owner_agent_idx", ReviewAgent.owner_id, ReviewAgent.agent_id)
sa.Index(
    "private_review_dispatch_jobs_pending_claim_idx",
    ReviewDispatchJob.status,
    ReviewDispatchJob.next_attempt_at,
    ReviewDispatchJob.created_at,
    ReviewDispatchJob.idempotency_id,
    postgresql_where=ReviewDispatchJob.status == ReviewDispatchStatus.PENDING,
)
sa.Index(
    "private_review_dispatch_jobs_review_idx",
    ReviewDispatchJob.owner_id,
    ReviewDispatchJob.review_id,
    ReviewDispatchJob.created_at.desc(),
)


__all__ = [
    "Review",
    "ReviewAgent",
    "ReviewAgentAttempt",
    "ReviewAgentAttemptStatus",
    "ReviewAgentExecutionConfig",
    "ReviewAgentStatus",
    "ReviewCategory",
    "ReviewDispatchJob",
    "ReviewDispatchStatus",
    "ReviewStatus",
]
