"""Add the current finding triage reason.

Revision ID: 20261027_0033
Revises: 20261027_0032
"""

from alembic import op

revision = "20261027_0033"
down_revision = "20261027_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.findings ADD COLUMN IF NOT EXISTS triage_reason text NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.findings DROP COLUMN IF EXISTS triage_reason")
