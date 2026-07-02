from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from webxray_agent.config import Settings


PAIRING_STATE_FILES = (
    "dashboard_ca.pem",
    "pinned_dashboard_cert.pem",
    "agent_cert.pem",
    "agent_private_key.pem",
    "bootstrap_token_hash",
    "bootstrap_token_expires_at",
    "bootstrap_status",
    "pairing_status",
)
AGENT_STATE_FILE = "agent_state"
UNPAIRED_STATE = "unpaired"


@dataclass(frozen=True)
class UnpairResult:
    agent_state: str
    removed_paths: list[str]


@dataclass(frozen=True)
class UninstallResult:
    agent_state: str
    dry_run: bool
    planned_paths: list[str]
    removed_paths: list[str]


def is_unpaired(settings: Settings) -> bool:
    state_path = _agent_state_path(settings)
    if not state_path.exists():
        return False
    return state_path.read_text(encoding="utf-8").strip() == UNPAIRED_STATE


def unpair_agent(settings: Settings) -> UnpairResult:
    settings.pairing_state_dir.mkdir(parents=True, exist_ok=True)
    removed_paths: list[str] = []

    for path in _pairing_state_paths(settings):
        if path.exists():
            path.unlink()
            removed_paths.append(str(path))

    _agent_state_path(settings).write_text(UNPAIRED_STATE, encoding="utf-8")
    return UnpairResult(agent_state=UNPAIRED_STATE, removed_paths=removed_paths)


def uninstall_agent(settings: Settings) -> UninstallResult:
    unpair_result = unpair_agent(settings)
    planned_paths = _owned_paths(settings)
    removed_paths: list[str] = []

    if not settings.uninstall_dry_run:
        for path in planned_paths:
            if not _is_owned_path(path, settings.install_root):
                continue
            if path.is_dir():
                shutil.rmtree(path)
                removed_paths.append(str(path))
            elif path.exists():
                path.unlink()
                removed_paths.append(str(path))

    return UninstallResult(
        agent_state=unpair_result.agent_state,
        dry_run=settings.uninstall_dry_run,
        planned_paths=[str(path) for path in planned_paths],
        removed_paths=removed_paths,
    )


def _pairing_state_paths(settings: Settings) -> list[Path]:
    return [settings.pairing_state_dir / file_name for file_name in PAIRING_STATE_FILES]


def _agent_state_path(settings: Settings) -> Path:
    return settings.pairing_state_dir / AGENT_STATE_FILE


def _owned_paths(settings: Settings) -> list[Path]:
    return [
        settings.script_storage_dir,
        settings.workdir_root,
        settings.pairing_state_dir,
    ]


def _is_owned_path(path: Path, install_root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = install_root.resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents
