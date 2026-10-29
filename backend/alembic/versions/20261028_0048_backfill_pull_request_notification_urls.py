"""Backfill PR notification action paths from persisted remediation metadata.

Revision ID: 20261028_0048
Revises: 20261028_0047
"""

from alembic import op

revision = "20261028_0048"
down_revision = "20261028_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE public.notifications AS notification
        SET action_path = remediation.pull_request ->> 'url'
        FROM public.remediations AS remediation
        WHERE notification.event_type = 'pull_request_created'
          AND notification.owner_id = remediation.owner_id
          AND notification.data ->> 'remediation_id' = remediation.id::text
          AND remediation.pull_request IS NOT NULL
          AND remediation.pull_request ? 'url'
          AND remediation.pull_request ->> 'url' ~ '^https://[^/?#]+/[^?#]+$'
        """
    )


def downgrade() -> None:
    # Preserve the created-notification history on rollback.
    pass
