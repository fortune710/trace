"""Allow owner-scoped agents to use encrypted BYOK credentials."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261007_0009"
down_revision = "20261007_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("credential_id", sa.UUID(), nullable=True),
        schema="public",
    )
    op.create_foreign_key(
        "agents_owner_credential_fkey",
        "agents",
        "credentials",
        ["owner_id", "credential_id"],
        ["owner_id", "id"],
        source_schema="public",
        referent_schema="private",
        ondelete="RESTRICT",
    )
    op.create_index(
        "agents_owner_credential_idx",
        "agents",
        ["owner_id", "credential_id"],
        schema="public",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_validate_agent_credential()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public, private
        AS $$
        BEGIN
          IF NEW.credential_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM private.credentials AS credential
            WHERE credential.owner_id = NEW.owner_id
              AND credential.id = NEW.credential_id
              AND credential.revoked_at IS NULL
              AND credential.provider::text = NEW.model_provider
          ) THEN
            RAISE EXCEPTION 'agent credential is unavailable'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION public.trace_validate_agent_credential() FROM PUBLIC;
        CREATE TRIGGER agents_validate_credential
          BEFORE INSERT OR UPDATE OF owner_id, credential_id, model_provider
          ON public.agents
          FOR EACH ROW EXECUTE FUNCTION public.trace_validate_agent_credential();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS agents_validate_credential ON public.agents")
    op.execute("DROP FUNCTION IF EXISTS public.trace_validate_agent_credential()")
    op.drop_index("agents_owner_credential_idx", table_name="agents", schema="public")
    op.drop_constraint(
        "agents_owner_credential_fkey", "agents", schema="public", type_="foreignkey"
    )
    op.drop_column("agents", "credential_id", schema="public")
