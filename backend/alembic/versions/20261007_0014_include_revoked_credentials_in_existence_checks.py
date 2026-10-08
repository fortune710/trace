"""Make credential existence checks cover revoked rows for safe authorization."""

from __future__ import annotations

from alembic import op

revision = "20261007_0014"
down_revision = "20261007_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_credential_exists(resource_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public, private
        AS $fn$
          SELECT EXISTS(
            SELECT 1
            FROM private.credentials AS credential
            WHERE credential.id = $1
          )
        $fn$;
        REVOKE ALL ON FUNCTION public.trace_credential_exists(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.trace_credential_exists(uuid) TO trace_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_credential_exists(resource_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public, private
        AS $fn$
          SELECT EXISTS(
            SELECT 1
            FROM private.credentials AS credential
            WHERE credential.id = $1
              AND credential.revoked_at IS NULL
          )
        $fn$;
        REVOKE ALL ON FUNCTION public.trace_credential_exists(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.trace_credential_exists(uuid) TO trace_app;
        """
    )
