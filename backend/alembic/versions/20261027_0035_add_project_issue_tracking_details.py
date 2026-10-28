"""Store provider-neutral issue-tracking destinations on projects.

Revision ID: 20261027_0035
Revises: 20261027_0034
"""

from alembic import op

revision = "20261027_0035"
down_revision = "20261027_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.projects
          ADD COLUMN issue_tracking_details jsonb NOT NULL
          DEFAULT '{"connected_projects":[]}'::jsonb,
          ADD CONSTRAINT projects_issue_tracking_details_shape_check CHECK (
            jsonb_typeof(issue_tracking_details) = 'object'
            AND issue_tracking_details ? 'connected_projects'
            AND jsonb_typeof(issue_tracking_details -> 'connected_projects') = 'array'
          );
        """
    )
    op.execute(
        """
        UPDATE public.projects
        SET issue_tracking_details = jsonb_build_object(
          'connected_projects',
          CASE
            WHEN source = 'github'
              AND repository_owner IS NOT NULL
              AND repository_name IS NOT NULL
            THEN jsonb_build_array(jsonb_build_object(
              'provider', source::text,
              'owner', repository_owner,
              'project', repository_name
            ))
            ELSE '[]'::jsonb
          END
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.projects
          DROP CONSTRAINT projects_issue_tracking_details_shape_check,
          DROP COLUMN issue_tracking_details;
        """
    )
