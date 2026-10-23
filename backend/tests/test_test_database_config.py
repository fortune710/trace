from pathlib import Path

ROOT_DIRECTORY = Path(__file__).resolve().parents[2]


def _read_example_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT_DIRECTORY / ".env.example").read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key] = value
    return values


def test_test_database_uses_an_isolated_service_and_database() -> None:
    environment = _read_example_environment()

    assert (
        environment["TEST_MIGRATION_DATABASE_URL"]
        != environment["MIGRATION_DATABASE_URL"]
    )
    assert environment["TEST_DATABASE_URL"] != environment["DATABASE_URL"]
    assert (
        "@postgres-test:5432/trace_test" in environment["TEST_MIGRATION_DATABASE_URL"]
    )
    assert "@postgres-test:5432/trace_test" in environment["TEST_DATABASE_URL"]


def test_compose_defines_a_test_database_and_dedicated_migration_runner() -> None:
    compose = (ROOT_DIRECTORY / "compose.yaml").read_text()

    assert "  postgres-test:\n" in compose
    assert "      POSTGRES_DB: trace_test" in compose
    assert "  migrate-test:\n" in compose
    assert "TEST_MIGRATION_DATABASE_URL" in compose
