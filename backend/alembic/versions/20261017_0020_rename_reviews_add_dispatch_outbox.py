"""Rename review persistence and add the identifier-only dispatch outbox.

Revision ID: 20261017_0020
Revises: 20261017_0019
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261017_0020"
down_revision = "20261017_0019"
branch_labels = None
depends_on = None


def _relation_exists(schema: str, name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("SELECT to_regclass(:name) IS NOT NULL"),
            {"name": f"{schema}.{name}"},
        )
        .scalar_one()
    )


def _column_exists(schema: str, table: str, column: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema = :schema
                    AND table_name = :table
                    AND column_name = :column
                )
                """
            ),
            {"schema": schema, "table": table, "column": column},
        )
        .scalar_one()
    )


def _constraint_exists(schema: str, table: str, constraint: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_constraint AS constraint_row
                  JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
                  JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                  WHERE namespace.nspname = :schema
                    AND relation.relname = :table
                    AND constraint_row.conname = :constraint
                )
                """
            ),
            {"schema": schema, "table": table, "constraint": constraint},
        )
        .scalar_one()
    )


def _index_exists(schema: str, index: str) -> bool:
    return _relation_exists(schema, index)


def _policy_exists(schema: str, table: str, policy: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_policies
                  WHERE schemaname = :schema
                    AND tablename = :table
                    AND policyname = :policy
                )
                """
            ),
            {"schema": schema, "table": table, "policy": policy},
        )
        .scalar_one()
    )


def _type_exists(schema: str, type_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("SELECT to_regtype(:name) IS NOT NULL"),
            {"name": f"{schema}.{type_name}"},
        )
        .scalar_one()
    )


def _function_exists(schema: str, signature: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("SELECT to_regprocedure(:signature) IS NOT NULL"),
            {"signature": f"{schema}.{signature}"},
        )
        .scalar_one()
    )


def _has_table_privilege(role: str, relation: str, privilege: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("SELECT has_table_privilege(:role, :relation, :privilege)"),
            {"role": role, "relation": relation, "privilege": privilege},
        )
        .scalar_one()
    )


def _state() -> str:
    legacy = (
        _relation_exists("public", "review_runs"),
        _relation_exists("public", "review_run_agents"),
        _column_exists("public", "findings", "review_run_id"),
    )
    target = (
        _relation_exists("public", "reviews"),
        _relation_exists("public", "review_agents"),
        _relation_exists("private", "review_dispatch_jobs"),
        _column_exists("public", "findings", "review_id"),
    )
    if all(legacy) and not any(target):
        return "legacy"
    if not any(legacy) and all(target):
        return "target"
    raise RuntimeError(
        "review persistence is in an unexpected mixed state; refusing to mutate it"
    )


def _validate_legacy() -> None:
    required_columns = {
        ("public", "review_runs", "id"),
        ("public", "review_run_agents", "id"),
        ("public", "review_run_agents", "review_run_id"),
        ("public", "findings", "review_run_id"),
    }
    required_constraints = {
        ("public", "review_runs", "review_runs_pkey"),
        ("public", "review_runs", "review_runs_owner_id_id_key"),
        ("public", "review_run_agents", "review_run_agents_pkey"),
        ("public", "review_run_agents", "review_run_agents_owner_tuple_key"),
        ("public", "review_run_agents", "review_run_agents_owner_id_id_key"),
        ("public", "findings", "findings_owner_run_agent_fkey"),
    }
    required_indexes = {
        ("public", "review_runs_owner_created_idx"),
        ("public", "review_runs_owner_idempotency_key_unique"),
        ("public", "review_run_agents_owner_run_idx"),
    }
    if not all(_column_exists(*column) for column in required_columns):
        raise RuntimeError("review persistence legacy state has incompatible columns")
    if not all(_constraint_exists(*constraint) for constraint in required_constraints):
        raise RuntimeError(
            "review persistence legacy state has incompatible constraints"
        )
    if not all(_index_exists(*index) for index in required_indexes):
        raise RuntimeError("review persistence legacy state has incompatible indexes")
    if not _type_exists("public", "review_run_agent_status"):
        raise RuntimeError(
            "review persistence legacy state has an incompatible status type"
        )
    if not _policy_exists(
        "public", "review_runs", "review_runs_owner_isolation"
    ) or not _policy_exists(
        "public", "review_run_agents", "review_run_agents_owner_isolation"
    ):
        raise RuntimeError(
            "review persistence legacy state has incompatible RLS policies"
        )
    if not _function_exists("public", "trace_review_run_exists(uuid)"):
        raise RuntimeError(
            "review persistence legacy state is missing its existence helper"
        )


