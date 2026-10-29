"""Add remediation pull-request notification events.

Revision ID: 20261028_0046
Revises: 20261028_0045
"""

from alembic import op

revision = "20261028_0046"
down_revision = "20261028_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE public.notification_event_type "
        "ADD VALUE IF NOT EXISTS 'pull_request_created'"
    )
    op.execute(
        "ALTER TYPE public.notification_event_type "
        "ADD VALUE IF NOT EXISTS 'pull_request_creation_failed'"
    )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in place.
    pass
