"""Add first-findings notification support and review ordering index.

Revision ID: 20261026_0031
Revises: 20261026_0030
"""

from alembic import op

revision = "20261026_0031"
down_revision = "20261026_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE public.notification_event_type "
        "ADD VALUE IF NOT EXISTS 'findings_available'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS findings_owner_review_created_idx "
        "ON public.findings(owner_id, review_id, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.findings_owner_review_created_idx")
