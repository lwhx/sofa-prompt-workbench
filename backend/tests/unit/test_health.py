from fastapi.testclient import TestClient

from app.main import app


def test_live_health_check_is_public() -> None:
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_health_check_reports_dependencies() -> None:
    response = TestClient(app).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["database"] == "ok"

