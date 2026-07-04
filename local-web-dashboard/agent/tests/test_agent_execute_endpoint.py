from pathlib import Path
from dataclasses import replace

from fastapi.testclient import TestClient

from backend.app.architecture.constants import AGENT_LIMITS_V1
from webxray_agent.config import AgentPaths
from webxray_agent.executor import ScriptExecutor
from webxray_agent.runtime import RuntimeMTLSContext, create_runtime_app
from webxray_agent.storage import ScriptStorage


def _runtime_client(
    tmp_path: Path,
    *,
    executor: ScriptExecutor | None = None,
) -> tuple[TestClient, ScriptStorage]:
    storage = ScriptStorage(AgentPaths.from_install_root(tmp_path / "agent"))
    app = create_runtime_app(
        RuntimeMTLSContext(
            ca_cert_path="ca.pem",
            server_cert_path="server.pem",
            server_key_path="server.key",
        ),
        storage=storage,
        executor=executor,
    )
    return TestClient(app), storage


def test_execute_happy_path_returns_sync_result_shape(tmp_path: Path) -> None:
    client, storage = _runtime_client(tmp_path)
    script_hash = storage.store_script(
        b"#!/bin/sh\n"
        b"python - <<'PY'\n"
        b"import sys\n"
        b"print('api-ok')\n"
        b"sys.stderr.write('diagnostic')\n"
        b"PY\n"
    )

    response = client.post(
        "/v1/scripts/execute",
        json={
            "hash": script_hash,
            "request_id": "api-happy",
            "args": [],
            "env": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["exit_code"] == 0
    assert body["stdout"] == "api-ok\n"
    assert body["stderr"] == "diagnostic"
    assert body["timed_out"] is False
    assert body["error_class"] is None
    assert isinstance(body["duration_ms"], int)


def test_execute_missing_hash_returns_structured_404_at_api_boundary(
    tmp_path: Path,
) -> None:
    client, _ = _runtime_client(tmp_path)

    response = client.post(
        "/v1/scripts/execute",
        json={
            "hash": "a" * 64,
            "request_id": "missing-at-api",
            "args": [],
            "env": {},
        },
    )

    assert response.status_code == 404
    assert response.json()["error_class"] == "script_not_found"


def test_execute_replays_same_request_id_and_same_fingerprint_from_cache(
    tmp_path: Path,
) -> None:
    client, storage = _runtime_client(tmp_path)
    count_file = tmp_path / "count.txt"
    script_hash = storage.store_script(
        b"#!/bin/sh\n"
        b"python - <<'PY'\n"
        b"import os\n"
        b"from pathlib import Path\n"
        b"path = Path(os.environ['COUNT_FILE'])\n"
        b"count = int(path.read_text() or '0') if path.exists() else 0\n"
        b"path.write_text(str(count + 1))\n"
        b"print(count + 1)\n"
        b"PY\n"
    )
    payload = {
        "hash": script_hash,
        "request_id": "api-replay",
        "args": [],
        "env": {"COUNT_FILE": str(count_file)},
    }

    first = client.post("/v1/scripts/execute", json=payload)
    second = client.post("/v1/scripts/execute", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["stdout"] == "1\n"
    assert second.json()["stdout"] == "1\n"
    assert count_file.read_text() == "1"


def test_execute_same_request_id_with_different_fingerprint_conflicts(
    tmp_path: Path,
) -> None:
    client, storage = _runtime_client(tmp_path)
    script_hash = storage.store_script(b"#!/bin/sh\necho conflict\n")

    first = client.post(
        "/v1/scripts/execute",
        json={"hash": script_hash, "request_id": "api-conflict", "args": ["a"], "env": {}},
    )
    second = client.post(
        "/v1/scripts/execute",
        json={"hash": script_hash, "request_id": "api-conflict", "args": ["b"], "env": {}},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error_class"] == "request_id_conflict"


def test_execute_request_id_cache_ttl_allows_reuse_after_expiry(tmp_path: Path) -> None:
    now = 1000.0

    def time_provider() -> float:
        return now

    paths = AgentPaths.from_install_root(tmp_path / "agent")
    storage = ScriptStorage(paths)
    executor = ScriptExecutor(
        storage=storage,
        workdir_root=paths.workdir_root,
        limits=replace(AGENT_LIMITS_V1, request_id_cache_ttl_seconds=10),
        time_provider=time_provider,
    )
    client, _ = _runtime_client(tmp_path, executor=executor)
    script_hash = storage.store_script(b"#!/bin/sh\necho ttl\n")

    first = client.post(
        "/v1/scripts/execute",
        json={"hash": script_hash, "request_id": "api-ttl", "args": ["before"], "env": {}},
    )
    now = 1011.0
    after_ttl = client.post(
        "/v1/scripts/execute",
        json={"hash": script_hash, "request_id": "api-ttl", "args": ["after"], "env": {}},
    )

    assert first.status_code == 200
    assert after_ttl.status_code == 200


def test_execute_request_id_cache_evicts_old_entries_at_max_size(tmp_path: Path) -> None:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    storage = ScriptStorage(paths)
    executor = ScriptExecutor(
        storage=storage,
        workdir_root=paths.workdir_root,
        limits=replace(AGENT_LIMITS_V1, request_id_cache_max_entries=2),
    )
    client, _ = _runtime_client(tmp_path, executor=executor)
    script_hash = storage.store_script(b"#!/bin/sh\necho evict\n")

    for request_id in ["r1", "r2", "r3"]:
        response = client.post(
            "/v1/scripts/execute",
            json={"hash": script_hash, "request_id": request_id, "args": [], "env": {}},
        )
        assert response.status_code == 200

    reused_evicted = client.post(
        "/v1/scripts/execute",
        json={"hash": script_hash, "request_id": "r1", "args": ["changed"], "env": {}},
    )

    assert reused_evicted.status_code == 200


def test_execute_body_over_128_kib_returns_413_before_parse(tmp_path: Path) -> None:
    client, storage = _runtime_client(tmp_path)
    script_hash = storage.store_script(b"#!/bin/sh\necho body-limit\n")
    large_arg = "x" * AGENT_LIMITS_V1.max_execute_body_bytes

    response = client.post(
        "/v1/scripts/execute",
        json={
            "hash": script_hash,
            "request_id": "api-body-limit",
            "args": [large_arg],
            "env": {},
        },
    )

    assert response.status_code == 413


def test_execute_timeout_result_shape_matches_contract(tmp_path: Path) -> None:
    client, storage = _runtime_client(tmp_path)
    script_hash = storage.store_script(
        b"#!/bin/sh\n"
        b"trap '' TERM\n"
        b"sleep 30\n"
    )

    response = client.post(
        "/v1/scripts/execute",
        json={
            "hash": script_hash,
            "request_id": "api-timeout",
            "args": [],
            "env": {},
            "timeout_seconds": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["exit_code"] is None
    assert body["timed_out"] is True
    assert body["error_class"] == "timeout"
