from fastapi.testclient import TestClient

from app.api import health
from app.main import app

client = TestClient(app)


def test_liveness_does_not_depend_on_database() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_database_status(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database", lambda: True)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readiness_returns_unavailable_when_database_is_down(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database", lambda: False)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
