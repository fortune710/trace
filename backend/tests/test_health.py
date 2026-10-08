from fastapi.testclient import TestClient

from main import app


class AvailableRedis:
    async def ping(self) -> bool:
        return True


def test_liveness_endpoint_does_not_require_a_database() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint_hides_database_configuration_errors(monkeypatch) -> None:
    def unavailable_engine():
        raise RuntimeError("DATABASE_URL is not configured")

    monkeypatch.setattr("main.get_redis_client", lambda: AvailableRedis())
    monkeypatch.setattr("main.get_engine", unavailable_engine)

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readiness_endpoint_hides_redis_configuration_errors(monkeypatch) -> None:
    def unavailable_redis_client():
        raise RuntimeError("REDIS_URL is not configured")

    monkeypatch.setattr("main.get_redis_client", unavailable_redis_client)

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
