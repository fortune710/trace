"""Record the credential-encryption provider and key reference."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260930_0004"
down_revision = "20260929_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE private.credential_encryption_provider AS ENUM ('local', 'vault')")
    op.add_column(
        "credentials",
        sa.Column(
            "encryption_provider",
            sa.Enum(
                "local",
                "vault",
                name="credential_encryption_provider",
                schema="private",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'local'::private.credential_encryption_provider"),
        ),
        schema="private",
    )
    op.add_column(
        "credentials",
        sa.Column("key_reference", sa.Text(), nullable=False, server_default=sa.text("'local-v1'")),
        schema="private",
    )
    op.alter_column("credentials", "encryption_provider", server_default=None, schema="private")
    op.alter_column("credentials", "key_reference", server_default=None, schema="private")


def downgrade() -> None:
    op.drop_column("credentials", "key_reference", schema="private")
    op.drop_column("credentials", "encryption_provider", schema="private")
    op.execute("DROP TYPE private.credential_encryption_provider")
