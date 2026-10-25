"""Allow the review worker to check finding digest conflicts.

Revision ID: 20261024_0028
Revises: 20261024_0027
Create Date: 2026-10-24
"""

from __future__ import annotations

from alembic import op

revision = "20261024_0028"
down_revision = "20261024_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Permit only the column reads required by ON CONFLICT DO NOTHING."""

    op.execute(
        "GRANT SELECT (owner_id, review_id, agent_id, content_digest) "
        "ON public.findings TO trace_internal"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT (owner_id, review_id, agent_id, content_digest) "
        "ON public.findings FROM trace_internal"
    )
