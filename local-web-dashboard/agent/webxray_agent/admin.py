from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from webxray_agent.config import AgentPaths, AgentState, AgentStateStore


class UnsafeCleanupPath(RuntimeError):
    status_code = 500
    error_class = "unsafe_cleanup_path"


@dataclass(frozen=True, slots=True)
class CleanupPlanItem:
    path: str
    exists: bool
    kind: str
    action: str

    @classmethod
    def for_path(cls, path: Path, *, action: str) -> CleanupPlanItem:
        try:
            stat_result = path.lstat()
        except FileNotFoundError:
            return cls(path=str(path), exists=False, kind="missing", action=action)
        if path.is_symlink():
            kind = "symlink"
        elif path.is_dir():
            kind = "directory"
        elif path.is_file():
            kind = "file"
        else:
            kind = "other"
        return cls(path=str(path), exists=True, kind=kind, action=action)


@dataclass(frozen=True, slots=True)
class AdminOperationResult:
    status: str
    agent_state: AgentState
    dry_run: bool
    cleanup_plan: tuple[CleanupPlanItem, ...]
    removed_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "status": self.status,
            "agent_state": self.agent_state.value,
            "dry_run": self.dry_run,
            "cleanup_plan": [
                {
                    "path": item.path,
                    "exists": item.exists,
                    "kind": item.kind,
                    "action": item.action,
                }
                for item in self.cleanup_plan
            ],
            "removed_paths": list(self.removed_paths),
            "missing_paths": list(self.missing_paths),
        }


class AdminLifecycleService:
    _TRUST_FILENAMES = (
        "dashboard_ca.pem",
        "dashboard_trust_anchor.pem",
        "dashboard_pinned_cert.pem",
        "pinned_dashboard_cert.pem",
        "agent.crt",
        "agent.cert",
        "agent.pem",
        "agent.key",
        "agent_private.key",
        "agent_private_key.pem",
    )

    def __init__(
        self,
        paths: AgentPaths,
        *,
        state_store: AgentStateStore | None = None,
    ) -> None:
        self.paths = paths
        self.state_store = state_store or AgentStateStore(paths)

    def unpair(self, *, dry_run: bool = False) -> AdminOperationResult:
        targets = self._unpair_targets()
        self._assert_all_owned(targets)
        plan = tuple(CleanupPlanItem.for_path(path, action="remove") for path in targets)
        removed: list[str] = []
        missing: list[str] = []

        if not dry_run:
            removed, missing = self._remove_targets(targets)
            self.state_store.mark_unpaired()

        return AdminOperationResult(
            status="unpaired",
            agent_state=AgentState.UNPAIRED,
            dry_run=dry_run,
            cleanup_plan=plan,
            removed_paths=tuple(removed),
            missing_paths=tuple(missing),
        )

    def uninstall(self, *, dry_run: bool = False) -> AdminOperationResult:
        unpair_targets = self._unpair_targets()
        uninstall_targets = self._uninstall_plan_targets()
        self._assert_all_owned((*unpair_targets, *uninstall_targets))
        plan = tuple(
            CleanupPlanItem.for_path(path, action="remove")
            for path in (*unpair_targets, *uninstall_targets)
        )
        removed: list[str] = []
        missing: list[str] = []

        if not dry_run:
            removed, missing = self._remove_targets(unpair_targets)
            if self.paths.install_root.exists():
                shutil.rmtree(self.paths.install_root)
                removed.append(str(self.paths.install_root))
            else:
                missing.append(str(self.paths.install_root))

        return AdminOperationResult(
            status="uninstalled",
            agent_state=AgentState.UNPAIRED,
            dry_run=dry_run,
            cleanup_plan=plan,
            removed_paths=tuple(dict.fromkeys(removed)),
            missing_paths=tuple(dict.fromkeys(missing)),
        )

    def _unpair_targets(self) -> tuple[Path, ...]:
        targets: list[Path] = [
            self.paths.config_dir / filename
            for filename in self._TRUST_FILENAMES
        ]
        if self.paths.pairing_state_dir.exists():
            targets.extend(self.paths.pairing_state_dir.iterdir())
        return tuple(dict.fromkeys(targets))

    def _uninstall_plan_targets(self) -> tuple[Path, ...]:
        return (
            self.paths.config_dir,
            self.paths.pairing_state_dir,
            self.paths.script_storage_dir,
            self.paths.workdir_root,
            self.paths.logs_dir,
            self.paths.install_root,
        )

    def _assert_all_owned(self, targets: Iterable[Path]) -> None:
        root = self.paths.install_root.resolve(strict=False)
        for target in targets:
            resolved = target.resolve(strict=False)
            if resolved != root and root not in resolved.parents:
                raise UnsafeCleanupPath(
                    f"refusing cleanup path outside web-xray install root: {target}"
                )

    def _remove_targets(self, targets: Iterable[Path]) -> tuple[list[str], list[str]]:
        removed: list[str] = []
        missing: list[str] = []
        for target in targets:
            try:
                target.lstat()
            except FileNotFoundError:
                missing.append(str(target))
                continue
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed.append(str(target))
        return removed, missing
