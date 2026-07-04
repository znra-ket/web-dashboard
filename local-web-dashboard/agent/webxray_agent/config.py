from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from webxray_agent.constants import AGENT_STATES_V1


SECRET_FILE_MODE = 0o600
PUBLIC_FILE_MODE = 0o644
RESTRICTIVE_DIR_MODE = 0o700


class AgentState(StrEnum):
    BOOTSTRAP_PENDING = AGENT_STATES_V1[0]
    PAIRED = AGENT_STATES_V1[1]
    UNPAIRED = AGENT_STATES_V1[2]


@dataclass(frozen=True, slots=True)
class AgentPaths:
    install_root: Path
    config_dir: Path
    pairing_state_dir: Path
    script_storage_dir: Path
    workdir_root: Path
    logs_dir: Path

    @classmethod
    def from_install_root(cls, install_root: Path | str) -> AgentPaths:
        root = Path(install_root)
        return cls(
            install_root=root,
            config_dir=root / "config",
            pairing_state_dir=root / "state" / "pairing",
            script_storage_dir=root / "scripts",
            workdir_root=root / "work",
            logs_dir=root / "logs",
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.install_root,
            self.config_dir,
            self.pairing_state_dir,
            self.script_storage_dir,
            self.workdir_root,
            self.logs_dir,
        ):
            ensure_directory(directory)


def ensure_directory(path: Path, mode: int = RESTRICTIVE_DIR_MODE) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)


def atomic_write_bytes(path: Path, content: bytes, mode: int = SECRET_FILE_MODE) -> None:
    ensure_directory(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
        os.chmod(path, mode)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise


def atomic_write_text(path: Path, content: str, mode: int = SECRET_FILE_MODE) -> None:
    atomic_write_bytes(path, content.encode("utf-8"), mode)


@dataclass(frozen=True, slots=True)
class AgentLocalState:
    state: AgentState
    bootstrap_token_hash: str | None = None
    bootstrap_expires_at: str | None = None
    bootstrap_absolute_expires_at: str | None = None
    dashboard_ca_fingerprint: str | None = None
    agent_cert_fingerprint: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "bootstrap_token_hash": self.bootstrap_token_hash,
            "bootstrap_expires_at": self.bootstrap_expires_at,
            "bootstrap_absolute_expires_at": self.bootstrap_absolute_expires_at,
            "dashboard_ca_fingerprint": self.dashboard_ca_fingerprint,
            "agent_cert_fingerprint": self.agent_cert_fingerprint,
        }

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> AgentLocalState:
        return cls(
            state=AgentState(payload["state"]),
            bootstrap_token_hash=payload.get("bootstrap_token_hash"),
            bootstrap_expires_at=payload.get("bootstrap_expires_at"),
            bootstrap_absolute_expires_at=payload.get("bootstrap_absolute_expires_at"),
            dashboard_ca_fingerprint=payload.get("dashboard_ca_fingerprint"),
            agent_cert_fingerprint=payload.get("agent_cert_fingerprint"),
        )


class AgentStateStore:
    def __init__(self, paths: AgentPaths) -> None:
        self.paths = paths
        self.state_path = paths.pairing_state_dir / "agent_state.json"

    def load(self) -> AgentLocalState:
        if not self.state_path.exists():
            return AgentLocalState(state=AgentState.UNPAIRED)
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        return AgentLocalState.from_json_dict(payload)

    def save(self, state: AgentLocalState) -> None:
        self.paths.ensure_directories()
        atomic_write_text(
            self.state_path,
            json.dumps(state.to_json_dict(), sort_keys=True),
            SECRET_FILE_MODE,
        )

    def mark_bootstrap_pending(
        self,
        *,
        token_hash: str,
        expires_at: str,
        absolute_expires_at: str,
    ) -> AgentLocalState:
        state = AgentLocalState(
            state=AgentState.BOOTSTRAP_PENDING,
            bootstrap_token_hash=token_hash,
            bootstrap_expires_at=expires_at,
            bootstrap_absolute_expires_at=absolute_expires_at,
        )
        self.save(state)
        return state

    def mark_paired(
        self,
        *,
        dashboard_ca_fingerprint: str,
        agent_cert_fingerprint: str,
    ) -> AgentLocalState:
        state = AgentLocalState(
            state=AgentState.PAIRED,
            dashboard_ca_fingerprint=dashboard_ca_fingerprint,
            agent_cert_fingerprint=agent_cert_fingerprint,
        )
        self.save(state)
        return state

    def mark_unpaired(self) -> AgentLocalState:
        state = AgentLocalState(state=AgentState.UNPAIRED)
        self.save(state)
        return state
