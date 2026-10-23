"""Normalize legacy agent model pairs and grant audit enqueue access.

Revision ID: 20261023_0023
Revises: 20261018_0022
Create Date: 2026-10-23
"""

from __future__ import annotations

from alembic import op

revision = "20261023_0023"
down_revision = "20261018_0022"
branch_labels = None
depends_on = None

# The provider/model pairs supported by the agent catalog
# (backend/agents/catalog.py). Every persisted pair that is not one of
# these is rewritten to the default supported pair so that legacy rows,
# including rows on disabled agents, pass AgentResponse validation,
# whose model_provider only accepts ModelProvider values.
_SUPPORTED_PAIRS = (
    "('openai', 'gpt-6.1-sol')",
    "('openai', 'gpt-5.1')",
    "('anthropic', 'claude-opus-5-5')",
    "('google', 'gemini-3.8-flash')",
    "('xai', 'grok-4.7')",
)


def upgrade() -> None:
    """Rewrite unsupported agent model pairs and grant audit INSERT."""

    pairs = ", ".join(_SUPPORTED_PAIRS)
    op.execute(
        "UPDATE public.agents "
        "SET model_provider = 'openai', model_name = 'gpt-6.1-sol' "
        f"WHERE (model_provider, model_name) NOT IN ({pairs})"
    )
    # The review-dispatch worker enqueues audit events as trace_internal
    # through enqueue_audit; migration 0012 granted that role only
    # SELECT, UPDATE, and DELETE on the audit outbox.
    op.execute(
        "GRANT INSERT ON private.audit_delivery_jobs TO trace_internal"
    )


def downgrade() -> None:
    # The model-pair rewrite is not reversible: the previous unsupported
    # values are not recorded anywhere. Only the grant is rolled back.
    op.execute(
        "REVOKE INSERT ON private.audit_delivery_jobs FROM trace_internal"
    )
