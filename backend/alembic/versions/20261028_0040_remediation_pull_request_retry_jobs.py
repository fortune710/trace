"""Add a durable retry queue for remediation pull-request publication.

Revision ID: 20261028_0040
Revises: 20261028_0039
"""

from alembic import op

revision = "20261028_0040"
down_revision = "20261028_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE private.remediation_pull_request_job_status AS ENUM "
        "('pending', 'processing', 'succeeded', 'dead_letter')"
    )
    op.execute(
        """
        CREATE TABLE private.remediation_pull_request_jobs (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL,
          remediation_id uuid NOT NULL,
          status private.remediation_pull_request_job_status NOT NULL
            DEFAULT 'pending'::private.remediation_pull_request_job_status,
          attempt_count integer NOT NULL DEFAULT 0,
          next_attempt_at timestamptz NULL,
          claimed_at timestamptz NULL,
          succeeded_at timestamptz NULL,
          failure_code text NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT remediation_pull_request_jobs_owner_remediation_key
            UNIQUE (owner_id, remediation_id),
          CONSTRAINT remediation_pull_request_jobs_attempts_check
            CHECK (attempt_count >= 0 AND attempt_count <= 3),
          CONSTRAINT remediation_pull_request_jobs_failure_code_check CHECK (
            failure_code IS NULL OR failure_code ~ '^[a-z0-9_]{1,64}$'
          ),
          CONSTRAINT remediation_pull_request_jobs_owner_remediation_fkey
            FOREIGN KEY (owner_id, remediation_id)
            REFERENCES public.remediations(owner_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX private_remediation_pull_request_jobs_pending_claim_idx
          ON private.remediation_pull_request_jobs
             (status, next_attempt_at, created_at, id)
          WHERE status = 'pending'::private.remediation_pull_request_job_status
        """
    )
    op.execute("GRANT USAGE ON SCHEMA private TO trace_app")
    op.execute("GRANT USAGE ON SCHEMA private TO trace_internal")
    op.execute("REVOKE ALL ON private.remediation_pull_request_jobs FROM PUBLIC")
    op.execute("REVOKE ALL ON private.remediation_pull_request_jobs FROM trace_app")
    op.execute("GRANT INSERT ON private.remediation_pull_request_jobs TO trace_app")
    op.execute(
        "GRANT SELECT, UPDATE, DELETE ON private.remediation_pull_request_jobs "
        "TO trace_internal"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS private.private_remediation_pull_request_jobs_pending_claim_idx"
    )
    op.execute("DROP TABLE private.remediation_pull_request_jobs")
    op.execute("DROP TYPE private.remediation_pull_request_job_status")
