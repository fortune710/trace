from __future__ import annotations

from pathlib import Path


def test_repository_metadata_migration_has_upgrade_and_downgrade_contract() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic/versions/20261008_0015_add_repository_source_metadata.py"
    )
    source = migration.read_text()

    assert 'revision = "20261008_0015"' in source
    assert 'down_revision = "20261007_0014"' in source
    for column in (
        "repository_owner",
        "repository_name",
        "branch_name",
        "repository_visibility",
        "imported_at",
    ):
        assert f'"{column}"' in source
    assert '"projects_owner_external_repository_key"' in source
    assert "source = 'github' AND archived_at IS NULL" in source
