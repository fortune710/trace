"""Store pull-request metadata on remediations.

Revision ID: 20261028_0039
Revises: 20261028_0038
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261028_0039"
down_revision = "20261028_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "remediations",
        sa.Column("pull_request", postgresql.JSONB(), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        "remediations_pull_request_shape_check",
        "remediations",
        "pull_request IS NULL OR ("
        "jsonb_typeof(pull_request) = 'object' "
        "AND pull_request ?& ARRAY['url', 'number', 'is_merged'] "
        "AND pull_request - 'url' - 'number' - 'is_merged' = '{}'::jsonb "
        "AND jsonb_typeof(pull_request -> 'url') = 'string' "
        "AND length(pull_request ->> 'url') > 0 "
        "AND jsonb_typeof(pull_request -> 'number') = 'number' "
        "AND (pull_request ->> 'number') ~ '^[1-9][0-9]*$' "
        "AND jsonb_typeof(pull_request -> 'is_merged') = 'boolean'"
        ")",
        schema="public",
    )
    op.execute("DROP FUNCTION IF EXISTS public.trace_pull_request_exists(uuid)")
    op.drop_table("pull_requests", schema="public")


def downgrade() -> None:
    op.create_table(
        "pull_requests",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("remediation_id", sa.UUID(), nullable=False),
        sa.Column("repository_url", sa.Text(), nullable=False),
        sa.Column("pull_request_number", sa.BigInteger(), nullable=False),
        sa.Column("pull_request_url", sa.Text(), nullable=False),
        sa.Column("branch_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="public",
    )
    op.drop_constraint(
        "remediations_pull_request_shape_check", "remediations", schema="public"
    )
    op.drop_column("remediations", "pull_request", schema="public")
