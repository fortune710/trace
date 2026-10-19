"""Persist idempotency metadata for explicit review submission.

Revision ID: 20261017_0018
Revises: 20261017_0017
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261017_0018"
down_revision = "20261017_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_runs",
        sa.Column(
            "idempotency_id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("public.uuidv7()"),
        ),
        schema="public",
    )
    op.add_column(
        "review_runs",
        sa.Column("idempotency_key_digest", sa.LargeBinary(), nullable=True),
        schema="public",
    )
    op.add_column(
        "review_runs",
        sa.Column("request_digest", sa.LargeBinary(), nullable=True),
        schema="public",
    )
    op.create_unique_constraint(
        "review_runs_owner_idempotency_id_key",
        "review_runs",
        ["owner_id", "idempotency_id"],
        schema="public",
    )
    op.create_index(
        "review_runs_owner_idempotency_key_unique",
        "review_runs",
        ["owner_id", "idempotency_key_digest"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("idempotency_key_digest IS NOT NULL"),
    )

    op.add_column(
        "review_run_agents",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("public.uuidv7()"),
        ),
        schema="public",
    )
    op.create_unique_constraint(
        "review_run_agents_owner_id_id_key",
        "review_run_agents",
        ["owner_id", "id"],
        schema="public",
    )

    # This SECURITY DEFINER helper deliberately checks global existence so the
    # request layer can distinguish an absent project (404) from another
    # builder's project (403) without bypassing table RLS for normal access.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_project_exists(resource_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $fn$
          SELECT EXISTS(
            SELECT 1 FROM public.projects AS resource WHERE resource.id = $1
          )
        $fn$;
        REVOKE ALL ON FUNCTION public.trace_project_exists(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.trace_project_exists(uuid) TO trace_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.trace_project_exists(uuid)")
    op.drop_constraint(
        "review_run_agents_owner_id_id_key",
        "review_run_agents",
        schema="public",
        type_="unique",
    )
    op.drop_column("review_run_agents", "id", schema="public")
    op.drop_index(
        "review_runs_owner_idempotency_key_unique",
        "review_runs",
        schema="public",
    )
    op.drop_constraint(
        "review_runs_owner_idempotency_id_key",
        "review_runs",
        schema="public",
        type_="unique",
    )
    op.drop_column("review_runs", "request_digest", schema="public")
    op.drop_column("review_runs", "idempotency_key_digest", schema="public")
    op.drop_column("review_runs", "idempotency_id", schema="public")
