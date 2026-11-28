from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

import db.model_registry  # noqa: F401
from db.base import Base

BACKEND = Path(__file__).parents[1]


def _migration_source() -> str:
    return (BACKEND / "alembic/versions/20261126_0057_add_agent_skills.py").read_text()


def test_agent_skills_migration_extends_the_single_head() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["20261126_0057"]
    assert script.get_revision("20261126_0057").down_revision == "20261101_0056"


def test_agent_skills_migration_enforces_owner_rls() -> None:
    source = _migration_source()

    assert "ALTER TABLE public.agent_skills ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE public.agent_skills FORCE ROW LEVEL SECURITY" in source
    assert "agent_skills_owner_isolation" in source
    assert "owner_id = public.trace_current_user_id()" in source
    assert "REFERENCES public.agents(owner_id, id)" in source
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON public.agent_skills TO trace_app"
        in source
    )


def test_agent_skills_model_matches_migration_contract() -> None:
    table = Base.metadata.tables["public.agent_skills"]

    assert {column.name for column in table.columns} >= {
        "id",
        "owner_id",
        "agent_id",
        "skill_id",
        "skill_md",
        "files",
        "sort_order",
    }
    assert "agent_skills_owner_agent_fkey" in {
        constraint.name for constraint in table.foreign_key_constraints
    }
