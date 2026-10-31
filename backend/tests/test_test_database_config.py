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


def test_production_vault_workers_start_through_their_token_loading_scripts() -> None:
    import yaml

    compose = yaml.safe_load((ROOT_DIRECTORY / "compose.production.yaml").read_text())

    for name, service in compose["services"].items():
        mounts_vault_token = any(
            secret.get("source") == "vault_runtime_token"
            for secret in service.get("secrets", [])
        )
        command = service.get("command")
        if not mounts_vault_token or command is None:
            continue
        # Vault encryption reads AUTH_VAULT_TOKEN, which only the start scripts
        # derive from the mounted AUTH_VAULT_TOKEN_FILE.
        assert command[0].startswith("./start-"), name
        assert (ROOT_DIRECTORY / "backend" / command[0]).is_file(), name


def test_nginx_admits_the_largest_valid_local_source_upload() -> None:
    import re

    from resources.schemas import LocalSourceUpload

    https = (ROOT_DIRECTORY / "config/nginx/https.conf").read_text()
    block = re.search(
        r"location = /api/v1/reviews \{(?P<body>[^}]*)\}", https, re.DOTALL
    )
    assert block is not None
    limit = re.search(r"client_max_body_size (\d+)m;", block["body"])
    assert limit is not None

    entries = LocalSourceUpload.model_fields["entries"]
    max_entries = next(
        item.max_length for item in entries.metadata if hasattr(item, "max_length")
    )
    # The base64 budget enforced by the schema, then per entry a 1,024 character
    # path (up to 4 bytes each in UTF-8) plus roughly 200 bytes of JSON structure.
    base64_budget = 5_400_000
    worst_case = base64_budget + max_entries * (1_024 * 4 + 200)

    assert int(limit[1]) * 1024 * 1024 >= worst_case
    # Every other backend route keeps NGINX's default request body limit.
    assert https.count("client_max_body_size") == 1
