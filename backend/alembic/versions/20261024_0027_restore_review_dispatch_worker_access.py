"""Restore the review dispatch worker's explicitly scoped table access.

Revision ID: 20261024_0027
Revises: 20261024_0026
Create Date: 2026-10-24
"""

from __future__ import annotations

from alembic import op

revision = "20261024_0027"
down_revision = "20261024_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Grant only the dispatch outbox operations used by the internal worker."""

    op.execute(
        "GRANT SELECT, UPDATE, DELETE ON private.review_dispatch_jobs TO trace_internal"
    )


def downgrade() -> None:
    """Remove the dispatch-outbox privileges introduced by this migration."""

    op.execute(
        "REVOKE SELECT, UPDATE, DELETE ON private.review_dispatch_jobs "
        "FROM trace_internal"
    )
