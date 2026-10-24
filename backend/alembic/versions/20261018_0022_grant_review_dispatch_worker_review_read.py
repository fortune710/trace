"""Allow the internal dispatch worker to verify a review's lifecycle state.

Revision ID: 20261018_0022
Revises: 20261018_0021
Create Date: 2026-10-18
"""

from __future__ import annotations

from alembic import op

revision = "20261018_0022"
down_revision = "20261018_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Grant only the review-state read needed before broker publication."""

    op.execute("GRANT SELECT ON TABLE public.reviews TO trace_internal")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON TABLE public.reviews FROM trace_internal")
