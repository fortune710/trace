"""Align resource indexes and finding status with the model contract."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261007_0013"
down_revision = "20261007_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial resource migration created one generic owner index per
    # table.  Keep the indexes used by the model contract instead: ordered
    # collection indexes for resources with timestamps and relationship
    # indexes for assignment/category rows.
    owner_index_tables = (
        "agents",
        "review_runs",
        "findings",
        "remediations",
        "pull_requests",
        "local_file_backups",
    )
    for table in owner_index_tables:
        op.execute(f"DROP INDEX IF EXISTS public.{table}_owner_idx")
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_owner_created_idx "
            f"ON public.{table} (owner_id, created_at DESC)"
        )

    op.execute("DROP INDEX IF EXISTS public.external_repositories_owner_idx")

    op.execute("DROP INDEX IF EXISTS public.review_run_agents_owner_idx")
    op.execute(
        "CREATE INDEX IF NOT EXISTS review_run_agents_owner_run_idx "
        "ON public.review_run_agents (owner_id, review_run_id)"
    )

    op.execute("DROP INDEX IF EXISTS public.review_run_categories_owner_idx")
    op.execute(
        "CREATE INDEX IF NOT EXISTS review_run_categories_owner_run_idx "
        "ON public.review_run_categories (owner_id, review_run_id)"
    )

    op.add_column(
        "findings",
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "accepted",
                "resolved",
                "dismissed",
                name="finding_status",
                schema="public",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'open'::public.finding_status"),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("findings", "status", schema="public")

    op.execute("DROP INDEX IF EXISTS public.review_run_categories_owner_run_idx")
    op.execute(
        "CREATE INDEX IF NOT EXISTS review_run_categories_owner_idx "
        "ON public.review_run_categories (owner_id)"
    )

    op.execute("DROP INDEX IF EXISTS public.review_run_agents_owner_run_idx")
    op.execute(
        "CREATE INDEX IF NOT EXISTS review_run_agents_owner_idx "
        "ON public.review_run_agents (owner_id)"
    )

    for table in (
        "local_file_backups",
        "pull_requests",
        "remediations",
        "findings",
        "review_runs",
        "agents",
    ):
        op.execute(f"DROP INDEX IF EXISTS public.{table}_owner_created_idx")
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_owner_idx ON public.{table} (owner_id)"
        )
