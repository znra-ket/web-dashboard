from pathlib import Path
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import webxray_agent.config as config
from webxray_agent.bootstrap import bootstrap_token_hash, create_bootstrap_app
from webxray_agent.config import (
    AgentPaths,
    AgentState,
    AgentStateStore,
    SECRET_FILE_MODE,
    RESTRICTIVE_DIR_MODE,
    atomic_write_text,
)
from webxray_agent.constants import AGENT_STATES_V1


def test_agent_states_match_agent_constants() -> None:
    assert tuple(state.value for state in AgentState) == AGENT_STATES_V1


def test_agent_paths_are_derived_from_install_root(tmp_path: Path) -> None:
    paths = AgentPaths.from_install_root(tmp_path / "agent")

    assert paths.install_root == tmp_path / "agent"
    assert paths.config_dir == paths.install_root / "config"
    assert paths.pairing_state_dir == paths.install_root / "state" / "pairing"
    assert paths.script_storage_dir == paths.install_root / "scripts"
    assert paths.workdir_root == paths.install_root / "work"
    assert paths.logs_dir == paths.install_root / "logs"


def test_secure_directories_and_secret_writes_request_restrictive_modes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    chmod_calls: list[tuple[Path, int]] = []
    real_chmod = config.os.chmod

    def capture_chmod(path: str | Path, mode: int) -> None:
        chmod_calls.append((Path(path), mode))
        real_chmod(path, mode)

    monkeypatch.setattr(config.os, "chmod", capture_chmod)

    paths = AgentPaths.from_install_root(tmp_path / "agent")
    paths.ensure_directories()
    secret_path = paths.pairing_state_dir / "private.key"
    atomic_write_text(secret_path, "secret-key-material", SECRET_FILE_MODE)

    assert secret_path.read_text(encoding="utf-8") == "secret-key-material"
    assert (secret_path, SECRET_FILE_MODE) in chmod_calls
    for directory in (
        paths.install_root,
        paths.config_dir,
        paths.pairing_state_dir,
        paths.script_storage_dir,
        paths.workdir_root,
        paths.logs_dir,
    ):
        assert (directory, RESTRICTIVE_DIR_MODE) in chmod_calls
    assert not list(paths.pairing_state_dir.glob(".private.key.*"))


def test_agent_state_transitions_are_persisted_without_raw_bootstrap_token(
    tmp_path: Path,
) -> None:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    store = AgentStateStore(paths)
    raw_token = "raw-bootstrap-token-never-written"

    assert store.load().state == AgentState.UNPAIRED

    store.mark_bootstrap_pending(
        token_hash="sha256-token-hash",
        expires_at="2026-07-04T12:15:00Z",
        absolute_expires_at="2026-07-04T12:30:00Z",
    )
    pending = AgentStateStore(paths).load()
    assert pending.state == AgentState.BOOTSTRAP_PENDING
    assert pending.bootstrap_token_hash == "sha256-token-hash"

    state_file = store.state_path.read_text(encoding="utf-8")
    assert "sha256-token-hash" in state_file
    assert raw_token not in state_file
    assert "raw-bootstrap-token" not in state_file

    store.mark_paired(
        dashboard_ca_fingerprint="dashboard-ca-fp",
        agent_cert_fingerprint="agent-cert-fp",
    )
    paired = AgentStateStore(paths).load()
    assert paired.state == AgentState.PAIRED
    assert paired.bootstrap_token_hash is None
    assert "sha256-token-hash" not in store.state_path.read_text(encoding="utf-8")

    store.mark_unpaired()
    unpaired = AgentStateStore(paths).load()
    assert unpaired.state == AgentState.UNPAIRED
    assert unpaired.dashboard_ca_fingerprint is None
    assert unpaired.agent_cert_fingerprint is None


def test_bootstrap_app_can_be_created_with_state_store(tmp_path: Path) -> None:
    store = AgentStateStore(AgentPaths.from_install_root(tmp_path / "agent"))
    raw_token = "raw-bootstrap-token-for-status"
    expires_at = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
    absolute_expires_at = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    store.mark_bootstrap_pending(
        token_hash=bootstrap_token_hash(raw_token),
        expires_at=expires_at,
        absolute_expires_at=absolute_expires_at,
    )

    response = TestClient(create_bootstrap_app(store)).get(
        "/bootstrap/v1/status",
        headers={"Authorization": f"Bootstrap {raw_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "agent_state": "bootstrap_pending",
        "bootstrap_state": "pending",
    }
