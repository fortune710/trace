"""Add durable automatic remediation pull-request outbox jobs.

Revision ID: 20261028_0042
Revises: 20261028_0041
"""

from alembic import op

revision = "20261028_0042"
down_revision = "20261028_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE private.remediation_pull_request_outbox_status AS ENUM "
        "('waiting_for_acceptance', 'pending', 'publishing', 'published', "
        "'cancelled', 'dead_letter')"
    )
    op.execute(
        """
        CREATE TABLE private.remediation_pull_request_outbox_jobs (
          idempotency_id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL,
          remediation_id uuid NOT NULL,
          status private.remediation_pull_request_outbox_status NOT NULL
            DEFAULT 'waiting_for_acceptance'::private.remediation_pull_request_outbox_status,
          attempt_count integer NOT NULL DEFAULT 0,
          next_attempt_at timestamptz NULL,
          claimed_at timestamptz NULL,
          published_at timestamptz NULL,
          failure_code text NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT remediation_pr_outbox_owner_remediation_key
            UNIQUE (owner_id, remediation_id),
          CONSTRAINT remediation_pr_outbox_attempts_check
            CHECK (attempt_count >= 0 AND attempt_count <= 3),
          CONSTRAINT remediation_pr_outbox_failure_code_check CHECK (
            failure_code IS NULL OR failure_code ~ '^[a-z0-9_]{1,64}$'
          ),
          CONSTRAINT remediation_pr_outbox_owner_remediation_fkey
            FOREIGN KEY (owner_id, remediation_id)
            REFERENCES public.remediations(owner_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX private_remediation_pr_outbox_pending_claim_idx
          ON private.remediation_pull_request_outbox_jobs
             (status, next_attempt_at, created_at, idempotency_id)
          WHERE status = 'pending'::private.remediation_pull_request_outbox_status
        """
    )
    op.execute("GRANT USAGE ON SCHEMA private TO trace_app")
    op.execute("GRANT USAGE ON SCHEMA private TO trace_internal")
    op.execute("REVOKE ALL ON private.remediation_pull_request_outbox_jobs FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON private.remediation_pull_request_outbox_jobs FROM trace_app"
    )
    op.execute(
        "GRANT INSERT ON private.remediation_pull_request_outbox_jobs TO trace_app"
    )
    op.execute(
        "GRANT SELECT, UPDATE, DELETE ON private.remediation_pull_request_outbox_jobs "
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


def downgrade() -> None:
    op.execute("REVOKE SELECT, UPDATE ON public.remediations FROM trace_internal")
    op.execute(
        "REVOKE SELECT (id, owner_id, review_id, status, title) "
        "ON public.findings FROM trace_internal"
    )
    op.execute(
        "REVOKE SELECT (id, owner_id, source, external_repository_id, branch_name) "
        "ON public.projects FROM trace_internal"
    )
    op.execute("DROP TABLE private.remediation_pull_request_outbox_jobs")
    op.execute("DROP TYPE private.remediation_pull_request_outbox_status")
