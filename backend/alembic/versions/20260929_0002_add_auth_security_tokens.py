"""Add rotation-aware sessions and one-time authentication tokens."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260929_0002"
down_revision = "20260926_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("auth_sessions_token_hash_key", "sessions", schema="auth", type_="unique")
    op.drop_column("sessions", "token_hash", schema="auth")

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["auth.sessions.id"], name="auth_refresh_tokens_session_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["auth.refresh_tokens.id"], name="auth_refresh_tokens_replaced_by_id_fkey", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="auth_refresh_tokens_pkey"),
        sa.UniqueConstraint("token_hash", name="auth_refresh_tokens_token_hash_key"),
        schema="auth",
    )
    op.create_index(
        "auth_refresh_tokens_session_expires_idx",
        "refresh_tokens",
        ["session_id", sa.text("expires_at DESC")],
        schema="auth",
    )
    op.execute(
        "CREATE INDEX auth_refresh_tokens_active_session_expires_idx "
        "ON auth.refresh_tokens (session_id, expires_at DESC) WHERE revoked_at IS NULL"
    )

    for table_name in ("email_verification_tokens", "password_recovery_tokens"):
        op.create_table(
            table_name,
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("token_hash", sa.LargeBinary(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], name=f"auth_{table_name}_user_id_fkey", ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name=f"auth_{table_name}_pkey"),
            sa.UniqueConstraint("token_hash", name=f"auth_{table_name}_token_hash_key"),
            schema="auth",
        )
        op.execute(
            f"CREATE INDEX auth_{table_name}_active_user_expires_idx "
            f"ON auth.{table_name} (user_id, expires_at DESC) WHERE used_at IS NULL"
        )


def downgrade() -> None:
    for table_name in ("password_recovery_tokens", "email_verification_tokens"):
        op.drop_table(table_name, schema="auth")

    op.drop_table("refresh_tokens", schema="auth")
    op.add_column("sessions", sa.Column("token_hash", sa.LargeBinary(), nullable=True), schema="auth")
    op.execute("UPDATE auth.sessions SET token_hash = digest(id::text, 'sha256') WHERE token_hash IS NULL")
    op.alter_column("sessions", "token_hash", nullable=False, schema="auth")
    op.create_unique_constraint("auth_sessions_token_hash_key", "sessions", ["token_hash"], schema="auth")
