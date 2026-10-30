"""Add the notification event emitted when a review starts.

Revision ID: 20261029_0051
Revises: 20261029_0050
"""

from alembic import op

revision = "20261029_0051"
down_revision = "20261029_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE public.notification_event_type "
        "ADD VALUE IF NOT EXISTS 'review_started'"
    )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in place.
    pass
