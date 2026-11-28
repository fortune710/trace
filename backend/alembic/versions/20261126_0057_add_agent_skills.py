"""Persist per-agent skills.sh attachments with owner RLS.

Revision ID: 20261126_0057
Revises: 20261101_0056
"""

from alembic import op

revision = "20261126_0057"
down_revision = "20261101_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.agent_skills (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(),
          owner_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          agent_id uuid NOT NULL,
          skill_id text NOT NULL
            CONSTRAINT agent_skills_skill_id_length
              CHECK (char_length(skill_id) BETWEEN 3 AND 256),
          slug text NOT NULL
            CONSTRAINT agent_skills_slug_length
              CHECK (char_length(slug) BETWEEN 1 AND 128),
          name text NOT NULL
            CONSTRAINT agent_skills_name_length
              CHECK (char_length(name) BETWEEN 1 AND 200),
          source text NOT NULL
            CONSTRAINT agent_skills_source_length
              CHECK (char_length(source) BETWEEN 1 AND 200),
          source_type text NOT NULL
            CONSTRAINT agent_skills_source_type_allowed
              CHECK (source_type IN ('github', 'well-known')),
          install_url text NULL
            CONSTRAINT agent_skills_install_url_length
              CHECK (install_url IS NULL OR char_length(install_url) <= 2048),
          url text NOT NULL
            CONSTRAINT agent_skills_url_length
              CHECK (char_length(url) BETWEEN 1 AND 2048),
          content_hash text NULL
            CONSTRAINT agent_skills_content_hash_length
              CHECK (content_hash IS NULL OR char_length(content_hash) <= 128),
          skill_md text NOT NULL
            CONSTRAINT agent_skills_skill_md_length
              CHECK (char_length(skill_md) BETWEEN 1 AND 200000),
          files jsonb NOT NULL DEFAULT '[]'::jsonb
            CONSTRAINT agent_skills_files_array
              CHECK (jsonb_typeof(files) = 'array'),
          sort_order integer NOT NULL DEFAULT 0
            CONSTRAINT agent_skills_sort_order_range
              CHECK (sort_order BETWEEN 0 AND 63),
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT agent_skills_owner_id_id_key UNIQUE (owner_id, id),
          CONSTRAINT agent_skills_owner_agent_skill_unique UNIQUE (owner_id, agent_id, skill_id),
          CONSTRAINT agent_skills_owner_agent_fkey
            FOREIGN KEY (owner_id, agent_id)
            REFERENCES public.agents(owner_id, id)
            ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_skills_owner_agent_sort_idx "
        "ON public.agent_skills(owner_id, agent_id, sort_order, created_at)"
    )
    op.execute("ALTER TABLE public.agent_skills ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.agent_skills FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY agent_skills_owner_isolation ON public.agent_skills "
        "FOR ALL "
        "USING (owner_id = public.trace_current_user_id()) "
        "WITH CHECK (owner_id = public.trace_current_user_id())"
    )
    op.execute("REVOKE ALL ON public.agent_skills FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON public.agent_skills TO trace_app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE public.agent_skills")
