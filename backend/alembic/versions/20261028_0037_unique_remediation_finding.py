"""Enforce one remediation per finding.

Revision ID: 20261028_0037
Revises: 20261027_0036
"""

from alembic import op

revision = "20261028_0037"
down_revision = "20261027_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "remediations_owner_finding_idx",
        "remediations",
        ["owner_id", "finding_id"],
        unique=True,
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "remediations_owner_finding_idx",
        table_name="remediations",
        schema="public",
    )
