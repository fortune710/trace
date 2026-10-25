"""Allow review lifecycle updates through the immutable snapshot trigger.

Revision ID: 20261024_0026
Revises: 20261024_0025
Create Date: 2026-10-24
"""

from __future__ import annotations

from alembic import op

revision = "20261024_0026"
down_revision = "20261024_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep snapshots immutable without blocking their lifecycle columns."""

    op.execute(
        """
        DROP TRIGGER IF EXISTS review_agents_snapshot_immutable ON public.review_agents;
        DROP TRIGGER IF EXISTS reviews_snapshot_immutable ON public.reviews;
        CREATE OR REPLACE FUNCTION public.trace_prevent_review_snapshot_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
          IF TG_TABLE_NAME = 'reviews' THEN
            IF NEW.source_revision IS DISTINCT FROM OLD.source_revision OR
               NEW.source_kind IS DISTINCT FROM OLD.source_kind OR
               NEW.source_identifier IS DISTINCT FROM OLD.source_identifier OR
               NEW.integrity_algorithm IS DISTINCT FROM OLD.integrity_algorithm OR
               NEW.source_captured_at IS DISTINCT FROM OLD.source_captured_at THEN
              RAISE EXCEPTION 'review source snapshot is immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'review_agents' THEN
            IF NEW.agent_id IS DISTINCT FROM OLD.agent_id OR
               NEW.agent_display_name IS DISTINCT FROM OLD.agent_display_name OR
               NEW.agent_specialization IS DISTINCT FROM OLD.agent_specialization OR
               NEW.agent_model_provider IS DISTINCT FROM OLD.agent_model_provider OR
               NEW.agent_model_name IS DISTINCT FROM OLD.agent_model_name OR
               NEW.agent_personality IS DISTINCT FROM OLD.agent_personality OR
               NEW.agent_skills IS DISTINCT FROM OLD.agent_skills OR
               NEW.agent_configuration_version IS DISTINCT FROM OLD.agent_configuration_version THEN
              RAISE EXCEPTION 'review agent snapshot is immutable';
            END IF;
          END IF;
          RETURN NEW;
        END
        $function$;
        CREATE TRIGGER reviews_snapshot_immutable
          BEFORE UPDATE ON public.reviews
          FOR EACH ROW EXECUTE FUNCTION public.trace_prevent_review_snapshot_mutation();
        CREATE TRIGGER review_agents_snapshot_immutable
          BEFORE UPDATE ON public.review_agents
          FOR EACH ROW EXECUTE FUNCTION public.trace_prevent_review_snapshot_mutation();
        DROP FUNCTION IF EXISTS public.trace_prevent_review_source_mutation();
        DROP FUNCTION IF EXISTS public.trace_prevent_review_agent_snapshot_mutation();
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON private.review_agent_attempts "
        "TO trace_internal"
    )
    op.execute("REVOKE DELETE ON private.review_agent_attempts FROM trace_internal")


def downgrade() -> None:
    """Restore the prior table-specific trigger functions and bindings."""

    op.execute(
        """
        DROP TRIGGER IF EXISTS review_agents_snapshot_immutable ON public.review_agents;
        DROP TRIGGER IF EXISTS reviews_snapshot_immutable ON public.reviews;
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
        DROP FUNCTION IF EXISTS public.trace_prevent_review_snapshot_mutation();
        """
    )
    op.execute("GRANT DELETE ON private.review_agent_attempts TO trace_internal")
