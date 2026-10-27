"""Add the finding status-query index.

Revision ID: 20261027_0032
Revises: 20261026_0031
"""

from alembic import op

revision = "20261027_0032"
down_revision = "20261026_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS findings_owner_review_status_created_idx "
        "ON public.findings(owner_id, review_id, status, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.findings_owner_review_status_created_idx")
