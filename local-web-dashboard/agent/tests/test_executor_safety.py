import asyncio
from pathlib import Path

import pytest

from backend.app.architecture.constants import AGENT_LIMITS_V1
from agent.tests.executor_contract_support import make_harness, make_request


def test_per_run_workdir_created_and_cleaned_after_success_and_failure(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    success_hash = harness.storage.store_script(b"#!/bin/sh\npwd > created_file\n")
    failure_hash = harness.storage.store_script(b"#!/bin/sh\nmkdir child\nexit 7\n")

    success = asyncio.run(
        harness.executor.execute(make_request(harness.module, script_hash=success_hash, request_id="work-success"))
    )
    failure = asyncio.run(
        harness.executor.execute(make_request(harness.module, script_hash=failure_hash, request_id="work-failure"))
    )

    assert success.workdir_cleaned is True
    assert failure.workdir_cleaned is True
    assert not any(harness.workdir_root.iterdir())


def test_workdir_quota_64_mib_is_enforced(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    script_hash = harness.storage.store_script(
        b"#!/bin/sh\npython - <<'PY'\nfrom pathlib import Path\nPath('big').write_bytes(b'x' * (64 * 1024 * 1024 + 1))\nPY\n"
    )

    result = asyncio.run(
        harness.executor.execute(make_request(harness.module, script_hash=script_hash, request_id="work-quota"))
    )

    assert result.status == "failed"
    assert result.error_class == "workdir_quota_exceeded"
    assert result.workdir_quota_bytes == AGENT_LIMITS_V1.workdir_quota_bytes_per_run


def test_resource_limits_are_applied_to_process(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    script_hash = harness.storage.store_script(b"#!/bin/sh\necho limits\n")

    result = asyncio.run(
        harness.executor.execute(make_request(harness.module, script_hash=script_hash, request_id="resource-limits"))
    )

    assert result.resource_limits.max_processes == AGENT_LIMITS_V1.max_processes_per_run
    assert result.resource_limits.max_open_files == AGENT_LIMITS_V1.max_open_files_per_run
    assert result.resource_limits.max_memory_bytes == AGENT_LIMITS_V1.max_memory_bytes_per_run


def test_root_execution_requires_explicit_test_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = make_harness(tmp_path)
    script_hash = harness.storage.store_script(b"#!/bin/sh\necho no-root\n")
    executor = harness.module.ScriptExecutor(
        storage=harness.storage,
        workdir_root=harness.workdir_root,
        limits=AGENT_LIMITS_V1,
        allow_root_for_tests=False,
    )

    monkeypatch.setattr(harness.module.os, "name", "posix")
    monkeypatch.setattr(harness.module.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.delenv("WEBXRAY_AGENT_ALLOW_ROOT_FOR_TESTS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    with pytest.raises(harness.module.ExecuteValidationError):
        asyncio.run(
            executor.execute(
                make_request(harness.module, script_hash=script_hash, request_id="root-refused")
            )
        )