def _validate_target() -> None:
    required_columns = {
        ("public", "reviews", "id"),
        ("public", "review_agents", "id"),
        ("public", "review_agents", "review_id"),
        ("public", "findings", "review_id"),
        ("private", "review_dispatch_jobs", "idempotency_id"),
        ("private", "review_dispatch_jobs", "review_agent_id"),
    }
    required_constraints = {
        ("public", "reviews", "reviews_pkey"),
        ("public", "reviews", "reviews_owner_id_id_key"),
        ("public", "reviews", "reviews_owner_idempotency_id_key"),
        ("public", "review_agents", "review_agents_pkey"),
        ("public", "review_agents", "review_agents_owner_tuple_key"),
        ("public", "review_agents", "review_agents_owner_review_id_id_key"),
        ("public", "findings", "findings_owner_review_agent_fkey"),
        ("private", "review_dispatch_jobs", "review_dispatch_jobs_pkey"),
        ("private", "review_dispatch_jobs", "review_dispatch_jobs_owner_agent_key"),
        (
            "private",
            "review_dispatch_jobs",
            "review_dispatch_jobs_owner_assignment_fkey",
        ),
    }
    required_indexes = {
        ("public", "reviews_owner_created_idx"),
        ("public", "reviews_owner_idempotency_key_unique"),
        ("public", "review_agents_owner_review_idx"),
        ("private", "private_review_dispatch_jobs_pending_claim_idx"),
        ("private", "private_review_dispatch_jobs_review_idx"),
    }
    if not all(_column_exists(*column) for column in required_columns):
        raise RuntimeError("review persistence target state is incomplete")
    if not all(_constraint_exists(*constraint) for constraint in required_constraints):
        raise RuntimeError(
            "review persistence target state has incompatible constraints"
        )
    if not all(_index_exists(*index) for index in required_indexes):
        raise RuntimeError("review persistence target state has incompatible indexes")
    if not _type_exists("public", "review_agent_status") or not _type_exists(
        "private", "review_dispatch_status"
    ):
        raise RuntimeError(
            "review persistence target state has incompatible status types"
        )
    if not _policy_exists(
        "public", "reviews", "reviews_owner_isolation"
    ) or not _policy_exists("public", "review_agents", "review_agents_owner_isolation"):
        raise RuntimeError(
            "review persistence target state has incompatible RLS policies"
        )
    if not _function_exists("public", "trace_review_exists(uuid)"):
        raise RuntimeError(
            "review persistence target state is missing its existence helper"
        )
    if not _has_table_privilege(
        "trace_app", "private.review_dispatch_jobs", "INSERT"
    ) or _has_table_privilege("trace_app", "private.review_dispatch_jobs", "SELECT"):
        raise RuntimeError("review dispatch outbox grants violate least privilege")
    if not all(
        _has_table_privilege(
            "trace_internal", "private.review_dispatch_jobs", privilege
        )
        for privilege in ("SELECT", "UPDATE", "DELETE")
    ):
        raise RuntimeError("review dispatch worker grants are incomplete")


def _assert_assignment_ids_are_uuid7_and_unique() -> None:
    invalid = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT EXISTS (
              SELECT 1
              FROM public.review_run_agents
              WHERE id IS NULL OR substring(id::text FROM 15 FOR 1) <> '7'
            )
            """
            )
        )
        .scalar_one()
    )
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT EXISTS (
              SELECT 1 FROM public.review_run_agents
              GROUP BY id HAVING count(*) > 1
            )
            """
            )
        )
        .scalar_one()
    )
    if invalid or duplicate:
        raise RuntimeError(
            "review assignment IDs must be unique UUIDv7 values before cutover"
        )


