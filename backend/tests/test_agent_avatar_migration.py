from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

import db.model_registry  # noqa: F401
from agents.avatar import MAX_AVATAR_BYTES, MAX_AVATAR_CONFIG_BYTES
from auth.rate_limit import AUTH_RATE_LIMIT_POLICIES
from db.base import Base

BACKEND = Path(__file__).parents[1]


def _migration_source() -> str:
    return (BACKEND / "alembic/versions/20261101_0056_agent_avatars.py").read_text()


def test_avatar_migration_extends_the_single_head() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["20261101_0056"]
    assert script.get_revision("20261101_0056").down_revision == "20261030_0055"


def test_avatar_migration_isolates_owners_and_limits_the_public_function() -> None:
    source = _migration_source()

    assert "ALTER TABLE private.agent_avatars ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE private.agent_avatars FORCE ROW LEVEL SECURITY" in source
    assert "owner_id = public.trace_current_user_id()" in source
    assert "REFERENCES public.agents(owner_id, id) ON DELETE CASCADE" in source
    assert f"byte_size <= {MAX_AVATAR_BYTES}" in source
    assert f"octet_length(avatar_config::text) <= {MAX_AVATAR_CONFIG_BYTES}" in source
    assert "SECURITY DEFINER" in source
    assert "SET search_path = pg_catalog, private" in source
    assert "REVOKE ALL ON FUNCTION public.read_agent_avatar(uuid) FROM PUBLIC" in source
    assert (
        "GRANT EXECUTE ON FUNCTION public.read_agent_avatar(uuid) TO trace_app"
        in source
    )
    assert "DROP FUNCTION public.read_agent_avatar(uuid)" in source
    assert "DROP TABLE private.agent_avatars" in source


def test_avatar_models_match_the_migration_contract() -> None:
    table = Base.metadata.tables["private.agent_avatars"]

    assert [column.name for column in table.primary_key.columns] == ["agent_id"]
    assert {constraint.name for constraint in table.constraints} >= {
        "agent_avatars_byte_size_check",
        "agent_avatars_byte_size_match_check",
        "agent_avatars_owner_agent_fkey",
    }
    foreign_key = next(iter(table.foreign_key_constraints))
    assert foreign_key.ondelete == "CASCADE"
    assert {element.target_fullname for element in foreign_key.elements} == {
        "public.agents.owner_id",
        "public.agents.id",
    }
    agents = Base.metadata.tables["public.agents"]
    assert agents.c.avatar_config.nullable
    assert "agents_avatar_config_check" in {
        constraint.name for constraint in agents.constraints
    }


def test_avatar_writes_have_their_own_rate_limit_policy() -> None:
    policy = AUTH_RATE_LIMIT_POLICIES["resource.avatar_write.user"]
    reference = AUTH_RATE_LIMIT_POLICIES["resource.credential_write.user"]

    assert policy.capacity == reference.capacity
    assert policy.refill_period_seconds == reference.refill_period_seconds
