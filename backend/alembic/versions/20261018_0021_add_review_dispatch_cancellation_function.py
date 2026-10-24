"""Permit owner-checked terminal cancellation of private review dispatch jobs.

Revision ID: 20261018_0021
Revises: 20261017_0020
Create Date: 2026-10-18
"""

from __future__ import annotations

from alembic import op

revision = "20261018_0021"
down_revision = "20261017_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION private.cancel_review_dispatch_jobs(
          requested_owner_id uuid,
          requested_review_id uuid
        )
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public, private
        AS $fn$
        DECLARE
          affected integer;
        BEGIN
          IF public.trace_current_user_id() IS DISTINCT FROM requested_owner_id THEN
            RAISE EXCEPTION 'review dispatch cancellation owner mismatch'
              USING ERRCODE = '42501';
          END IF;

          UPDATE private.review_dispatch_jobs AS job
          SET status = 'dead_letter'::private.review_dispatch_status,
              failure_code = 'review_cancelled',
              next_attempt_at = NULL,
              updated_at = CURRENT_TIMESTAMP
          FROM public.reviews AS review
          WHERE job.owner_id = requested_owner_id
            AND job.review_id = requested_review_id
            AND review.owner_id = requested_owner_id
            AND review.id = requested_review_id
            AND review.status = 'cancelled'::public.review_status
            AND job.status IN (
              'pending'::private.review_dispatch_status,
              'processing'::private.review_dispatch_status
            );
          GET DIAGNOSTICS affected = ROW_COUNT;
          RETURN affected;
        END;
        $fn$;
        REVOKE ALL ON FUNCTION private.cancel_review_dispatch_jobs(uuid, uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION private.cancel_review_dispatch_jobs(uuid, uuid) TO trace_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL ON FUNCTION private.cancel_review_dispatch_jobs(uuid, uuid) FROM trace_app;
        DROP FUNCTION IF EXISTS private.cancel_review_dispatch_jobs(uuid, uuid);
        """
    )
