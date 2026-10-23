"""Remove the legacy agent fallback order.

Revision ID: 20261017_0019
Revises: 20261017_0018
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261017_0019"
down_revision = "20261017_0018"
branch_labels = None
depends_on = None


def _agents_table_exists() -> bool:
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT to_regclass('public.agents') IS NOT NULL"))
        .scalar_one()
    )


def _fallback_order_exists() -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'agents'
                      AND column_name = 'fallback_order'
                )
                """
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    if _agents_table_exists() and _fallback_order_exists():
        op.execute("ALTER TABLE public.agents DROP COLUMN IF EXISTS fallback_order")


def downgrade() -> None:
    if _agents_table_exists() and not _fallback_order_exists():
        op.execute(
            "ALTER TABLE public.agents "
            "ADD COLUMN IF NOT EXISTS fallback_order INTEGER NOT NULL DEFAULT 0"
        )
