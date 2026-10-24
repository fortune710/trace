"""Add immutable review source and agent snapshots.

Revision ID: 20261021_0023
Revises: 20261018_0022
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision = "20261021_0023"
down_revision = "20261018_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
          IF EXISTS (SELECT 1 FROM public.reviews)
             OR EXISTS (SELECT 1 FROM public.review_agents) THEN
            RAISE EXCEPTION
              'review snapshot migration requires empty review tables; refusing unsafe backfill';
          END IF;
        END
        $block$;
        """
    )
    op.execute(
        "ALTER TABLE public.agents "
        "ADD COLUMN configuration_version integer NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE public.reviews "
        "ADD COLUMN source_kind public.repository_source NOT NULL, "
        "ADD COLUMN source_identifier text NOT NULL, "
        "ADD COLUMN integrity_algorithm text NOT NULL, "
        "ADD COLUMN source_captured_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )
    op.execute(
        """
        ALTER TABLE public.reviews
        ADD CONSTRAINT reviews_source_snapshot_check CHECK (
          (source_kind = 'github' AND integrity_algorithm = 'git-commit-sha1-v1'
            AND source_revision ~ '^[0-9a-f]{40}$')
          OR
          (source_kind = 'local' AND integrity_algorithm = 'sha256-directory-manifest-v1'
            AND source_revision ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        """
        ALTER TABLE public.review_agents
        ADD COLUMN agent_display_name text NOT NULL,
        ADD COLUMN agent_specialization public.review_category NOT NULL,
        ADD COLUMN agent_model_provider text NOT NULL,
        ADD COLUMN agent_model_name text NOT NULL,
        ADD COLUMN agent_personality text NULL,
        ADD COLUMN agent_skills jsonb NOT NULL DEFAULT '[]'::jsonb,
        ADD COLUMN agent_configuration_version integer NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX reviews_owner_project_idx ON public.reviews(owner_id, project_id)"
    )
    op.execute(
        "CREATE INDEX reviews_owner_source_revision_idx "
        "ON public.reviews(owner_id, source_kind, source_revision)"
    )
    op.execute(
        "CREATE INDEX review_agents_owner_agent_idx "
        "ON public.review_agents(owner_id, agent_id)"
    )
    op.execute(
        "CREATE TYPE private.review_agent_attempt_status "
        "AS ENUM ('started', 'succeeded', 'failed')"
    )
    op.execute(
        """
        CREATE TABLE private.review_agent_attempts (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL,
          review_id uuid NOT NULL,
          review_agent_id uuid NOT NULL,
          attempt_number integer NOT NULL,
          status private.review_agent_attempt_status NOT NULL,
          provider_request_id text NULL,
          retry_count integer NOT NULL DEFAULT 0,
          failure_code text NULL,
          started_at timestamptz NOT NULL,
          completed_at timestamptz NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT review_agent_attempts_owner_number_key
            UNIQUE(owner_id, review_agent_id, attempt_number),
          CONSTRAINT review_agent_attempts_number_check CHECK(attempt_number >= 1),
          CONSTRAINT review_agent_attempts_retry_check CHECK(retry_count >= 0),
          CONSTRAINT review_agent_attempts_failure_code_check CHECK(
            failure_code IS NULL OR failure_code ~ '^[a-z0-9_]{1,64}$'
          ),
          CONSTRAINT review_agent_attempts_owner_assignment_fkey
            FOREIGN KEY(owner_id, review_id, review_agent_id)
            REFERENCES public.review_agents(owner_id, review_id, id)
            ON DELETE CASCADE
        )
        """
    )
    # NB: one trigger function shared by both tables cannot work: PL/pgSQL
    # resolves NEW/OLD field references against the first table's row type
    # the function is planned with, so an UPDATE on reviews failed with
    # 'record "new" has no field "agent_id"' (and vice versa for
    # source_revision on review_agents). Keep one function per table, each
    # referencing only its own table's columns.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_prevent_review_source_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
          IF (
            NEW.source_revision IS DISTINCT FROM OLD.source_revision OR
            NEW.source_kind IS DISTINCT FROM OLD.source_kind OR
            NEW.source_identifier IS DISTINCT FROM OLD.source_identifier OR
            NEW.integrity_algorithm IS DISTINCT FROM OLD.integrity_algorithm OR
            NEW.source_captured_at IS DISTINCT FROM OLD.source_captured_at
          ) THEN
            RAISE EXCEPTION 'review source snapshot is immutable';
          END IF;
          RETURN NEW;
        END
        $function$;
        CREATE TRIGGER reviews_snapshot_immutable
          BEFORE UPDATE ON public.reviews
          FOR EACH ROW EXECUTE FUNCTION public.trace_prevent_review_source_mutation();
        CREATE OR REPLACE FUNCTION public.trace_prevent_review_agent_snapshot_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
          IF (
            NEW.agent_id IS DISTINCT FROM OLD.agent_id OR
            NEW.agent_display_name IS DISTINCT FROM OLD.agent_display_name OR
            NEW.agent_specialization IS DISTINCT FROM OLD.agent_specialization OR
            NEW.agent_model_provider IS DISTINCT FROM OLD.agent_model_provider OR
            NEW.agent_model_name IS DISTINCT FROM OLD.agent_model_name OR
            NEW.agent_personality IS DISTINCT FROM OLD.agent_personality OR
            NEW.agent_skills IS DISTINCT FROM OLD.agent_skills OR
            NEW.agent_configuration_version IS DISTINCT FROM OLD.agent_configuration_version
          ) THEN
            RAISE EXCEPTION 'review agent snapshot is immutable';
          END IF;
          RETURN NEW;
        END
        $function$;
        CREATE TRIGGER review_agents_snapshot_immutable
          BEFORE UPDATE ON public.review_agents
          FOR EACH ROW EXECUTE FUNCTION public.trace_prevent_review_agent_snapshot_mutation();
        """
    )
    # The app (trace_app) and worker (trace_internal) roles both touch
    # attempt rows; default privileges cover trace_app only, so grant both
    # explicitly, as 0020 did for private.review_dispatch_jobs.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON private.review_agent_attempts TO trace_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON private.review_agent_attempts TO trace_internal"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS review_agents_snapshot_immutable ON public.review_agents"
    )
    op.execute("DROP TRIGGER IF EXISTS reviews_snapshot_immutable ON public.reviews")
    op.execute(
        "DROP FUNCTION IF EXISTS public.trace_prevent_review_agent_snapshot_mutation()"
    )
    op.execute("DROP FUNCTION IF EXISTS public.trace_prevent_review_source_mutation()")
    op.execute(
        "DROP FUNCTION IF EXISTS public.trace_prevent_review_snapshot_mutation()"
    )
    op.execute("DROP TABLE private.review_agent_attempts")
    op.execute("DROP TYPE private.review_agent_attempt_status")
    op.execute("DROP INDEX public.review_agents_owner_agent_idx")
    op.execute("DROP INDEX public.reviews_owner_source_revision_idx")
    op.execute("DROP INDEX public.reviews_owner_project_idx")
    op.execute(
        "ALTER TABLE public.review_agents DROP COLUMN agent_configuration_version"
    )
    op.execute("ALTER TABLE public.review_agents DROP COLUMN agent_skills")
    op.execute("ALTER TABLE public.review_agents DROP COLUMN agent_personality")
    op.execute("ALTER TABLE public.review_agents DROP COLUMN agent_model_name")
    op.execute("ALTER TABLE public.review_agents DROP COLUMN agent_model_provider")
    op.execute("ALTER TABLE public.review_agents DROP COLUMN agent_specialization")
    op.execute("ALTER TABLE public.review_agents DROP COLUMN agent_display_name")
    op.execute(
        "ALTER TABLE public.reviews DROP CONSTRAINT reviews_source_snapshot_check"
    )
    op.execute("ALTER TABLE public.reviews DROP COLUMN source_captured_at")
    op.execute("ALTER TABLE public.reviews DROP COLUMN integrity_algorithm")
    op.execute("ALTER TABLE public.reviews DROP COLUMN source_identifier")
    op.execute("ALTER TABLE public.reviews DROP COLUMN source_kind")
    op.execute("ALTER TABLE public.agents DROP COLUMN configuration_version")