def _create_review_exists_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_review_exists(resource_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $fn$
          SELECT EXISTS(SELECT 1 FROM public.reviews AS resource WHERE resource.id = $1)
        $fn$;
        REVOKE ALL ON FUNCTION public.trace_review_exists(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.trace_review_exists(uuid) TO trace_app;
        """
    )


def _create_review_dispatch_outbox() -> None:
    op.execute(
        """
        CREATE TYPE private.review_dispatch_status AS ENUM
          ('pending', 'processing', 'published', 'dead_letter')
        """
    )
    op.execute(
        """
        CREATE TABLE private.review_dispatch_jobs (
          idempotency_id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL,
          review_id uuid NOT NULL,
          review_agent_id uuid NOT NULL,
          status private.review_dispatch_status NOT NULL
            DEFAULT 'pending'::private.review_dispatch_status,
          attempt_count integer NOT NULL DEFAULT 0,
          next_attempt_at timestamptz NULL,
          claimed_at timestamptz NULL,
          published_at timestamptz NULL,
          failure_code text NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT review_dispatch_jobs_owner_agent_key
            UNIQUE (owner_id, review_agent_id),
          CONSTRAINT review_dispatch_jobs_attempts_check CHECK (attempt_count >= 0),
          CONSTRAINT review_dispatch_jobs_failure_code_check CHECK (
            failure_code IS NULL OR failure_code ~ '^[a-z0-9_]{1,64}$'
          ),
          CONSTRAINT review_dispatch_jobs_owner_fkey
            FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE CASCADE,
          CONSTRAINT review_dispatch_jobs_owner_assignment_fkey
            FOREIGN KEY (owner_id, review_id, review_agent_id)
            REFERENCES public.review_agents(owner_id, review_id, id)
            ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX private_review_dispatch_jobs_pending_claim_idx
          ON private.review_dispatch_jobs
             (status, next_attempt_at, created_at, idempotency_id)
          WHERE status = 'pending'::private.review_dispatch_status
        """
    )
    op.execute(
        """
        CREATE INDEX private_review_dispatch_jobs_review_idx
          ON private.review_dispatch_jobs (owner_id, review_id, created_at DESC)
        """
    )
    op.execute("GRANT USAGE ON SCHEMA private TO trace_app")
    op.execute("GRANT USAGE ON SCHEMA private TO trace_internal")
    op.execute("REVOKE ALL ON private.review_dispatch_jobs FROM PUBLIC")
    op.execute("REVOKE ALL ON private.review_dispatch_jobs FROM trace_app")
    op.execute("GRANT INSERT ON private.review_dispatch_jobs TO trace_app")
    op.execute(
        "GRANT SELECT, UPDATE, DELETE ON private.review_dispatch_jobs TO trace_internal"
    )


def upgrade() -> None:
    state = _state()
    if state == "target":
        _validate_target()
        return

    _validate_legacy()
    op.execute(
        "LOCK TABLE public.review_runs, public.review_run_agents, public.findings "
        "IN ACCESS EXCLUSIVE MODE"
    )
    _assert_assignment_ids_are_uuid7_and_unique()

    op.execute(
        "ALTER TABLE public.findings DROP CONSTRAINT findings_owner_run_agent_fkey"
    )
    op.execute("ALTER TABLE public.review_runs RENAME TO reviews")
    op.execute("ALTER TABLE public.review_run_agents RENAME TO review_agents")
    op.execute(
        "ALTER TABLE public.review_agents RENAME COLUMN review_run_id TO review_id"
    )
    op.execute("ALTER TABLE public.findings RENAME COLUMN review_run_id TO review_id")
    op.execute(
        "ALTER TYPE public.review_run_agent_status RENAME TO review_agent_status"
    )

    op.execute(
        "ALTER TABLE public.reviews RENAME CONSTRAINT review_runs_pkey TO reviews_pkey"
    )
    op.execute(
        "ALTER TABLE public.reviews RENAME CONSTRAINT review_runs_owner_id_id_key "
        "TO reviews_owner_id_id_key"
    )
    op.execute(
        "ALTER TABLE public.reviews RENAME CONSTRAINT review_runs_owner_project_fkey "
        "TO reviews_owner_project_fkey"
    )
    op.execute(
        "ALTER TABLE public.reviews RENAME CONSTRAINT "
        "review_runs_owner_idempotency_id_key TO reviews_owner_idempotency_id_key"
    )
    op.execute(
        "ALTER INDEX public.review_runs_owner_created_idx RENAME TO reviews_owner_created_idx"
    )
    op.execute(
        "ALTER INDEX public.review_runs_owner_idempotency_key_unique "
        "RENAME TO reviews_owner_idempotency_key_unique"
    )

    op.execute(
        "ALTER TABLE public.review_agents DROP CONSTRAINT review_run_agents_pkey"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT "
        "review_run_agents_owner_tuple_key TO review_agents_owner_tuple_key"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT "
        "review_run_agents_owner_id_id_key TO review_agents_owner_id_id_key"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT "
        "review_run_agents_owner_run_fkey TO review_agents_owner_review_fkey"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT "
        "review_run_agents_owner_agent_fkey TO review_agents_owner_agent_fkey"
    )
    op.execute(
        "ALTER TABLE public.review_agents ADD CONSTRAINT review_agents_pkey PRIMARY KEY (id)"
    )
    op.execute(
        "ALTER TABLE public.review_agents ADD CONSTRAINT "
        "review_agents_owner_review_id_id_key UNIQUE (owner_id, review_id, id)"
    )
    op.execute(
        "ALTER INDEX public.review_run_agents_owner_run_idx "
        "RENAME TO review_agents_owner_review_idx"
    )
    op.execute(
        "ALTER TABLE public.findings ADD CONSTRAINT findings_owner_review_agent_fkey "
        "FOREIGN KEY (owner_id, review_id, agent_id) "
        "REFERENCES public.review_agents(owner_id, review_id, agent_id) "
        "ON DELETE RESTRICT"
    )

    op.execute("DROP POLICY IF EXISTS review_runs_owner_isolation ON public.reviews")
    op.execute(
        "CREATE POLICY reviews_owner_isolation ON public.reviews "
        "USING (owner_id = public.trace_current_user_id()) "
        "WITH CHECK (owner_id = public.trace_current_user_id())"
    )
    op.execute(
        "DROP POLICY IF EXISTS review_run_agents_owner_isolation ON public.review_agents"
    )
    op.execute(
        "CREATE POLICY review_agents_owner_isolation ON public.review_agents "
        "USING (owner_id = public.trace_current_user_id()) "
        "WITH CHECK (owner_id = public.trace_current_user_id())"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.reviews TO trace_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON public.review_agents TO trace_app"
    )
    _create_review_exists_function()
    op.execute("DROP FUNCTION IF EXISTS public.trace_review_run_exists(uuid)")
    _create_review_dispatch_outbox()


def downgrade() -> None:
    if _state() != "target":
        raise RuntimeError("review persistence is not in the expected target state")
    jobs = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM private.review_dispatch_jobs"))
        .scalar_one()
    )
    if jobs:
        raise RuntimeError(
            "cannot downgrade review persistence while dispatch jobs still exist"
        )

    op.execute("DROP TABLE private.review_dispatch_jobs")
    op.execute("DROP TYPE private.review_dispatch_status")
    op.execute(
        "ALTER TABLE public.findings DROP CONSTRAINT findings_owner_review_agent_fkey"
    )
    op.execute("ALTER TABLE public.review_agents DROP CONSTRAINT review_agents_pkey")
    op.execute(
        "ALTER TABLE public.review_agents DROP CONSTRAINT "
        "review_agents_owner_review_id_id_key"
    )
    op.execute(
        "ALTER TABLE public.review_agents ADD CONSTRAINT review_agents_pkey "
        "PRIMARY KEY (review_id, agent_id)"
    )
    op.execute(
        "ALTER TABLE public.findings ADD CONSTRAINT findings_owner_review_agent_fkey "
        "FOREIGN KEY (owner_id, review_id, agent_id) "
        "REFERENCES public.review_agents(owner_id, review_id, agent_id) "
        "ON DELETE RESTRICT"
    )

    op.execute("DROP POLICY IF EXISTS reviews_owner_isolation ON public.reviews")
    op.execute(
        "DROP POLICY IF EXISTS review_agents_owner_isolation ON public.review_agents"
    )
    op.execute(
        "ALTER INDEX public.reviews_owner_created_idx RENAME TO review_runs_owner_created_idx"
    )
    op.execute(
        "ALTER INDEX public.reviews_owner_idempotency_key_unique "
        "RENAME TO review_runs_owner_idempotency_key_unique"
    )
    op.execute(
        "ALTER INDEX public.review_agents_owner_review_idx "
        "RENAME TO review_run_agents_owner_run_idx"
    )
    op.execute(
        "ALTER TABLE public.reviews RENAME CONSTRAINT reviews_pkey TO review_runs_pkey"
    )
    op.execute(
        "ALTER TABLE public.reviews RENAME CONSTRAINT reviews_owner_id_id_key "
        "TO review_runs_owner_id_id_key"
    )
    op.execute(
        "ALTER TABLE public.reviews RENAME CONSTRAINT reviews_owner_project_fkey "
        "TO review_runs_owner_project_fkey"
    )
    op.execute(
        "ALTER TABLE public.reviews RENAME CONSTRAINT reviews_owner_idempotency_id_key "
        "TO review_runs_owner_idempotency_id_key"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT review_agents_owner_tuple_key "
        "TO review_run_agents_owner_tuple_key"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT review_agents_owner_id_id_key "
        "TO review_run_agents_owner_id_id_key"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT review_agents_owner_review_fkey "
        "TO review_run_agents_owner_run_fkey"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT review_agents_owner_agent_fkey "
        "TO review_run_agents_owner_agent_fkey"
    )
    op.execute(
        "ALTER TABLE public.review_agents RENAME CONSTRAINT review_agents_pkey "
        "TO review_run_agents_pkey"
    )
    op.execute(
        "ALTER TABLE public.findings RENAME CONSTRAINT findings_owner_review_agent_fkey "
        "TO findings_owner_run_agent_fkey"
    )
    op.execute(
        "ALTER TYPE public.review_agent_status RENAME TO review_run_agent_status"
    )
    op.execute("ALTER TABLE public.findings RENAME COLUMN review_id TO review_run_id")
    op.execute(
        "ALTER TABLE public.review_agents RENAME COLUMN review_id TO review_run_id"
    )
    op.execute("ALTER TABLE public.review_agents RENAME TO review_run_agents")
    op.execute("ALTER TABLE public.reviews RENAME TO review_runs")
    op.execute(
        "CREATE POLICY review_runs_owner_isolation ON public.review_runs "
        "USING (owner_id = public.trace_current_user_id()) "
        "WITH CHECK (owner_id = public.trace_current_user_id())"
    )
    op.execute(
        "CREATE POLICY review_run_agents_owner_isolation ON public.review_run_agents "
        "USING (owner_id = public.trace_current_user_id()) "
        "WITH CHECK (owner_id = public.trace_current_user_id())"
    )
    op.execute("DROP FUNCTION IF EXISTS public.trace_review_exists(uuid)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_review_run_exists(resource_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $fn$
          SELECT EXISTS(SELECT 1 FROM public.review_runs AS resource WHERE resource.id = $1)
        $fn$;
        REVOKE ALL ON FUNCTION public.trace_review_run_exists(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.trace_review_run_exists(uuid) TO trace_app;
        """
    )
