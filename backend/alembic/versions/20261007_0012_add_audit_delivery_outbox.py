"""Add the transient PostgreSQL audit delivery outbox."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261007_0012"
down_revision = "20261007_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE private.audit_delivery_status AS ENUM "
        "('pending', 'processing', 'delivered', 'dead_letter')"
    )
    op.create_table(
        "audit_delivery_jobs",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("canonical_json", sa.Text(), nullable=False),
        sa.Column("event_hash", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "delivered",
                "dead_letter",
                name="audit_delivery_status",
                schema="private",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending'::private.audit_delivery_status"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("transaction_hash", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id", name="private_audit_delivery_jobs_pkey"),
        schema="private",
    )
    op.create_index(
        "private_audit_delivery_jobs_pending_idx",
        "audit_delivery_jobs",
        ["status", "next_attempt_at", "created_at"],
        schema="private",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute("GRANT USAGE ON SCHEMA private TO trace_internal")
    op.execute(
        "GRANT SELECT, UPDATE, DELETE ON private.audit_delivery_jobs TO trace_internal"
    )
    op.execute("GRANT USAGE ON SCHEMA private TO trace_app")
    op.execute("REVOKE ALL ON private.audit_delivery_jobs FROM trace_app")
    op.execute("GRANT INSERT ON private.audit_delivery_jobs TO trace_app")
    op.execute(
        "GRANT SELECT (event_id, event_hash, status) "
        "ON private.audit_delivery_jobs TO trace_app"
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON private.audit_delivery_jobs FROM trace_app")
    op.execute("REVOKE ALL ON private.audit_delivery_jobs FROM trace_internal")
    op.execute("REVOKE USAGE ON SCHEMA private FROM trace_internal")
    op.drop_index(
        "private_audit_delivery_jobs_pending_idx",
        table_name="audit_delivery_jobs",
        schema="private",
    )
    op.drop_table("audit_delivery_jobs", schema="private")
    op.execute("DROP TYPE private.audit_delivery_status")
