from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from audit.runtime import get_audit_recorder
from db.session import close_cached_engines, get_engine
from main import create_app

pytestmark = pytest.mark.integration


def _application_connection_count(engine: sa.Engine, application_name: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = :application_name "
                "AND backend_type = 'client backend'"
            ),
            {"application_name": application_name},
        ).scalar_one()


def test_repeated_app_lifecycles_dispose_cached_postgresql_pools(
    integration_database_url: str,
    integration_engine: sa.Engine,
    integration_settings,
    monkeypatch,
) -> None:
    application_name = "trace-phase4-lifecycle-test"
    database_url = sa.engine.make_url(integration_database_url).update_query_dict(
        {"application_name": application_name}
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        database_url.render_as_string(hide_password=False),
    )
    get_audit_recorder.cache_clear()
    close_cached_engines()

    try:
        for _ in range(3):
            application = create_app(integration_settings)
            with TestClient(application), get_engine().connect() as connection:
                connection.execute(sa.text("SELECT 1"))

            assert get_engine.cache_info().currsize == 0
            assert (
                _application_connection_count(integration_engine, application_name) == 0
            )
    finally:
        get_audit_recorder.cache_clear()
        close_cached_engines()
