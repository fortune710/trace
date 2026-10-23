"""Add concurrency versions for credential and review mutations."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261007_0010"
down_revision = "20261007_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credentials",
        sa.Column(
            "mutation_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="private",
    )
    op.add_column(
        "review_runs",
        sa.Column(
            "retry_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="public",
    )
    op.create_check_constraint(
        "credentials_mutation_version_check",
        "credentials",
        "mutation_version >= 0",
        schema="private",
    )
    op.create_check_constraint(
        "review_runs_retry_version_check",
        "review_runs",
        "retry_version >= 0",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        "review_runs_retry_version_check",
        "review_runs",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        "credentials_mutation_version_check",
        "credentials",
        schema="private",
        type_="check",
    )
    op.drop_column("review_runs", "retry_version", schema="public")
    op.drop_column("credentials", "mutation_version", schema="private")
