"""Add owner authorization policies and the trusted worker role."""

from __future__ import annotations

import os

import sqlalchemy as sa

from alembic import op

revision = "20261007_0006"
down_revision = "20261002_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    internal_password = os.getenv("TRACE_INTERNAL_PASSWORD")
    if not internal_password:
        raise RuntimeError("TRACE_INTERNAL_PASSWORD must be set before migrations")

    connection = op.get_bind()
    connection.execute(
        sa.text("SELECT set_config('trace.internal_password', :password, false)"),
        {"password": internal_password},
    )

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trace_internal') THEN
            EXECUTE format(
              'ALTER ROLE trace_internal LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS PASSWORD %L',
              current_setting('trace.internal_password')
            );
          ELSE
            EXECUTE format(
              'CREATE ROLE trace_internal LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS PASSWORD %L',
              current_setting('trace.internal_password')
            );
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          EXECUTE format('GRANT CONNECT ON DATABASE %I TO trace_internal', current_database());
        END $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA auth TO trace_internal")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.email_delivery_jobs TO trace_internal"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA auth TO trace_internal")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_current_user_id()
        RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $$
        DECLARE
          configured text;
          parsed uuid;
        BEGIN
          configured := current_setting('trace.current_user_id', true);
          IF configured IS NULL OR configured = '' THEN
            RETURN NULL;
          END IF;
          BEGIN
            parsed := configured::uuid;
          EXCEPTION WHEN invalid_text_representation THEN
            RETURN NULL;
          END;
          RETURN parsed;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_project_exists(resource_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
          SELECT EXISTS(
            SELECT 1
            FROM public.projects AS project
            WHERE project.id = $1
              AND project.archived_at IS NULL
          )
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_credential_exists(resource_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public, private
        AS $$
          SELECT EXISTS(
            SELECT 1
            FROM private.credentials AS credential
            WHERE credential.id = $1
              AND credential.revoked_at IS NULL
          )
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.trace_current_user_id() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION public.trace_project_exists(uuid) FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION public.trace_credential_exists(uuid) FROM PUBLIC"
    )
    op.execute("GRANT EXECUTE ON FUNCTION public.trace_current_user_id() TO trace_app")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.trace_project_exists(uuid) TO trace_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.trace_credential_exists(uuid) TO trace_app"
    )

    for table, policy in (
        ("public.projects", "projects_owner_isolation"),
        ("private.credentials", "credentials_owner_isolation"),
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"""
            CREATE POLICY {policy} ON {table}
            USING (owner_id = public.trace_current_user_id())
            WITH CHECK (owner_id = public.trace_current_user_id())
            """
        )


def downgrade() -> None:
    for table, policy in (
        ("public.projects", "projects_owner_isolation"),
        ("private.credentials", "credentials_owner_isolation"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS public.trace_credential_exists(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.trace_project_exists(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.trace_current_user_id()")
    op.execute("REVOKE ALL ON auth.email_delivery_jobs FROM trace_internal")
    op.execute("REVOKE USAGE ON SCHEMA auth FROM trace_internal")
    op.execute("DROP ROLE IF EXISTS trace_internal")
