"""Add private review execution configuration and finding idempotency.

Revision ID: 20261022_0024
Revises: 20261021_0023
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op

revision = "20261022_0024"
down_revision = "20261021_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE private.review_agent_execution_configs (
          review_agent_id uuid PRIMARY KEY,
          owner_id uuid NOT NULL,
          review_id uuid NOT NULL,
          credential_id uuid NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT review_agent_execution_configs_owner_assignment_fkey
            FOREIGN KEY(owner_id, review_id, review_agent_id)
            REFERENCES public.review_agents(owner_id, review_id, id)
            ON DELETE CASCADE
        )
        """
    )
    op.execute("ALTER TABLE public.findings ADD COLUMN content_digest bytea NULL")
    op.execute(
        """
        CREATE UNIQUE INDEX findings_owner_review_agent_digest_key
        ON public.findings(owner_id, review_id, agent_id, content_digest)
        WHERE content_digest IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX public.findings_owner_review_agent_digest_key")
    op.execute("ALTER TABLE public.findings DROP COLUMN content_digest")
    op.execute("DROP TABLE private.review_agent_execution_configs")
