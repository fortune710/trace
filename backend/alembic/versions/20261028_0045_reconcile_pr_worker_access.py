"""Reconcile persisted databases with remediation PR worker requirements.

Revision ID: 20261028_0045
Revises: 20261028_0044
"""

from alembic import op

revision = "20261028_0045"
down_revision = "20261028_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('public.local_file_backups') IS NOT NULL
             AND NOT EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = 'local_file_backups'
                 AND column_name = 'applied_hash'
             ) THEN
            ALTER TABLE public.local_file_backups ADD COLUMN applied_hash bytea;
            UPDATE public.local_file_backups
              SET applied_hash = source_hash
              WHERE applied_hash IS NULL;
            ALTER TABLE public.local_file_backups
              ALTER COLUMN applied_hash SET NOT NULL;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.local_project_handles (
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
        "CREATE INDEX IF NOT EXISTS local_project_handles_owner_created_idx "
        "ON public.local_project_handles (owner_id, created_at DESC)"
    )
    op.execute("ALTER TABLE public.local_project_handles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.local_project_handles FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = 'local_project_handles'
              AND policyname = 'local_project_handles_owner_isolation'
          ) THEN
            CREATE POLICY local_project_handles_owner_isolation
              ON public.local_project_handles
              USING (owner_id = public.trace_current_user_id())
              WITH CHECK (owner_id = public.trace_current_user_id());
          END IF;
        END $$;
        """
    )
    op.execute("REVOKE ALL ON public.local_project_handles FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON public.local_project_handles "
        "TO trace_app"
    )
    op.execute(
        "GRANT SELECT (id, automatic_pull_requests) ON public.users "
        "TO trace_internal"
    )
    op.execute(
        "GRANT SELECT (id, owner_id, source, external_repository_id, branch_name) "
        "ON public.projects TO trace_internal"
    )
    op.execute(
        "GRANT SELECT (id, owner_id, review_id, status, title) "
        "ON public.findings TO trace_internal"
    )
    op.execute("GRANT SELECT, UPDATE ON public.remediations TO trace_internal")
    op.execute(
        "GRANT INSERT (id, owner_id, project_id, finding_id, prompt_text, "
        "proposed_diff, status) ON public.remediations TO trace_internal"
    )
    op.execute(
        "GRANT INSERT (idempotency_id, owner_id, remediation_id) "
        "ON private.remediation_pull_request_outbox_jobs TO trace_internal"
    )
    op.execute(
        "GRANT SELECT, UPDATE, DELETE "
        "ON private.remediation_pull_request_outbox_jobs TO trace_internal"
    )
    op.execute(
        "GRANT INSERT (id, owner_id, remediation_id) "
        "ON private.remediation_pull_request_jobs TO trace_app"
    )
    op.execute(
        "GRANT SELECT (id, owner_id, remediation_id) "
        "ON private.remediation_pull_request_jobs TO trace_app"
    )
    op.execute(
        "GRANT INSERT (id, owner_id, remediation_id) "
        "ON private.remediation_pull_request_jobs TO trace_internal"
    )
    op.execute(
        "GRANT SELECT (id, owner_id, remediation_id) "
        "ON private.remediation_pull_request_jobs TO trace_internal"
    )
    op.execute(
        "GRANT INSERT (event_id, owner_id, canonical_json, event_hash, status) "
        "ON private.audit_delivery_jobs TO trace_app"
    )
    op.execute(
        "GRANT SELECT (event_id, event_hash, status) "
        "ON private.audit_delivery_jobs TO trace_app"
    )
    op.execute(
        "GRANT INSERT (event_id, owner_id, canonical_json, event_hash, status) "
        "ON private.audit_delivery_jobs TO trace_internal"
    )


def downgrade() -> None:
    """Preserve compatible pre-existing schema and grants on rollback."""
