"""Remove review-level category selections in favor of agent assignments.

Revision ID: 20261017_0016
Revises: 20261008_0015
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261017_0016"
down_revision = "20261008_0015"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check the current schema without failing on partially provisioned databases."""
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT to_regclass(:table_name) IS NOT NULL"), {
            "table_name": f"public.{table_name}",
        })
        .scalar()
    )


def upgrade() -> None:
    # The review category is now inferred from each explicitly selected agent.
    # The guard makes deployment safe for databases where a previous repair or
    # manual bootstrap already removed this legacy table.
    if _table_exists("review_run_categories"):
        op.drop_table("review_run_categories", schema="public")


def downgrade() -> None:
    # Restore the legacy table only when it is absent, so a repeated downgrade
    # or a manually restored database does not fail.
    if _table_exists("review_run_categories"):
        return

    op.create_table(
        "review_run_categories",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("review_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "security",
                "engineering",
                "product",
                "legal",
                "accessibility",
                name="review_category",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["public.users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_run_id"],
            ["public.review_runs.owner_id", "public.review_runs.id"],
            name="review_run_categories_owner_run_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("review_run_id", "category"),
        schema="public",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS review_run_categories_owner_run_idx "
        "ON public.review_run_categories (owner_id, review_run_id)"
    )
    op.execute(
        "ALTER TABLE public.review_run_categories ENABLE ROW LEVEL SECURITY; "
        "ALTER TABLE public.review_run_categories FORCE ROW LEVEL SECURITY; "
        "DROP POLICY IF EXISTS review_run_categories_owner_isolation "
        "ON public.review_run_categories; "
        "CREATE POLICY review_run_categories_owner_isolation "
        "ON public.review_run_categories "
        "USING (owner_id = public.trace_current_user_id()) "
        "WITH CHECK (owner_id = public.trace_current_user_id()); "
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON public.review_run_categories TO trace_app"
    )
