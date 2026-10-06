"""Create Phase 2 database schemas and account data model."""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260926_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    app_password = os.getenv("TRACE_APP_PASSWORD")
    if not app_password:
        raise RuntimeError("TRACE_APP_PASSWORD must be set before running migrations")

    connection = op.get_bind()
    connection.execute(sa.text("SELECT set_config('trace.app_password', :password, false)"), {"password": app_password})
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trace_app') THEN
            EXECUTE format(
              'ALTER ROLE trace_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
              current_setting('trace.app_password')
            );
          ELSE
            EXECUTE format(
              'CREATE ROLE trace_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
              current_setting('trace.app_password')
            );
          END IF;
        END $$;
        """
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION trace")
    op.execute("CREATE SCHEMA IF NOT EXISTS private AUTHORIZATION trace")
    op.execute("CREATE TYPE auth.user_status AS ENUM ('active', 'disabled', 'deleted')")
    op.execute("CREATE TYPE auth.identity_provider AS ENUM ('github', 'google', 'email')")
    op.execute("CREATE TYPE public.project_source_type AS ENUM ('github', 'local')")
    op.execute("CREATE TYPE private.credential_provider AS ENUM ('github', 'google', 'openai', 'anthropic')")
    op.execute("CREATE TYPE private.credential_kind AS ENUM ('oauth', 'api_key')")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("status", postgresql.ENUM(name="user_status", schema="auth", create_type=False), server_default=sa.text("'active'::auth.user_status"), nullable=False),
        sa.Column("email_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="auth_users_pkey"),
        schema="auth",
    )
    op.execute("CREATE UNIQUE INDEX auth_users_email_lower_key ON auth.users (lower(email)) WHERE email IS NOT NULL")

    op.create_table(
        "identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", postgresql.ENUM(name="identity_provider", schema="auth", create_type=False), nullable=False),
        sa.Column("provider_subject", sa.Text(), nullable=False),
        sa.Column("provider_metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], name="auth_identities_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="auth_identities_pkey"),
        sa.UniqueConstraint("provider", "provider_subject", name="auth_identities_provider_subject_key"),
        schema="auth",
    )
    op.create_index("auth_identities_user_created_idx", "identities", ["user_id", sa.text("created_at DESC")], schema="auth")

    op.create_table(
        "password_credentials",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("failed_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], name="auth_password_credentials_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="auth_password_credentials_pkey"),
        schema="auth",
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], name="auth_sessions_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="auth_sessions_pkey"),
        sa.UniqueConstraint("token_hash", name="auth_sessions_token_hash_key"),
        schema="auth",
    )
    op.create_index("auth_sessions_user_expires_idx", "sessions", ["user_id", sa.text("expires_at DESC")], schema="auth")
    op.execute("CREATE INDEX auth_sessions_active_user_expires_idx ON auth.sessions (user_id, expires_at DESC) WHERE revoked_at IS NULL")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["id"], ["auth.users.id"], name="public_users_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="public_users_pkey"),
        schema="public",
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_type", postgresql.ENUM(name="project_source_type", schema="public", create_type=False), nullable=False),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=True),
        sa.Column("local_path_hash", sa.LargeBinary(), nullable=True),
        sa.Column("source_hash", sa.LargeBinary(), nullable=True),
        sa.Column("current_revision", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(source_type = 'github' AND github_repository_id IS NOT NULL AND local_path_hash IS NULL) OR (source_type = 'local' AND local_path_hash IS NOT NULL AND github_repository_id IS NULL)", name="projects_source_reference_check"),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], name="projects_owner_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="projects_pkey"),
        schema="public",
    )
    op.create_index("projects_owner_created_idx", "projects", ["owner_id", sa.text("created_at DESC")], schema="public")
    op.execute("CREATE UNIQUE INDEX projects_owner_github_repository_key ON public.projects (owner_id, github_repository_id) WHERE source_type = 'github' AND archived_at IS NULL")
    op.execute("CREATE UNIQUE INDEX projects_owner_local_path_key ON public.projects (owner_id, local_path_hash) WHERE source_type = 'local' AND archived_at IS NULL")

    op.create_table(
        "credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", postgresql.ENUM(name="credential_provider", schema="private", create_type=False), nullable=False),
        sa.Column("credential_kind", postgresql.ENUM(name="credential_kind", schema="private", create_type=False), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Text(), nullable=False),
        sa.Column("aad_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], name="credentials_owner_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="credentials_pkey"),
        schema="private",
    )
    op.execute("CREATE UNIQUE INDEX credentials_active_owner_provider_kind_key ON private.credentials (owner_id, provider, credential_kind) WHERE revoked_at IS NULL")

    op.execute(
        """
        DO $$
        BEGIN
          EXECUTE format('GRANT CONNECT ON DATABASE %I TO trace_app', current_database());
        END $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA auth, public, private TO trace_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA auth, public, private TO trace_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA auth, public, private TO trace_app")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE trace IN SCHEMA auth GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trace_app")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE trace IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trace_app")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE trace IN SCHEMA private GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trace_app")


def downgrade() -> None:
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA auth, public, private FROM trace_app")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA auth, public, private FROM trace_app")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE trace IN SCHEMA auth REVOKE ALL ON TABLES FROM trace_app")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE trace IN SCHEMA public REVOKE ALL ON TABLES FROM trace_app")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE trace IN SCHEMA private REVOKE ALL ON TABLES FROM trace_app")
    op.execute("REVOKE USAGE ON SCHEMA auth, public, private FROM trace_app")
    op.execute(
        """
        DO $$
        BEGIN
          EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM trace_app', current_database());
        END $$;
        """
    )
    op.execute("DROP SCHEMA IF EXISTS private CASCADE")
    op.execute("DROP TABLE IF EXISTS public.projects")
    op.execute("DROP TABLE IF EXISTS public.users")
    op.execute("DROP TYPE IF EXISTS public.project_source_type")
    op.execute("DROP SCHEMA IF EXISTS auth CASCADE")
    op.execute("DROP ROLE IF EXISTS trace_app")
