"""Persist the account-level remediation pull-request preference.

Revision ID: 20261028_0041
Revises: 20261028_0040
"""

import sqlalchemy as sa

from alembic import op

revision = "20261028_0041"
down_revision = "20261028_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "automatic_pull_requests",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("users", "automatic_pull_requests", schema="public")
