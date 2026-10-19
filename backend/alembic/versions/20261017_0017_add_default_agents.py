"""Add default-agent metadata and provision defaults for existing accounts.

Revision ID: 20261017_0017
Revises: 20261017_0016
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261017_0017"
down_revision = "20261017_0016"
branch_labels = None
depends_on = None


def _relation_exists(relation_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT to_regclass(:relation_name) IS NOT NULL"), {
            "relation_name": relation_name,
        })
        .scalar()
    )


def _enum_exists(schema: str, enum_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_type AS type
                  JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
                  WHERE namespace.nspname = :schema AND type.typname = :enum_name
                )
                """
            ),
            {"schema": schema, "enum_name": enum_name},
        )
        .scalar()
    )


def _enum_value_exists(schema: str, enum_name: str, value: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_enum AS value_row
                  JOIN pg_type AS type ON type.oid = value_row.enumtypid
                  JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
                  WHERE namespace.nspname = :schema
                    AND type.typname = :enum_name
                    AND value_row.enumlabel = :value
                )
                """
            ),
            {"schema": schema, "enum_name": enum_name, "value": value},
        )
        .scalar()
    )


def _add_enum_value_if_missing(schema: str, enum_name: str, value: str) -> None:
    if _enum_exists(schema, enum_name) and not _enum_value_exists(
        schema, enum_name, value
    ):
        # All callers use migration-owned identifiers and values, rather than
        # user input, so this DDL can safely use a literal enum label.
        op.execute(f"ALTER TYPE {schema}.{enum_name} ADD VALUE '{value}'")


def _seed_existing_accounts() -> None:
    if not (
        _relation_exists("public.users")
        and _relation_exists("public.agents")
        and _enum_exists("public", "review_category")
    ):
        return

    defaults = (
        {
            "key": "harvey-specter-legal",
            "name": "Harvey Specter",
            "personality": (
                "You are a decisive in-house legal reviewer. Identify concrete legal, "
                "privacy, compliance, and terms-of-service risk; distinguish required "
                "action from business judgment; and recommend plain-language mitigations."
            ),
            "category": "legal",
            "avatar": "agent-defaults/harvey-specter",
        },
        {
            "key": "mark-zuckerberg-engineering",
            "name": "Mark Zuckerberg",
            "personality": (
                "You are a systems-minded engineering reviewer. Examine architecture, "
                "reliability, security boundaries, scalability, and developer ergonomics; "
                "prioritize specific, reproducible fixes."
            ),
            "category": "engineering",
            "avatar": "agent-defaults/mark-zuckerberg",
        },
        {
            "key": "super-pm-product",
            "name": "Super PM",
            "personality": (
                "You are a practical product strategist. Evaluate user value, onboarding, "
                "scope, edge cases, success metrics, and launch risk; turn ambiguity into "
                "clear priorities."
            ),
            "category": "product",
            "avatar": "agent-defaults/super-pm",
        },
    )
    statement = sa.text(
        """
        INSERT INTO public.agents (
          id, owner_id, name, personality, review_category, model_provider,
          model_name, avatar, default_key, skills, fallback_order
        )
        SELECT public.uuidv7(), user_row.id, :name, :personality,
          CAST(:category AS public.review_category), 'openai', 'gpt-6.1-sol',
          :avatar, :key, '[]'::jsonb, 0
        FROM public.users AS user_row
        ON CONFLICT (owner_id, default_key) WHERE default_key IS NOT NULL DO NOTHING
        """
    )
    for default in defaults:
        op.get_bind().execute(statement, default)


def upgrade() -> None:
    _add_enum_value_if_missing("public", "review_category", "marketing")
    _add_enum_value_if_missing("private", "credential_provider", "xai")

    if _relation_exists("public.agents"):
        op.execute("ALTER TABLE public.agents ADD COLUMN IF NOT EXISTS avatar TEXT")
        op.execute(
            "ALTER TABLE public.agents ADD COLUMN IF NOT EXISTS default_key TEXT"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS agents_owner_default_key_unique "
            "ON public.agents (owner_id, default_key) "
            "WHERE default_key IS NOT NULL"
        )

    _seed_existing_accounts()


def downgrade() -> None:
    # Default agents are user-owned after creation, and PostgreSQL enum labels
    # cannot be safely removed once used. Keep both forward-compatible instead
    # of deleting customized records or risking a failed deployment rollback.
    return
