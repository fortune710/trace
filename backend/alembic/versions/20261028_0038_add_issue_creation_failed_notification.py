"""Add issue-creation-failed notifications.

Revision ID: 20261028_0038
Revises: 20261028_0037
"""

from alembic import op

revision = "20261028_0038"
down_revision = "20261028_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE public.notification_event_type "
        "ADD VALUE IF NOT EXISTS 'issue_creation_failed'"
    )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in place.
    pass
