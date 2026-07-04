from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from webxray_agent.bootstrap import bootstrap_token_hash, create_bootstrap_app
from webxray_agent.config import AgentPaths, AgentState, AgentStateStore


def _iso(offset: timedelta) -> str:
    return (datetime.now(UTC) + offset).isoformat().replace("+00:00", "Z")


def _bootstrap_client(
    tmp_path: Path,
    *,
    raw_token: str = "bootstrap-token-secret",
    expires_in: timedelta = timedelta(minutes=15),
    absolute_expires_in: timedelta = timedelta(minutes=30),
) -> tuple[TestClient, AgentStateStore, AgentPaths, str]:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    store = AgentStateStore(paths)
    store.mark_bootstrap_pending(
        token_hash=bootstrap_token_hash(raw_token),
        expires_at=_iso(expires_in),
        absolute_expires_at=_iso(absolute_expires_in),
    )
    return TestClient(create_bootstrap_app(store)), store, paths, raw_token


def _auth(raw_token: str) -> dict[str, str]:
    return {"Authorization": f"Bootstrap {raw_token}"}


def test_bootstrap_status_requires_token_and_does_not_store_raw_token(
    tmp_path: Path,
) -> None:
    client, store, _, raw_token = _bootstrap_client(tmp_path)

    response = client.get("/bootstrap/v1/status")

    assert response.status_code == 401
    assert response.json()["error_class"] == "invalid_bootstrap_token"
    state_text = store.state_path.read_text(encoding="utf-8")
    assert raw_token not in state_text
    assert bootstrap_token_hash(raw_token) in state_text


def test_wrong_bootstrap_token_is_rejected(tmp_path: Path) -> None:
    client, _, _, _ = _bootstrap_client(tmp_path)

    response = client.get("/bootstrap/v1/status", headers=_auth("wrong-token"))

    assert response.status_code == 401
    assert response.json()["error_class"] == "invalid_bootstrap_token"


def test_expired_bootstrap_token_is_rejected(tmp_path: Path) -> None:
    client, _, _, raw_token = _bootstrap_client(
        tmp_path,
        expires_in=timedelta(seconds=-1),
        absolute_expires_in=timedelta(minutes=1),
    )

    response = client.get("/bootstrap/v1/status", headers=_auth(raw_token))

    assert response.status_code == 401
    assert response.json()["error_class"] == "invalid_bootstrap_token"


def test_csr_first_request_returns_not_ready_then_later_ready_with_csr(
    tmp_path: Path,
) -> None:
    client, _, paths, raw_token = _bootstrap_client(tmp_path)

    first = client.get("/bootstrap/v1/csr", headers=_auth(raw_token))
    second = client.get("/bootstrap/v1/csr", headers=_auth(raw_token))

    assert first.status_code == 202
    assert first.json()["status"] == "csr_not_ready"
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "csr_ready"
    assert "BEGIN CERTIFICATE REQUEST" in body["csr"]
    assert (paths.config_dir / "agent.key").exists()
    assert (paths.config_dir / "agent.csr").exists()


def test_certificate_install_transitions_to_paired_and_closes_bootstrap(
    tmp_path: Path,
) -> None:
    client, store, paths, raw_token = _bootstrap_client(tmp_path)
    client.get("/bootstrap/v1/csr", headers=_auth(raw_token))
    client.get("/bootstrap/v1/csr", headers=_auth(raw_token))
    certificate = "-----BEGIN CERTIFICATE-----\nagent-cert\n-----END CERTIFICATE-----\n"
    dashboard_ca = "-----BEGIN CERTIFICATE-----\ndashboard-ca\n-----END CERTIFICATE-----\n"

    install = client.post(
        "/bootstrap/v1/certificate",
        headers=_auth(raw_token),
        json={"certificate": certificate, "dashboard_ca": dashboard_ca},
    )
    after_success = client.get("/bootstrap/v1/status", headers=_auth(raw_token))

    assert install.status_code == 200
    assert install.json()["status"] == "certificate_installed"
    paired = store.load()
    assert paired.state == AgentState.PAIRED
    assert paired.bootstrap_token_hash is None
    assert paired.agent_cert_fingerprint == hashlib.sha256(
        certificate.encode("utf-8")
    ).hexdigest()
    assert (paths.config_dir / "agent.crt").read_text(encoding="utf-8") == certificate
    assert (paths.config_dir / "dashboard_ca.pem").read_text(encoding="utf-8") == dashboard_ca
    assert after_success.status_code == 410
    assert after_success.json()["error_class"] == "bootstrap_closed"


def test_certificate_install_requires_existing_local_private_key(tmp_path: Path) -> None:
    client, _, _, raw_token = _bootstrap_client(tmp_path)

    response = client.post(
        "/bootstrap/v1/certificate",
        headers=_auth(raw_token),
        json={"certificate": "cert"},
    )

    assert response.status_code == 409
    assert response.json()["error_class"] == "csr_not_ready"


def test_bootstrap_app_does_not_expose_runtime_v1_api(tmp_path: Path) -> None:
    client, _, _, raw_token = _bootstrap_client(tmp_path)

    assert client.get("/v1/info", headers=_auth(raw_token)).status_code == 404
    assert client.post("/v1/scripts/upload", headers=_auth(raw_token), content=b"x").status_code == 404
