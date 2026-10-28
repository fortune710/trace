"""Create opaque server ownership handles for desktop-local projects.

Revision ID: 20261028_0044
Revises: 20261028_0043
"""

revision = "20261028_0044"
down_revision = "20261028_0043"
branch_labels = None
depends_on = None


from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.local_project_handles (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          client_project_id uuid NOT NULL,
          issue_tracking_details jsonb NOT NULL
            DEFAULT '{"connected_projects":[]}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT local_project_handles_owner_id_id_key UNIQUE (owner_id, id),
          CONSTRAINT local_project_handles_owner_client_key
            UNIQUE (owner_id, client_project_id),
          CONSTRAINT local_project_handles_issue_tracking_details_shape_check CHECK (
            jsonb_typeof(issue_tracking_details) = 'object'
            AND issue_tracking_details ? 'connected_projects'
            AND jsonb_typeof(issue_tracking_details -> 'connected_projects') = 'array'
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX local_project_handles_owner_created_idx "
        "ON public.local_project_handles (owner_id, created_at DESC)"
    )
    op.execute("ALTER TABLE public.local_project_handles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.local_project_handles FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY local_project_handles_owner_isolation
          ON public.local_project_handles
          USING (owner_id = public.trace_current_user_id())
          WITH CHECK (owner_id = public.trace_current_user_id())
        """
    )
    op.execute("REVOKE ALL ON public.local_project_handles FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.local_project_handles TO trace_app")


def downgrade() -> None:
    op.execute("DROP TABLE public.local_project_handles")
