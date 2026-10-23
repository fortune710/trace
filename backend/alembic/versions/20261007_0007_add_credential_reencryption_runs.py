"""Add durable credential re-encryption runs and the maintenance role."""

from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261007_0007"
down_revision = "20261007_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    maintenance_password = os.getenv("TRACE_CREDENTIAL_MAINTENANCE_PASSWORD")
    if not maintenance_password:
        raise RuntimeError(
            "TRACE_CREDENTIAL_MAINTENANCE_PASSWORD must be set before migrations"
        )

    connection = op.get_bind()
    connection.execute(
        sa.text("SELECT set_config('trace.maintenance_password', :password, true)"),
        {"password": maintenance_password},
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_roles WHERE rolname = 'trace_credential_maintenance'
          ) THEN
            EXECUTE format(
              'ALTER ROLE trace_credential_maintenance LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS PASSWORD %L',
              current_setting('trace.maintenance_password')
            );
          ELSE
            EXECUTE format(
              'CREATE ROLE trace_credential_maintenance LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS PASSWORD %L',
              current_setting('trace.maintenance_password')
            );
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          EXECUTE format(
            'GRANT CONNECT ON DATABASE %I TO trace_credential_maintenance',
            current_database()
          );
        END $$;
        """
    )
    op.execute(
        "CREATE TYPE private.credential_reencryption_status AS ENUM ('running', 'completed', 'failed')"
    )
    op.execute(
        "CREATE TYPE private.credential_reencryption_item_status AS ENUM ('pending', 'rewrapped', 'skipped', 'retryable', 'failed')"
    )
    op.create_table(
        "credential_reencryption_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "completed",
                "failed",
                name="credential_reencryption_status",
                schema="private",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'running'::private.credential_reencryption_status"),
        ),
        sa.Column(
            "encryption_provider",
            sa.Enum(
                "local",
                "vault",
                name="credential_encryption_provider",
                schema="private",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("target_key_reference", sa.Text(), nullable=False),
        sa.Column("target_key_version", sa.Text(), nullable=False),
        sa.Column(
            "last_credential_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rewrapped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="credential_reencryption_runs_pkey"),
        schema="private",
    )
    op.create_table(
        "credential_reencryption_items",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "rewrapped",
                "skipped",
                "retryable",
                "failed",
                name="credential_reencryption_item_status",
                schema="private",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text(
                "'pending'::private.credential_reencryption_item_status"
            ),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["private.credential_reencryption_runs.id"],
            name="credential_reencryption_items_run_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["private.credentials.id"],
            name="credential_reencryption_items_credential_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "credential_id", name="credential_reencryption_items_pkey"
        ),
        schema="private",
    )
    op.create_index(
        "credential_reencryption_items_retry_idx",
        "credential_reencryption_items",
        ["run_id", "status", "next_attempt_at"],
        schema="private",
    )
    op.execute(
        "REVOKE ALL ON private.credential_reencryption_runs, private.credential_reencryption_items FROM trace_app"
    )
    op.execute(
        "REVOKE ALL ON private.credential_reencryption_runs, private.credential_reencryption_items FROM trace_internal"
    )
    op.execute("GRANT USAGE ON SCHEMA private TO trace_credential_maintenance")
    op.execute(
        "GRANT SELECT, UPDATE ON private.credentials TO trace_credential_maintenance"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON private.credential_reencryption_runs, private.credential_reencryption_items TO trace_credential_maintenance"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE ALL ON private.credentials, private.credential_reencryption_runs, private.credential_reencryption_items FROM trace_credential_maintenance"
    )
    op.execute("REVOKE USAGE ON SCHEMA private FROM trace_credential_maintenance")
    op.drop_index(
        "credential_reencryption_items_retry_idx",
        table_name="credential_reencryption_items",
        schema="private",
    )
    op.drop_table("credential_reencryption_items", schema="private")
    op.drop_table("credential_reencryption_runs", schema="private")
    op.execute("DROP TYPE private.credential_reencryption_item_status")
    op.execute("DROP TYPE private.credential_reencryption_status")
    op.execute("DROP ROLE IF EXISTS trace_credential_maintenance")
