"""Generalize provider resources and add owner-isolated review resources."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261007_0008"
down_revision = "20261007_0007"
branch_labels = None
depends_on = None


RESOURCE_TABLES = (
    "external_repositories",
    "projects",
    "agents",
    "review_runs",
    "review_run_agents",
    "review_run_categories",
    "findings",
    "remediations",
    "pull_requests",
    "local_file_backups",
)


def _create_enum(name: str, values: str) -> None:
    op.execute(f"CREATE TYPE public.{name} AS ENUM ({values})")


def _drop_resource_policy(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_owner_isolation ON public.{table}")


def _create_resource_policy(table: str) -> None:
    op.execute(
        f"""
        ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS {table}_owner_isolation ON public.{table};
        CREATE POLICY {table}_owner_isolation ON public.{table}
          USING (owner_id = public.trace_current_user_id())
          WITH CHECK (owner_id = public.trace_current_user_id());
        """
    )


def upgrade() -> None:
    _create_enum("repository_source", "'github', 'local'")
    _create_enum(
        "project_category",
        "'entertainment', 'educational', 'sports', 'gaming', 'business', 'health', 'finance', 'social', 'productivity', 'e_commerce', 'other'",
    )
    _create_enum(
        "review_category",
        "'security', 'engineering', 'product', 'legal', 'accessibility'",
    )
    _create_enum(
        "review_status", "'queued', 'running', 'completed', 'failed', 'cancelled'"
    )
    _create_enum(
        "review_run_agent_status",
        "'assigned', 'running', 'completed', 'failed', 'cancelled'",
    )
    _create_enum("finding_severity", "'info', 'low', 'medium', 'high', 'critical'")
    _create_enum("finding_status", "'open', 'accepted', 'resolved', 'dismissed'")
    _create_enum("remediation_status", "'proposed', 'approved', 'rejected', 'applied'")

    # The old project enum and provider-specific identifier are migrated in
    # place so existing project rows retain their identity and timestamps.
    op.execute(
        "ALTER TABLE public.projects DROP CONSTRAINT IF EXISTS projects_source_reference_check"
    )
    op.execute("DROP INDEX IF EXISTS public.projects_owner_github_repository_key")
    op.execute("DROP INDEX IF EXISTS public.projects_owner_local_path_key")
    op.execute("ALTER TABLE public.projects RENAME COLUMN source_type TO source")
    op.execute(
        "ALTER TABLE public.projects ALTER COLUMN source TYPE public.repository_source "
        "USING source::text::public.repository_source"
    )
    op.execute(
        "ALTER TABLE public.projects RENAME COLUMN github_repository_id TO external_repository_id"
    )
    op.execute(
        "ALTER TABLE public.projects ALTER COLUMN external_repository_id TYPE text "
        "USING external_repository_id::text"
    )
    op.execute("DROP TYPE public.project_source_type")
    op.add_column(
        "projects",
        sa.Column("external_repository_connection_id", sa.UUID(), nullable=True),
        schema="public",
    )
    op.add_column(
        "projects",
        sa.Column(
            "category",
            sa.Enum(
                "entertainment",
                "educational",
                "sports",
                "gaming",
                "business",
                "health",
                "finance",
                "social",
                "productivity",
                "e_commerce",
                "other",
                name="project_category",
                schema="public",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'other'::public.project_category"),
        ),
        schema="public",
    )
    op.add_column(
        "projects",
        sa.Column(
            "auto_create_pull_requests",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema="public",
    )
    op.create_unique_constraint(
        "projects_owner_id_id_key", "projects", ["owner_id", "id"], schema="public"
    )

    op.create_unique_constraint(
        "credentials_owner_id_id_key",
        "credentials",
        ["owner_id", "id"],
        schema="private",
    )

    op.create_table(
        "external_repositories",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("public.uuidv7()")
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "github",
                "local",
                name="repository_source",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("external_user_id", sa.Text(), nullable=False),
        sa.Column("credential_id", sa.UUID(), nullable=False),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "source = 'github'", name="external_repositories_github_only_check"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "credential_id"],
            ["private.credentials.owner_id", "private.credentials.id"],
            name="external_repositories_owner_credential_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "id", name="external_repositories_owner_id_id_key"
        ),
        schema="public",
    )
    op.create_index(
        "external_repositories_owner_active_key",
        "external_repositories",
        ["owner_id", "source", "external_user_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_foreign_key(
        "projects_owner_external_repository_connection_fkey",
        "projects",
        "external_repositories",
        ["owner_id", "external_repository_connection_id"],
        ["owner_id", "id"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "projects_source_reference_check",
        "projects",
        "(source = 'github' AND external_repository_id IS NOT NULL AND external_repository_connection_id IS NOT NULL AND local_path_hash IS NULL) "
        "OR (source = 'local' AND local_path_hash IS NOT NULL AND external_repository_id IS NULL AND external_repository_connection_id IS NULL)",
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
    op.create_index(
        "projects_owner_local_path_key",
        "projects",
        ["owner_id", "local_path_hash"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("source = 'local' AND archived_at IS NULL"),
    )

    op.create_table(
        "agents",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("public.uuidv7()")
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("personality", sa.Text(), nullable=True),
        sa.Column(
            "review_category",
            sa.Enum(
                "security",
                "engineering",
                "product",
                "legal",
                "accessibility",
                name="review_category",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("model_provider", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column(
            "skills",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "fallback_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "id", name="agents_owner_id_id_key"),
        schema="public",
    )
    op.create_table(
        "review_runs",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("public.uuidv7()")
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("source_revision", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="review_status",
                schema="public",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'queued'::public.review_status"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["public.projects.owner_id", "public.projects.id"],
            name="review_runs_owner_project_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "id", name="review_runs_owner_id_id_key"),
        schema="public",
    )
    op.create_table(
        "review_run_agents",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("review_run_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "assigned",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="review_run_agent_status",
                schema="public",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'assigned'::public.review_run_agent_status"),
        ),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_run_id"],
            ["public.review_runs.owner_id", "public.review_runs.id"],
            name="review_run_agents_owner_run_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "agent_id"],
            ["public.agents.owner_id", "public.agents.id"],
            name="review_run_agents_owner_agent_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("review_run_id", "agent_id"),
        sa.UniqueConstraint(
            "owner_id",
            "review_run_id",
            "agent_id",
            name="review_run_agents_owner_tuple_key",
        ),
        schema="public",
    )
    op.create_table(
        "review_run_categories",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("review_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "security",
                "engineering",
                "product",
                "legal",
                "accessibility",
                name="review_category",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_run_id"],
            ["public.review_runs.owner_id", "public.review_runs.id"],
            name="review_run_categories_owner_run_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("review_run_id", "category"),
        schema="public",
    )
    op.create_table(
        "findings",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("public.uuidv7()")
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("review_run_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "security",
                "engineering",
                "product",
                "legal",
                "accessibility",
                name="review_category",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "low",
                "medium",
                "high",
                "critical",
                name="finding_severity",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("source_location", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "review_run_id", "agent_id"],
            [
                "public.review_run_agents.owner_id",
                "public.review_run_agents.review_run_id",
                "public.review_run_agents.agent_id",
            ],
            name="findings_owner_run_agent_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "id", name="findings_owner_id_id_key"),
        schema="public",
    )
    op.create_table(
        "remediations",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("public.uuidv7()")
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("proposed_diff", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "proposed",
                "approved",
                "rejected",
                "applied",
                name="remediation_status",
                schema="public",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'proposed'::public.remediation_status"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["public.projects.owner_id", "public.projects.id"],
            name="remediations_owner_project_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "finding_id"],
            ["public.findings.owner_id", "public.findings.id"],
            name="remediations_owner_finding_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "id", name="remediations_owner_id_id_key"),
        schema="public",
    )
    op.create_table(
        "pull_requests",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("public.uuidv7()")
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("remediation_id", sa.UUID(), nullable=False),
        sa.Column("repository_url", sa.Text(), nullable=False),
        sa.Column("pull_request_number", sa.BigInteger(), nullable=False),
        sa.Column("pull_request_url", sa.Text(), nullable=False),
        sa.Column("branch_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "remediation_id"],
            ["public.remediations.owner_id", "public.remediations.id"],
            name="pull_requests_owner_remediation_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "id", name="pull_requests_owner_id_id_key"),
        sa.UniqueConstraint(
            "owner_id", "remediation_id", name="pull_requests_owner_remediation_key"
        ),
        schema="public",
    )
    op.create_table(
        "local_file_backups",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("public.uuidv7()")
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("remediation_id", sa.UUID(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("backup_path", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "remediation_id"],
            ["public.remediations.owner_id", "public.remediations.id"],
            name="local_file_backups_owner_remediation_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "id", name="local_file_backups_owner_id_id_key"
        ),
        sa.UniqueConstraint(
            "owner_id",
            "remediation_id",
            name="local_file_backups_owner_remediation_key",
        ),
        schema="public",
    )

    for table in RESOURCE_TABLES:
        _create_resource_policy(table)

    # A revoked connection is retained for historical attribution, but cannot
    # be selected for a newly created or reassigned GitHub project.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trace_require_active_external_repository()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
          IF NEW.source = 'github' AND NOT EXISTS (
            SELECT 1
            FROM public.external_repositories AS repository
            WHERE repository.owner_id = NEW.owner_id
              AND repository.id = NEW.external_repository_connection_id
              AND repository.source = 'github'
              AND repository.revoked_at IS NULL
          ) THEN
            RAISE EXCEPTION 'external repository connection must be active'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION public.trace_require_active_external_repository() FROM PUBLIC;
        CREATE TRIGGER projects_require_active_external_repository
          BEFORE INSERT OR UPDATE OF source, external_repository_connection_id
          ON public.projects
          FOR EACH ROW EXECUTE FUNCTION public.trace_require_active_external_repository();
        """
    )

    existence_functions = {
        "external_repository": "public.external_repositories",
        "agent": "public.agents",
        "review_run": "public.review_runs",
        "finding": "public.findings",
        "remediation": "public.remediations",
        "pull_request": "public.pull_requests",
        "local_file_backup": "public.local_file_backups",
    }
    for function_name, table in existence_functions.items():
        op.execute(
            f"""
            CREATE OR REPLACE FUNCTION public.trace_{function_name}_exists(resource_id uuid)
            RETURNS boolean
            LANGUAGE sql
            STABLE
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $fn$
              SELECT EXISTS(SELECT 1 FROM {table} AS resource WHERE resource.id = $1)
            $fn$;
            REVOKE ALL ON FUNCTION public.trace_{function_name}_exists(uuid) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.trace_{function_name}_exists(uuid) TO trace_app;
            """
        )

    for table in RESOURCE_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO trace_app"
        )
        if table != "projects":
            op.execute(f"CREATE INDEX {table}_owner_idx ON public.{table} (owner_id)")


