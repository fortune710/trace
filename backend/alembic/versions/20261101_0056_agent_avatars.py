"""Store agent avatar images and the editor configuration that produced them."""

from alembic import op

revision = "20261101_0056"
down_revision = "20261030_0055"
branch_labels = None
depends_on = None


def upgrade():
    # trace_app already holds table-level SELECT/INSERT/UPDATE on public.agents,
    # so the new column needs no separate column grant.
    op.execute("""
        ALTER TABLE public.agents
          ADD COLUMN avatar_config jsonb NULL,
          ADD CONSTRAINT agents_avatar_config_check CHECK (
            avatar_config IS NULL
            OR (jsonb_typeof(avatar_config) = 'object'
                AND octet_length(avatar_config::text) <= 1024)
          )
    """)
    op.execute("""
        CREATE TABLE private.agent_avatars (
          owner_id uuid NOT NULL,
          agent_id uuid PRIMARY KEY,
          content_type text NOT NULL,
          data bytea NOT NULL,
          sha256 text NOT NULL,
          byte_size integer NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT agent_avatars_byte_size_check CHECK (byte_size <= 262144),
          CONSTRAINT agent_avatars_byte_size_match_check CHECK (octet_length(data) = byte_size),
          CONSTRAINT agent_avatars_owner_agent_fkey
            FOREIGN KEY (owner_id, agent_id)
            REFERENCES public.agents(owner_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("ALTER TABLE private.agent_avatars ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE private.agent_avatars FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY agent_avatars_owner ON private.agent_avatars "
        "USING (owner_id = public.trace_current_user_id()) "
        "WITH CHECK (owner_id = public.trace_current_user_id())"
    )
    op.execute("REVOKE ALL ON private.agent_avatars FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON private.agent_avatars TO trace_app"
    )
    # The public GET has no principal, so owner RLS would hide every row from
    # trace_app. This function runs as its (RLS-exempt) owner, like the existing
    # trace_*_exists helpers, and exposes one avatar by id and nothing else.
    op.execute("""
        CREATE FUNCTION public.read_agent_avatar(agent_id uuid)
        RETURNS TABLE (content_type text, data bytea, sha256 text)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, private
        AS $fn$
          SELECT avatar.content_type, avatar.data, avatar.sha256
          FROM private.agent_avatars AS avatar
          WHERE avatar.agent_id = $1
        $fn$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.read_agent_avatar(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.read_agent_avatar(uuid) TO trace_app")


def downgrade():
    op.execute("DROP FUNCTION public.read_agent_avatar(uuid)")
    op.execute("DROP TABLE private.agent_avatars")
    op.execute("""
        ALTER TABLE public.agents
          DROP CONSTRAINT agents_avatar_config_check,
          DROP COLUMN avatar_config
    """)
