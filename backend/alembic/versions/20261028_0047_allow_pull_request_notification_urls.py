"""Allow trusted HTTPS pull-request URLs in notification action paths.

Revision ID: 20261028_0047
Revises: 20261028_0046
"""

from alembic import op

revision = "20261028_0047"
down_revision = "20261028_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Commit the values added by 0046 before this migration casts one of them.
    # PostgreSQL rejects use of an enum value added in the current transaction.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE public.notification_event_type "
            "ADD VALUE IF NOT EXISTS 'pull_request_created'"
        )
        op.execute(
            "ALTER TYPE public.notification_event_type "
            "ADD VALUE IF NOT EXISTS 'pull_request_creation_failed'"
        )
    op.execute(
        "ALTER TABLE public.notifications "
        "DROP CONSTRAINT notifications_action_path_relative"
    )
    op.execute(
        "ALTER TABLE public.notifications "
        "ADD CONSTRAINT notifications_action_path_relative CHECK ("
        "action_path IS NULL OR action_path ~ '^/[^/].*' OR "
        "(event_type = 'pull_request_created'::public.notification_event_type "
        "AND action_path ~ '^https://[^/?#]+/[^?#]+$')"
        ")"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.notifications "
        "DROP CONSTRAINT notifications_action_path_relative"
    )
    op.execute(
        "ALTER TABLE public.notifications "
        "ADD CONSTRAINT notifications_action_path_relative "
        "CHECK (action_path IS NULL OR action_path ~ '^/[^/].*')"
    )
