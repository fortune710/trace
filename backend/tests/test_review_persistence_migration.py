from pathlib import Path


def test_review_persistence_migration_has_defensive_upgrade_and_safe_downgrade() -> (
    None
):
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261017_0020_rename_reviews_add_dispatch_outbox.py"
    )
    source = migration.read_text()

    assert 'down_revision = "20261017_0019"' in source
    assert (
        "LOCK TABLE public.review_runs, public.review_run_agents, public.findings"
        in source
    )
    assert "def _state() -> str:" in source
    assert "refusing to mutate it" in source
    assert "_assert_assignment_ids_are_uuid7_and_unique()" in source
    assert "public.review_runs RENAME TO reviews" in source
    assert "public.review_run_agents RENAME TO review_agents" in source
    assert "private.review_dispatch_jobs" in source
    assert (
        "cannot downgrade review persistence while dispatch jobs still exist" in source
    )
    assert "DROP" in source
    assert "DROP ... CASCADE" not in source
