"""Grant the API role access to the PR outbox identifier it returns.

Revision ID: 20261029_0050
Revises: 20261029_0049
"""

from alembic import op

revision = "20261029_0050"
down_revision = "20261029_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Permit RETURNING idempotency_id after an API-role outbox insert."""

    op.execute(
        "GRANT SELECT (idempotency_id) "
        "ON private.remediation_pull_request_outbox_jobs TO trace_app"
    )


def downgrade() -> None:
    """Remove the read privilege introduced for INSERT ... RETURNING."""

    op.execute(
        "REVOKE SELECT (idempotency_id) "
        "ON private.remediation_pull_request_outbox_jobs FROM trace_app"
    )
