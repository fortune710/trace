"""Add optimistic concurrency versioning for remediation decisions."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261007_0011"
down_revision = "20261007_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "remediations",
        sa.Column(
            "mutation_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="public",
    )
    op.create_check_constraint(
        "remediations_mutation_version_check",
        "remediations",
        "mutation_version >= 0",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        "remediations_mutation_version_check",
        "remediations",
        schema="public",
        type_="check",
    )
    op.drop_column("remediations", "mutation_version", schema="public")
