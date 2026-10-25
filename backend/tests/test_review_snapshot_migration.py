from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

from alembic import command

_PRE_SNAPSHOT_REVISION = "20261018_0022"
_SNAPSHOT_REVISION = "20261021_0023"


def _migration_url() -> URL:
    value = os.environ.get("MIGRATION_DATABASE_URL")
    assert value and "postgres-test" in value
    return make_url(value)


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


@contextmanager
def _contract_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[sa.Engine]:
    database_name = f"trace_snapshot_contract_{uuid4().hex}"
    migration_url = _migration_url()
    admin_engine = sa.create_engine(
        migration_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    engine: sa.Engine | None = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'CREATE DATABASE "{database_name}"'))
        contract_url = migration_url.set(database=database_name)
        monkeypatch.setenv(
            "MIGRATION_DATABASE_URL",
            contract_url.render_as_string(hide_password=False),
        )
        command.upgrade(_alembic_config(), _PRE_SNAPSHOT_REVISION)
        engine = sa.create_engine(contract_url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


@pytest.mark.integration
def test_review_snapshot_migration_upgrades_empty_tables_and_downgrades_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _contract_database(monkeypatch) as engine:
        command.upgrade(_alembic_config(), _SNAPSHOT_REVISION)

        with engine.connect() as connection:
            indexes = set(
                connection.execute(
                    sa.text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename IN ('reviews', 'review_agents')"
                    )
                ).scalars()
            )
            constraints = set(
                connection.execute(
                    sa.text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid IN ('public.reviews'::regclass, 'public.review_agents'::regclass)"
                    )
                ).scalars()
            )
            triggers = set(
                connection.execute(
                    sa.text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE tgrelid IN ('public.reviews'::regclass, 'public.review_agents'::regclass) "
                        "AND NOT tgisinternal"
                    )
                ).scalars()
            )
            attempt_table = connection.execute(
                sa.text("SELECT to_regclass('private.review_agent_attempts')")
            ).scalar_one()

        assert {
            "reviews_owner_project_idx",
            "reviews_owner_source_revision_idx",
            "review_agents_owner_agent_idx",
        } <= indexes
        assert "reviews_source_snapshot_check" in constraints
        assert {
            "reviews_snapshot_immutable",
            "review_agents_snapshot_immutable",
        } <= triggers
        assert attempt_table == "private.review_agent_attempts"

        command.downgrade(_alembic_config(), _PRE_SNAPSHOT_REVISION)
        with engine.connect() as connection:
            assert (
                connection.execute(
                    sa.text("SELECT to_regclass('private.review_agent_attempts')")
                ).scalar_one()
                is None
            )
            assert (
                connection.execute(
                    sa.text(
                        "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'reviews' "
                        "AND column_name = 'source_kind')"
                    )
                ).scalar_one()
                is False
            )


@pytest.mark.integration
@pytest.mark.parametrize("table", ("reviews", "review_agents"))
def test_review_snapshot_migration_refuses_historic_review_data(
    monkeypatch: pytest.MonkeyPatch,
    table: str,
) -> None:
    with _contract_database(monkeypatch) as engine:
        with engine.begin() as connection:
            connection.execute(sa.text("SET session_replication_role = replica"))
            if table == "reviews":
                connection.execute(
                    sa.text(
                        "INSERT INTO public.reviews(owner_id, project_id, source_revision) "
                        "VALUES (:owner_id, :project_id, 'legacy-review')"
                    ),
                    {"owner_id": uuid4(), "project_id": uuid4()},
                )
            else:
                connection.execute(
                    sa.text(
                        "INSERT INTO public.review_agents(owner_id, review_id, agent_id) "
                        "VALUES (:owner_id, :review_id, :agent_id)"
                    ),
                    {"owner_id": uuid4(), "review_id": uuid4(), "agent_id": uuid4()},
                )
            connection.execute(sa.text("SET session_replication_role = origin"))

        with pytest.raises(
            sa.exc.DatabaseError,
            match="review snapshot migration requires empty review tables",
        ):
            command.upgrade(_alembic_config(), _SNAPSHOT_REVISION)

        with engine.connect() as connection:
            assert (
                connection.execute(
                    sa.text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == _PRE_SNAPSHOT_REVISION
            )
