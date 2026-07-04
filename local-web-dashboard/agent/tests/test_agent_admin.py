from pathlib import Path

from fastapi.testclient import TestClient

from webxray_agent.bootstrap import bootstrap_app
from webxray_agent.config import AgentPaths, AgentState, AgentStateStore, atomic_write_text
from webxray_agent.runtime import RuntimeMTLSContext, create_runtime_app
from webxray_agent.storage import ScriptStorage


def _paired_runtime_client(
    paths: AgentPaths,
) -> tuple[TestClient, AgentStateStore, ScriptStorage]:
    state_store = AgentStateStore(paths)
    state_store.mark_paired(
        dashboard_ca_fingerprint="dashboard-ca-fp",
        agent_cert_fingerprint="agent-cert-fp",
    )
    storage = ScriptStorage(paths)
    app = create_runtime_app(
        RuntimeMTLSContext(
            ca_cert_path=str(paths.config_dir / "dashboard_ca.pem"),
            server_cert_path=str(paths.config_dir / "agent.crt"),
            server_key_path=str(paths.config_dir / "agent.key"),
        ),
        storage=storage,
        state_store=state_store,
    )
    return TestClient(app), state_store, storage


def _write_pairing_material(paths: AgentPaths) -> None:
    atomic_write_text(paths.config_dir / "dashboard_ca.pem", "dashboard-ca")
    atomic_write_text(paths.config_dir / "dashboard_pinned_cert.pem", "pinned-dashboard")
    atomic_write_text(paths.config_dir / "agent.crt", "agent-cert")
    atomic_write_text(paths.config_dir / "agent.key", "agent-private-key")
    atomic_write_text(paths.pairing_state_dir / "bootstrap_token.json", "token-hash-only")


def test_unpair_clears_pairing_state_and_runtime_refuses_further_commands(
    tmp_path: Path,
) -> None:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    client, state_store, storage = _paired_runtime_client(paths)
    _write_pairing_material(paths)
    script_hash = storage.store_script(b"#!/bin/sh\necho still-installed\n")

    response = client.post("/v1/admin/unpair")

    assert response.status_code == 200
    assert response.json()["agent_state"] == "unpaired"
    assert state_store.load().state == AgentState.UNPAIRED
    assert not (paths.config_dir / "dashboard_ca.pem").exists()
    assert not (paths.config_dir / "dashboard_pinned_cert.pem").exists()
    assert not (paths.config_dir / "agent.crt").exists()
    assert not (paths.config_dir / "agent.key").exists()
    assert not (paths.pairing_state_dir / "bootstrap_token.json").exists()
    assert storage.has_script(script_hash)

    after_unpair = client.get("/v1/info")

    assert after_unpair.status_code == 410
    assert after_unpair.json()["error_class"] == "agent_unpaired"


def test_unpair_is_idempotent_where_runtime_handler_is_still_reachable(
    tmp_path: Path,
) -> None:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    client, state_store, _ = _paired_runtime_client(paths)

    first = client.post("/v1/admin/unpair")
    second = client.post("/v1/admin/unpair")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["agent_state"] == "unpaired"
    assert state_store.load().state == AgentState.UNPAIRED


def test_uninstall_dry_run_reports_all_owned_paths_without_deleting(
    tmp_path: Path,
) -> None:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    client, _, storage = _paired_runtime_client(paths)
    _write_pairing_material(paths)
    storage.store_script(b"#!/bin/sh\necho cleanup-plan\n")
    atomic_write_text(paths.workdir_root / "run" / "temp.txt", "temporary")
    atomic_write_text(paths.logs_dir / "agent.log", "log")

    response = client.post("/v1/admin/uninstall", json={"dry_run": True})

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    planned_paths = {item["path"] for item in body["cleanup_plan"]}
    assert str(paths.install_root) in planned_paths
    assert str(paths.config_dir) in planned_paths
    assert str(paths.pairing_state_dir) in planned_paths
    assert str(paths.script_storage_dir) in planned_paths
    assert str(paths.workdir_root) in planned_paths
    assert str(paths.logs_dir) in planned_paths
    assert paths.install_root.exists()


def test_uninstall_executes_cleanup_for_owned_paths(tmp_path: Path) -> None:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    client, _, storage = _paired_runtime_client(paths)
    _write_pairing_material(paths)
    storage.store_script(b"#!/bin/sh\necho remove-me\n")
    atomic_write_text(paths.workdir_root / "run" / "temp.txt", "temporary")
    atomic_write_text(paths.logs_dir / "agent.log", "log")

    response = client.post("/v1/admin/uninstall")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "uninstalled"
    assert body["agent_state"] == "unpaired"
    assert body["dry_run"] is False
    assert not paths.install_root.exists()


def test_uninstall_is_idempotent_after_owned_root_is_removed(tmp_path: Path) -> None:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    client, _, storage = _paired_runtime_client(paths)
    _write_pairing_material(paths)
    storage.store_script(b"#!/bin/sh\necho remove-once\n")

    first = client.post("/v1/admin/uninstall")
    second = client.post("/v1/admin/uninstall")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "uninstalled"
    assert not paths.install_root.exists()


def test_uninstall_refuses_to_delete_paths_outside_install_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside-scripts"
    outside.mkdir()
    outside_file = outside / "keep.txt"
    outside_file.write_text("keep", encoding="utf-8")
    paths = AgentPaths(
        install_root=tmp_path / "agent",
        config_dir=tmp_path / "agent" / "config",
        pairing_state_dir=tmp_path / "agent" / "state" / "pairing",
        script_storage_dir=outside,
        workdir_root=tmp_path / "agent" / "work",
        logs_dir=tmp_path / "agent" / "logs",
    )
    client, _, _ = _paired_runtime_client(paths)

    response = client.post("/v1/admin/uninstall")

    assert response.status_code == 500
    assert response.json()["error_class"] == "unsafe_cleanup_path"
    assert outside_file.read_text(encoding="utf-8") == "keep"
    assert paths.install_root.exists()


def test_admin_routes_are_unavailable_on_bootstrap_app() -> None:
    client = TestClient(bootstrap_app)

    assert client.post("/v1/admin/unpair").status_code == 404
    assert client.post("/v1/admin/uninstall").status_code == 404
