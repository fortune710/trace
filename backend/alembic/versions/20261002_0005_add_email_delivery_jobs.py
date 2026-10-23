"""Add encrypted durable jobs for RabbitMQ email delivery."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261002_0005"
down_revision = "20260930_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE auth.email_delivery_kind AS ENUM ('verification', 'password_recovery')"
    )
    op.execute(
        "CREATE TYPE auth.email_delivery_status AS ENUM ('pending', 'sending', 'sent', 'failed')"
    )
    op.execute(
        "CREATE TYPE auth.email_payload_encryption_provider AS ENUM ('local', 'vault')"
    )
    op.create_table(
        "email_delivery_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("public.uuidv7()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "verification",
                "password_recovery",
                name="email_delivery_kind",
                schema="auth",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sending",
                "sent",
                "failed",
                name="email_delivery_status",
                schema="auth",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending'::auth.email_delivery_status"),
        ),
        sa.Column("payload_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("payload_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("payload_key_version", sa.Text(), nullable=False),
        sa.Column(
            "payload_aad_version",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'v1'"),
        ),
        sa.Column(
            "payload_encryption_provider",
            sa.Enum(
                "local",
                "vault",
                name="email_payload_encryption_provider",
                schema="auth",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("payload_key_reference", sa.Text(), nullable=False),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name="auth_email_delivery_jobs_user_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="auth_email_delivery_jobs_pkey"),
        schema="auth",
    )
    op.execute(
        "CREATE INDEX auth_email_delivery_jobs_pending_created_idx "
        "ON auth.email_delivery_jobs (status, created_at) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.drop_table("email_delivery_jobs", schema="auth")
    op.execute("DROP TYPE auth.email_payload_encryption_provider")
    op.execute("DROP TYPE auth.email_delivery_status")
    op.execute("DROP TYPE auth.email_delivery_kind")
