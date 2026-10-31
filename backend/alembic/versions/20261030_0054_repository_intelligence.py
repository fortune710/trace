"""Persist revision-scoped repository intelligence.

Revision ID: 20261030_0054
Revises: 20261029_0051
"""

from alembic import op

revision = "20261030_0054"
down_revision = "20261029_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE private.repository_intelligence_snapshots (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          project_id uuid NOT NULL,
          source_kind public.repository_source NOT NULL,
          source_identifier text NOT NULL,
          source_revision text NOT NULL,
          integrity_algorithm text NOT NULL,
          analyzer_version text NOT NULL,
          status text NOT NULL CHECK (status IN ('pending','running','ready','failed')),
          attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
          claimed_at timestamptz NULL,
          manifest_digest text NULL,
          summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          completed_at timestamptz NULL,
          CONSTRAINT intelligence_snapshots_owner_id_key UNIQUE (owner_id,id),
          CONSTRAINT intelligence_snapshots_revision_key UNIQUE
            (owner_id,source_kind,source_identifier,source_revision,analyzer_version),
          FOREIGN KEY (owner_id,project_id) REFERENCES public.projects(owner_id,id)
            ON DELETE CASCADE
        );
        CREATE TABLE private.repository_intelligence_facts (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL,
          snapshot_id uuid NOT NULL,
          kind text NOT NULL,
          path text NOT NULL,
          symbol text NULL,
          line_start integer NULL,
          line_end integer NULL,
          attributes_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          evidence_digest text NOT NULL,
          CONSTRAINT intelligence_facts_owner_snapshot_id_key
            UNIQUE (owner_id,snapshot_id,id),
          FOREIGN KEY (owner_id,snapshot_id)
            REFERENCES private.repository_intelligence_snapshots(owner_id,id)
            ON DELETE CASCADE
        );
        CREATE INDEX intelligence_facts_lookup_idx
          ON private.repository_intelligence_facts(snapshot_id,kind,path);
        CREATE TABLE private.repository_intelligence_edges (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL,
          snapshot_id uuid NOT NULL,
          from_fact_id uuid NOT NULL,
          to_fact_id uuid NOT NULL,
          relationship text NOT NULL,
          evidence_path text NOT NULL,
          evidence_line integer NULL,
          FOREIGN KEY (owner_id,snapshot_id)
            REFERENCES private.repository_intelligence_snapshots(owner_id,id)
            ON DELETE CASCADE,
          FOREIGN KEY (owner_id,snapshot_id,from_fact_id)
            REFERENCES private.repository_intelligence_facts(owner_id,snapshot_id,id)
            ON DELETE CASCADE,
          FOREIGN KEY (owner_id,snapshot_id,to_fact_id)
            REFERENCES private.repository_intelligence_facts(owner_id,snapshot_id,id)
            ON DELETE CASCADE
        );
        CREATE TABLE private.repository_static_rule_hits (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL,
          snapshot_id uuid NOT NULL,
          rule_id text NOT NULL,
          rule_version integer NOT NULL,
          path text NOT NULL,
          line_start integer NOT NULL,
          line_end integer NULL,
          severity text NOT NULL,
          confidence text NOT NULL,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          evidence_digest text NOT NULL,
          FOREIGN KEY (owner_id,snapshot_id)
            REFERENCES private.repository_intelligence_snapshots(owner_id,id)
            ON DELETE CASCADE,
          CONSTRAINT intelligence_rule_hit_key
            UNIQUE (snapshot_id,rule_id,rule_version,path,line_start)
        );
        """
    )
    for table in (
        "repository_intelligence_snapshots",
        "repository_intelligence_facts",
        "repository_intelligence_edges",
        "repository_static_rule_hits",
    ):
        op.execute(f"ALTER TABLE private.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE private.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_owner_isolation ON private.{table} "
            "USING (owner_id = public.trace_current_user_id()) "
            "WITH CHECK (owner_id = public.trace_current_user_id())"
        )
        op.execute(
            f"CREATE POLICY {table}_internal_worker ON private.{table} "
            "TO trace_internal USING (true) WITH CHECK (true)"
        )
        op.execute(f"REVOKE ALL ON private.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON private.{table} TO trace_internal")
        op.execute(f"GRANT SELECT, INSERT ON private.{table} TO trace_app")
    op.execute("GRANT UPDATE ON private.repository_intelligence_snapshots TO trace_app")
    op.execute(
        "ALTER TABLE public.reviews ADD COLUMN intelligence_snapshot_id uuid NULL"
    )
    op.execute(
        "ALTER TABLE public.reviews ADD CONSTRAINT reviews_intelligence_snapshot_fkey "
        "FOREIGN KEY (owner_id,intelligence_snapshot_id) "
        "REFERENCES private.repository_intelligence_snapshots(owner_id,id) ON DELETE RESTRICT"
    )
    op.execute("""
        CREATE TABLE private.local_review_source_snapshots (
          review_id uuid PRIMARY KEY,
          owner_id uuid NOT NULL,
          source_revision text NOT NULL,
          ciphertext bytea NOT NULL,
          nonce bytea NOT NULL,
          key_version text NOT NULL,
          encryption_provider text NOT NULL,
          key_reference text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (owner_id,review_id) REFERENCES public.reviews(owner_id,id) ON DELETE CASCADE
        )
    """)
    op.execute(
        "ALTER TABLE private.local_review_source_snapshots ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE private.local_review_source_snapshots FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY local_source_owner ON private.local_review_source_snapshots USING (owner_id = public.trace_current_user_id()) WITH CHECK (owner_id = public.trace_current_user_id())"
    )
    op.execute(
        "CREATE POLICY local_source_internal ON private.local_review_source_snapshots TO trace_internal USING (true) WITH CHECK (true)"
    )
    op.execute("REVOKE ALL ON private.local_review_source_snapshots FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT ON private.local_review_source_snapshots TO trace_app, trace_internal"
    )
    op.execute("""
        CREATE FUNCTION private.reject_review_intelligence_snapshot_change()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.intelligence_snapshot_id IS DISTINCT FROM OLD.intelligence_snapshot_id THEN
            RAISE EXCEPTION 'review intelligence snapshot is immutable';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER reviews_intelligence_snapshot_immutable
        BEFORE UPDATE ON public.reviews FOR EACH ROW
        EXECUTE FUNCTION private.reject_review_intelligence_snapshot_change()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER reviews_intelligence_snapshot_immutable ON public.reviews")
    op.execute("DROP FUNCTION private.reject_review_intelligence_snapshot_change()")
    op.execute("DROP TABLE private.local_review_source_snapshots")
    op.execute("ALTER TABLE public.reviews DROP COLUMN intelligence_snapshot_id")
    for table in (
        "repository_intelligence_edges",
        "repository_static_rule_hits",
        "repository_intelligence_facts",
        "repository_intelligence_snapshots",
    ):
        op.execute(f"DROP TABLE private.{table}")
