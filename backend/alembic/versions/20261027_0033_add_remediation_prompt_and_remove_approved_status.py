"""Add remediation prompts and remove the approved remediation state.

Revision ID: 20261027_0033
Revises: 20261027_0032
"""

from alembic import op

revision = "20261027_0033"
down_revision = "20261027_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.remediations ADD COLUMN prompt_text text NULL")

    # An approved remediation has not necessarily been applied. Preserve that
    # distinction by returning existing approved rows to the proposed state.
    op.execute(
        "UPDATE public.remediations "
        "SET status = 'proposed'::public.remediation_status "
        "WHERE status = 'approved'::public.remediation_status"
    )
    op.execute(
        "CREATE TYPE public.remediation_status_without_approved "
        "AS ENUM ('proposed', 'rejected', 'applied')"
    )
    op.execute(
        "ALTER TABLE public.remediations "
        "ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE public.remediation_status_without_approved "
        "USING status::text::public.remediation_status_without_approved"
    )
    op.execute("DROP TYPE public.remediation_status")
    op.execute(
        "ALTER TYPE public.remediation_status_without_approved "
        "RENAME TO remediation_status"
    )
    op.execute(
        "ALTER TABLE public.remediations "
        "ALTER COLUMN status SET DEFAULT 'proposed'::public.remediation_status"
    )


def downgrade() -> None:
    op.execute(
        "CREATE TYPE public.remediation_status_with_approved "
        "AS ENUM ('proposed', 'approved', 'rejected', 'applied')"
    )
    op.execute(
        "ALTER TABLE public.remediations "
        "ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE public.remediation_status_with_approved "
        "USING status::text::public.remediation_status_with_approved"
    )
    op.execute("DROP TYPE public.remediation_status")
    op.execute(
        "ALTER TYPE public.remediation_status_with_approved "
        "RENAME TO remediation_status"
    )
    op.execute(
        "ALTER TABLE public.remediations "
        "ALTER COLUMN status SET DEFAULT 'proposed'::public.remediation_status"
    )
    op.execute("ALTER TABLE public.remediations DROP COLUMN prompt_text")
