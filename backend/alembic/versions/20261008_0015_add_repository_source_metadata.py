"""Store selected provider repository metadata on projects."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261008_0015"
down_revision = "20261007_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("repository_owner", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "projects",
        sa.Column("repository_name", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "projects", sa.Column("branch_name", sa.Text(), nullable=True), schema="public"
    )
    op.add_column(
        "projects",
        sa.Column("repository_visibility", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "projects",
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )

    op.drop_index(
        "projects_owner_external_repository_key",
        table_name="projects",
        schema="public",
    )
    op.create_index(
        "projects_owner_external_repository_key",
        "projects",
        ["owner_id", "source", "external_repository_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("source = 'github' AND archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "projects_owner_external_repository_key",
        table_name="projects",
        schema="public",
    )
    op.create_index(
        "projects_owner_external_repository_key",
        "projects",
        ["owner_id", "external_repository_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("source = 'github' AND archived_at IS NULL"),
    )
    for column in (
        "imported_at",
        "repository_visibility",
        "branch_name",
        "repository_name",
        "repository_owner",
    ):
        op.drop_column("projects", column, schema="public")
