from fastapi.testclient import TestClient

from backend.app.main import app, create_app


def test_backend_app_imports() -> None:
    assert app is not None
    assert create_app() is not app


def test_backend_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend"}
