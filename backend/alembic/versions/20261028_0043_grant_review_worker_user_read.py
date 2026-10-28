"""Grant the review worker access to its automatic-PR preference.

Revision ID: 20261028_0043
Revises: 20261028_0042
"""

from alembic import op

revision = "20261028_0043"
down_revision = "20261028_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "GRANT SELECT (id, automatic_pull_requests) ON public.users TO trace_internal"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT (id, automatic_pull_requests) ON public.users "
        "FROM trace_internal"
    )
