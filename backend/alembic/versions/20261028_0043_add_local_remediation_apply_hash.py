"""Record the verified post-apply hash for local remediation backups.

Revision ID: 20261028_0043
Revises: 20261028_0042
"""

revision = "20261028_0043"
down_revision = "20261028_0042"
branch_labels = None
depends_on = None


from alembic import op


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.local_file_backups "
        "ADD COLUMN applied_hash bytea NULL"
    )
    # Existing rows predate local application and cannot prove a post-apply
    # value. Reusing their recorded source hash keeps the schema valid while
    # allowing the desktop to create accurate records going forward.
    op.execute(
        "UPDATE public.local_file_backups "
        "SET applied_hash = source_hash WHERE applied_hash IS NULL"
    )
    op.execute(
        "ALTER TABLE public.local_file_backups "
        "ALTER COLUMN applied_hash SET NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.local_file_backups DROP COLUMN applied_hash"
    )
