import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.architecture.constants import AGENT_FEATURES_V1, AGENT_LIMITS_V1
from webxray_agent.bootstrap import bootstrap_app
from webxray_agent.config import AgentPaths, AgentState
from webxray_agent.constants import MAX_SCRIPT_UPLOAD_BYTES
from webxray_agent.runtime import RuntimeMTLSContext, create_runtime_app
from webxray_agent.storage import ScriptStorage


def _runtime_client(tmp_path: Path) -> tuple[TestClient, ScriptStorage]:
    storage = ScriptStorage(AgentPaths.from_install_root(tmp_path / "agent"))
    context = RuntimeMTLSContext(
        ca_cert_path="ca.pem",
        server_cert_path="server.pem",
        server_key_path="server.key",
    )
    return TestClient(create_runtime_app(context, storage=storage)), storage


def test_upload_happy_path(tmp_path: Path) -> None:
    client, storage = _runtime_client(tmp_path)
    content = b"#!/bin/sh\necho ok\n"

    response = client.post("/v1/scripts/upload", content=content)

    expected_hash = hashlib.sha256(content).hexdigest()
    assert response.status_code == 200
    assert response.json() == {"hash": expected_hash}
    assert storage.has_script(expected_hash)


def test_upload_over_limit_returns_413_before_storage(tmp_path: Path) -> None:
    client, storage = _runtime_client(tmp_path)

    response = client.post("/v1/scripts/upload", content=b"x" * (MAX_SCRIPT_UPLOAD_BYTES + 1))

    assert response.status_code == 413
    assert not storage.root.exists() or list(storage.root.iterdir()) == []


def test_delete_existing_and_missing_are_successful(tmp_path: Path) -> None:
    client, storage = _runtime_client(tmp_path)
    script_hash = storage.store_script(b"delete through api")

    existing = client.delete(f"/v1/scripts/{script_hash}")
    missing = client.delete(f"/v1/scripts/{script_hash}")

    assert existing.status_code == 204
    assert missing.status_code == 204
    assert storage.has_script(script_hash) is False


def test_info_includes_all_limits_and_features(tmp_path: Path) -> None:
    client, _ = _runtime_client(tmp_path)

    response = client.get("/v1/info")

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == 1
    assert body["supported_features"] == list(AGENT_FEATURES_V1)
    assert body["limits"] == dict(AGENT_LIMITS_V1.as_mapping())


def test_unpaired_runtime_rejects_v1_app_creation() -> None:
    context = RuntimeMTLSContext(
        ca_cert_path="ca.pem",
        server_cert_path="server.pem",
        server_key_path="server.key",
        agent_state=AgentState.UNPAIRED,
    )

    with pytest.raises(RuntimeError, match="paired agent state"):
        create_runtime_app(context)


def test_plain_bootstrap_app_does_not_contain_script_routes() -> None:
    script_routes = {
        route.path
        for route in bootstrap_app.routes
        if getattr(route, "path", "").startswith("/v1/scripts")
    }

    assert script_routes == set()
