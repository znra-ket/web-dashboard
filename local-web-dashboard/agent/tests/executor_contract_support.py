from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from backend.app.architecture.constants import AGENT_LIMITS_V1
from webxray_agent.config import AgentPaths
from webxray_agent.storage import ScriptStorage


@dataclass(frozen=True)
class ExecutorHarness:
    module: Any
    executor: Any
    storage: ScriptStorage
    workdir_root: Path


def load_executor_module() -> Any:
    try:
        return import_module("webxray_agent.executor")
    except ModuleNotFoundError as exc:
        pytest.fail(
            "RED CONTRACT: webxray_agent.executor is not implemented yet. "
            "Prompt 10 must provide the executor module.",
            pytrace=False,
        )
        raise exc


def make_request(module: Any, **overrides: Any) -> Any:
    request_type = getattr(module, "ExecuteRequest", None)
    assert request_type is not None, "Prompt 10 must expose ExecuteRequest"
    payload = {
        "script_hash": "0" * 64,
        "request_id": "request-1",
        "args": [],
        "env": {},
        "timeout_seconds": None,
    }
    payload.update(overrides)
    return request_type(**payload)


def make_harness(tmp_path: Path) -> ExecutorHarness:
    module = load_executor_module()
    executor_type = getattr(module, "ScriptExecutor", None)
    assert executor_type is not None, "Prompt 10 must expose ScriptExecutor"

    paths = AgentPaths.from_install_root(tmp_path / "agent")
    storage = ScriptStorage(paths)
    workdir_root = paths.workdir_root
    executor = executor_type(
        storage=storage,
        workdir_root=workdir_root,
        limits=AGENT_LIMITS_V1,
    )
    return ExecutorHarness(
        module=module,
        executor=executor,
        storage=storage,
        workdir_root=workdir_root,
    )
