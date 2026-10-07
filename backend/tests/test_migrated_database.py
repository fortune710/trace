import os

import pytest
import sqlalchemy as sa


@pytest.mark.integration
def test_isolated_database_is_migrated_to_the_schema_contract() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url

    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert {"auth", "private", "public"}.issubset(set(inspector.get_schema_names()))
        assert {
            "users",
            "sessions",
            "refresh_tokens",
            "email_delivery_jobs",
        }.issubset(set(inspector.get_table_names(schema="auth")))
        assert {"users", "projects"}.issubset(
            set(inspector.get_table_names(schema="public"))
        )
        assert {
            "credentials",
            "credential_reencryption_runs",
            "credential_reencryption_items",
        }.issubset(set(inspector.get_table_names(schema="private")))
    finally:
        engine.dispose()
