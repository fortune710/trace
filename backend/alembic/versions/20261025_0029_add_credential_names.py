"""Name BYOK credentials and allow several active keys per provider.

Revision ID: 20261025_0029
Revises: 20261024_0028
Create Date: 2026-10-25
"""

from __future__ import annotations

from alembic import op

revision = "20261025_0029"
down_revision = "20261024_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive: every statement tolerates a partially applied state, so
    # re-running this migration after an interrupted attempt, or on a
    # database where the column was added out of band, does not raise.
    op.execute("ALTER TABLE private.credentials ADD COLUMN IF NOT EXISTS name TEXT")
    op.execute(
        "DROP INDEX IF EXISTS private.credentials_active_owner_provider_kind_key"
    )
    # Unnamed credentials keep the old one-active-row-per-provider rule so
    # the OAuth connect flow's upsert keeps working unchanged.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "credentials_active_unnamed_owner_provider_kind_key "
        "ON private.credentials (owner_id, provider, credential_kind) "
        "WHERE revoked_at IS NULL AND name IS NULL"
    )
    # Named API keys are unique by name per owner, not by provider, so a
    # user can hold several active keys for the same provider.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS credentials_active_owner_name_key "
        "ON private.credentials (owner_id, name) "
        "WHERE revoked_at IS NULL AND name IS NOT NULL"
    )
    # An agent may only link an API-key credential, never an OAuth one,
    # even when the OAuth credential's provider matches the model provider.
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
              AND credential.credential_kind::text = 'api_key'
          ) THEN
            RAISE EXCEPTION 'agent credential is unavailable'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION public.trace_validate_agent_credential() FROM PUBLIC;
        DROP TRIGGER IF EXISTS agents_validate_credential ON public.agents;
        CREATE TRIGGER agents_validate_credential
          BEFORE INSERT OR UPDATE OF owner_id, credential_id, model_provider
          ON public.agents
          FOR EACH ROW EXECUTE FUNCTION public.trace_validate_agent_credential();
        """
    )


def downgrade() -> None:
    # Guards mirror the upgrade. Note: if named credentials exist, the
    # restored one-row-per-provider index below will fail rather than
    # silently discarding keys; revoke or rename those keys first.
    op.execute("DROP INDEX IF EXISTS private.credentials_active_owner_name_key")
    op.execute(
        "DROP INDEX IF EXISTS "
        "private.credentials_active_unnamed_owner_provider_kind_key"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "credentials_active_owner_provider_kind_key "
        "ON private.credentials (owner_id, provider, credential_kind) "
        "WHERE revoked_at IS NULL"
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
        DROP TRIGGER IF EXISTS agents_validate_credential ON public.agents;
        CREATE TRIGGER agents_validate_credential
          BEFORE INSERT OR UPDATE OF owner_id, credential_id, model_provider
          ON public.agents
          FOR EACH ROW EXECUTE FUNCTION public.trace_validate_agent_credential();
        """
    )
    op.execute("ALTER TABLE private.credentials DROP COLUMN IF EXISTS name")
