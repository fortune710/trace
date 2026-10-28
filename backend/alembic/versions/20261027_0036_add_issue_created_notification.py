"""Add issue-created notifications.

Revision ID: 20261027_0036
Revises: 20261027_0035
"""

from alembic import op

revision = "20261027_0036"
down_revision = "20261027_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE public.notification_event_type ADD VALUE IF NOT EXISTS 'issue_created'"
    )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in place.
    pass
