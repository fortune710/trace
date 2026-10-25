"""Grant the internal review executor its required database access.

Revision ID: 20261024_0025
Revises: 20261022_0024
Create Date: 2026-10-24
"""

from __future__ import annotations

from alembic import op

revision = "20261024_0025"
down_revision = "20261022_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Grant only the tables and mutations used by review execution."""

    op.execute("GRANT SELECT, UPDATE ON public.reviews TO trace_internal")
    op.execute("GRANT SELECT, UPDATE ON public.review_agents TO trace_internal")
    op.execute("GRANT INSERT ON public.findings TO trace_internal")
    op.execute("GRANT SELECT ON public.external_repositories TO trace_internal")
    op.execute("GRANT SELECT, UPDATE ON private.credentials TO trace_internal")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON private.review_agent_attempts "
        "TO trace_internal"
    )
    op.execute(
        "GRANT SELECT ON private.review_agent_execution_configs TO trace_internal"
    )


def downgrade() -> None:
    """Remove only the privileges introduced for review execution."""

    op.execute("REVOKE UPDATE ON public.reviews FROM trace_internal")
    op.execute("REVOKE SELECT, UPDATE ON public.review_agents FROM trace_internal")
    op.execute("REVOKE INSERT ON public.findings FROM trace_internal")
    op.execute("REVOKE SELECT ON public.external_repositories FROM trace_internal")
    op.execute("REVOKE SELECT, UPDATE ON private.credentials FROM trace_internal")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON private.review_agent_attempts "
        "FROM trace_internal"
    )
    op.execute(
        "REVOKE SELECT ON private.review_agent_execution_configs FROM trace_internal"
    )
