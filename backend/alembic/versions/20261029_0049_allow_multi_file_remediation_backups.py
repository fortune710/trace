"""Allow one local backup per remediation file.

Revision ID: 20261029_0049
Revises: 20261028_0048
"""

from alembic import op

revision = "20261029_0049"
down_revision = "20261028_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.local_file_backups "
        "DROP CONSTRAINT IF EXISTS local_file_backups_owner_remediation_key"
    )
    op.execute(
        "ALTER TABLE public.local_file_backups "
        "ADD CONSTRAINT local_file_backups_owner_remediation_path_key "
        "UNIQUE (owner_id, remediation_id, file_path)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.local_file_backups "
        "DROP CONSTRAINT IF EXISTS local_file_backups_owner_remediation_path_key"
    )
    op.execute(
        "ALTER TABLE public.local_file_backups "
        "ADD CONSTRAINT local_file_backups_owner_remediation_key "
        "UNIQUE (owner_id, remediation_id)"
    )
