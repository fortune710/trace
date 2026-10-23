from __future__ import annotations

from db import session


class _DisposableEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


def test_close_cached_engines_disposes_pools_before_clearing_cache(monkeypatch) -> None:
    primary = _DisposableEngine()
    maintenance = _DisposableEngine()
    engines = iter((primary, maintenance))
    session.get_engine.cache_clear()
    session.get_maintenance_engine.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://primary.example.test/trace")
    monkeypatch.setenv(
        "MAINTENANCE_DATABASE_URL", "postgresql://maintenance.example.test/trace"
    )
    monkeypatch.setattr(session, "create_engine", lambda *_args, **_kwargs: next(engines))

    try:
        assert session.get_engine() is primary
        assert session.get_maintenance_engine() is maintenance

        session.close_cached_engines()

        assert primary.dispose_calls == 1
        assert maintenance.dispose_calls == 1
        assert session.get_engine.cache_info().currsize == 0
        assert session.get_maintenance_engine.cache_info().currsize == 0
    finally:
        session.get_engine.cache_clear()
        session.get_maintenance_engine.cache_clear()
