from fastapi.testclient import TestClient

from webxray_agent.bootstrap import bootstrap_app, create_bootstrap_app


def test_bootstrap_app_imports() -> None:
    assert bootstrap_app is not None
    assert create_bootstrap_app() is not bootstrap_app


def test_bootstrap_status() -> None:
    response = TestClient(bootstrap_app).get("/bootstrap/v1/status")

    assert response.status_code == 410
    assert response.json()["error_class"] == "bootstrap_closed"
