"""Create durable owner-scoped notifications.

Revision ID: 20261026_0030
Revises: 20261025_0029
"""

from alembic import op

revision = "20261026_0030"
down_revision = "20261025_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE public.notification_category AS ENUM ('info', 'security', 'warning')"
    )
    op.execute(
        "CREATE TYPE public.notification_event_type AS ENUM "
        "('review_queued', 'review_completed', 'review_failed', 'account_registered', "
        "'email_verified', 'password_reset', 'password_signed_in', 'oauth_signed_in', "
        "'logged_out', 'github_connected')"
    )
    op.execute(
        """
        CREATE TABLE public.notifications (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          category public.notification_category NOT NULL,
          event_type public.notification_event_type NOT NULL,
          title text NOT NULL CONSTRAINT notifications_title_length CHECK (length(title) BETWEEN 1 AND 200),
          body text NOT NULL CONSTRAINT notifications_body_length CHECK (length(body) BETWEEN 1 AND 2000),
          action_path text NULL CONSTRAINT notifications_action_path_relative CHECK (action_path IS NULL OR action_path ~ '^/[^/].*'),
          data jsonb NOT NULL DEFAULT '{}'::jsonb CONSTRAINT notifications_data_object CHECK (jsonb_typeof(data) = 'object'),
          dedupe_key text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          read_at timestamptz NULL,
          CONSTRAINT notifications_owner_dedupe_key UNIQUE (owner_id, dedupe_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX notifications_owner_created_idx ON public.notifications(owner_id, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX notifications_owner_unread_idx ON public.notifications(owner_id, created_at DESC) WHERE read_at IS NULL"
    )
    op.execute("ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY notifications_owner_isolation ON public.notifications "
        "USING (owner_id = public.trace_current_user_id()) "
        "WITH CHECK (owner_id = public.trace_current_user_id())"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON public.notifications TO trace_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON public.notifications TO trace_internal")


def downgrade() -> None:
    op.execute("DROP TABLE public.notifications")
    op.execute("DROP TYPE public.notification_event_type")
    op.execute("DROP TYPE public.notification_category")