def downgrade() -> None:
    for function_name in (
        "local_file_backup",
        "pull_request",
        "remediation",
        "finding",
        "review_run",
        "agent",
        "external_repository",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS public.trace_{function_name}_exists(uuid)")
    op.execute(
        "DROP TRIGGER IF EXISTS projects_require_active_external_repository ON public.projects"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS public.trace_require_active_external_repository()"
    )

    for table in reversed(RESOURCE_TABLES):
        op.execute(f"REVOKE ALL ON public.{table} FROM trace_app")
        _drop_resource_policy(table)
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP INDEX IF EXISTS public.{table}_owner_idx")

    for table in (
        "local_file_backups",
        "pull_requests",
        "remediations",
        "findings",
        "review_run_categories",
        "review_run_agents",
        "review_runs",
        "agents",
        "external_repositories",
    ):
        op.drop_table(table, schema="public")

    op.drop_constraint(
        "projects_source_reference_check", "projects", schema="public", type_="check"
    )
    op.drop_constraint(
        "projects_owner_external_repository_connection_fkey",
        "projects",
        schema="public",
        type_="foreignkey",
    )
    op.drop_constraint(
        "projects_owner_id_id_key", "projects", schema="public", type_="unique"
    )
    op.drop_index(
        "projects_owner_external_repository_key", table_name="projects", schema="public"
    )
    op.drop_index(
        "projects_owner_local_path_key", table_name="projects", schema="public"
    )
    op.drop_column("projects", "auto_create_pull_requests", schema="public")
    op.drop_column("projects", "category", schema="public")
    op.drop_column("projects", "external_repository_connection_id", schema="public")
    op.execute(
        "ALTER TABLE public.projects RENAME COLUMN external_repository_id TO github_repository_id"
    )
    op.execute(
        "ALTER TABLE public.projects ALTER COLUMN github_repository_id TYPE bigint "
        "USING CASE WHEN github_repository_id ~ '^[0-9]+$' THEN github_repository_id::bigint ELSE NULL END"
    )
    _create_enum("project_source_type", "'github', 'local'")
    op.execute("ALTER TABLE public.projects RENAME COLUMN source TO source_type")
    op.execute(
        "ALTER TABLE public.projects ALTER COLUMN source_type TYPE public.project_source_type "
        "USING source_type::text::public.project_source_type"
    )
    op.execute("DROP TYPE public.repository_source")
    op.create_check_constraint(
        "projects_source_reference_check",
        "projects",
        "(source_type = 'github' AND github_repository_id IS NOT NULL AND local_path_hash IS NULL) "
        "OR (source_type = 'local' AND local_path_hash IS NOT NULL AND github_repository_id IS NULL)",
        schema="public",
    )
    op.execute(
        "CREATE UNIQUE INDEX projects_owner_github_repository_key "
        "ON public.projects (owner_id, github_repository_id) "
        "WHERE source_type = 'github' AND archived_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX projects_owner_local_path_key "
        "ON public.projects (owner_id, local_path_hash) "
        "WHERE source_type = 'local' AND archived_at IS NULL"
    )
    op.drop_constraint(
        "credentials_owner_id_id_key", "credentials", schema="private", type_="unique"
    )
    for enum_name in (
        "remediation_status",
        "finding_status",
        "finding_severity",
        "review_run_agent_status",
        "review_status",
        "review_category",
        "project_category",
    ):
        op.execute(f"DROP TYPE public.{enum_name}")
