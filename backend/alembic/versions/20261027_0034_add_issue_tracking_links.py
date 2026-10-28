"""Add provider-neutral external issue links.

Revision ID: 20261027_0034
Revises: 20261027_0033
"""

from alembic import op

revision = "20261027_0034"
down_revision = "20261027_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE private.credential_provider ADD VALUE IF NOT EXISTS 'linear'"
    )
    op.execute("CREATE TYPE public.issue_provider_name AS ENUM ('github', 'linear')")
    op.execute(
        "CREATE TYPE public.issue_link_state AS ENUM ('pending', 'created', 'failed')"
    )
    op.execute(
        """
        CREATE TABLE public.issue_links (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          finding_id uuid NOT NULL,
          provider public.issue_provider_name NOT NULL,
          destination_id text NOT NULL,
          external_identifier text NULL,
          external_url text NULL,
          state public.issue_link_state NOT NULL DEFAULT 'pending'::public.issue_link_state,
          failure_code text NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT issue_links_owner_id_id_key UNIQUE(owner_id, id),
          CONSTRAINT issue_links_owner_finding_fkey
            FOREIGN KEY(owner_id, finding_id)
            REFERENCES public.findings(owner_id, id) ON DELETE CASCADE,
          CONSTRAINT issue_links_owner_finding_provider_destination_key
            UNIQUE(owner_id, finding_id, provider, destination_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX issue_links_owner_finding_provider_idx "
        "ON public.issue_links(owner_id, finding_id, provider)"
    )
    op.execute(
        """
        ALTER TABLE public.issue_links ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.issue_links FORCE ROW LEVEL SECURITY;
        CREATE POLICY issue_links_owner_isolation ON public.issue_links
          USING (owner_id = public.trace_current_user_id())
          WITH CHECK (owner_id = public.trace_current_user_id());
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.issue_links TO trace_app;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_issue_link_exists(resource_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $fn$
          SELECT EXISTS(SELECT 1 FROM public.issue_links AS resource WHERE resource.id = $1)
        $fn$;
        REVOKE ALL ON FUNCTION public.trace_issue_link_exists(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.trace_issue_link_exists(uuid) TO trace_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.trace_issue_link_exists(uuid)")
    op.execute("DROP TABLE public.issue_links")
    op.execute("DROP TYPE public.issue_link_state")
    op.execute("DROP TYPE public.issue_provider_name")
    # PostgreSQL cannot remove an enum value safely; retain the unused
    # credential_provider 'linear' label when downgrading.
