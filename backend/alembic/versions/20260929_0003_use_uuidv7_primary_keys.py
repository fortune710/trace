"""Use time-ordered UUIDv7 defaults for generated primary keys."""

from __future__ import annotations

from alembic import op

revision = "20260929_0003"
down_revision = "20260929_0002"
branch_labels = None
depends_on = None


_UUIDV7_TABLES = (
    ("auth", "users"),
    ("auth", "identities"),
    ("auth", "sessions"),
    ("auth", "refresh_tokens"),
    ("auth", "email_verification_tokens"),
    ("auth", "password_recovery_tokens"),
    ("public", "projects"),
    ("private", "credentials"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.uuidv7()
        RETURNS uuid
        LANGUAGE plpgsql
        VOLATILE
        AS $$
        DECLARE
          timestamp_hex text := lpad(to_hex(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint), 12, '0');
          random_hex text := replace(gen_random_uuid()::text, '-', '');
        BEGIN
          RETURN (
            substr(timestamp_hex, 1, 8) || '-' ||
            substr(timestamp_hex, 9, 4) || '-' ||
            '7' || substr(random_hex, 14, 3) || '-' ||
            substr(random_hex, 17, 4) || '-' ||
            substr(random_hex, 21, 12)
          )::uuid;
        END;
        $$;
        """
    )
    for schema, table in _UUIDV7_TABLES:
        op.execute(
            f"ALTER TABLE {schema}.{table} ALTER COLUMN id SET DEFAULT public.uuidv7()"
        )


def downgrade() -> None:
    for schema, table in _UUIDV7_TABLES:
        op.execute(
            f"ALTER TABLE {schema}.{table} ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )
    op.execute("DROP FUNCTION IF EXISTS public.uuidv7()")
