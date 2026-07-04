import asyncio
import os
from pathlib import Path

import pytest

from agent.tests.executor_contract_support import make_harness, make_request


def test_execute_runs_only_by_content_hash_not_script_name(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    script_hash = harness.storage.store_script(b"#!/bin/sh\necho by-hash\n")
    request = make_request(
        harness.module,
        script_hash=script_hash,
        script_name="dashboard-name-must-be-ignored",
        request_id="hash-only",
    )

    result = asyncio.run(harness.executor.execute(request))

    assert result.status == "success"
    assert result.stdout == b"by-hash\n"
    assert getattr(result, "script_name_used", None) is None


def test_missing_hash_raises_404_service_error(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    request = make_request(
        harness.module,
        script_hash="a" * 64,
        request_id="missing-hash",
    )

    with pytest.raises(harness.module.ScriptNotFound) as exc_info:
        asyncio.run(harness.executor.execute(request))

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_class == "script_not_found"


def test_execute_uses_default_timeout_60_seconds(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    script_hash = harness.storage.store_script(b"#!/bin/sh\necho timeout-default\n")
    request = make_request(harness.module, script_hash=script_hash, timeout_seconds=None)

    result = asyncio.run(harness.executor.execute(request))

    assert result.timeout_seconds == 60


def test_timeout_uses_sigterm_then_five_second_grace_then_sigkill_process_group(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    script = (
        b"#!/bin/sh\n"
        b"trap '' TERM\n"
        b"echo started\n"
        b"sleep 30\n"
    )
    script_hash = harness.storage.store_script(script)
    request = make_request(
        harness.module,
        script_hash=script_hash,
        request_id="timeout-kill",
        timeout_seconds=1,
    )

    result = asyncio.run(harness.executor.execute(request))

    assert result.status == "failed"
    assert result.error_class == "timeout"
    assert result.terminated_with == "SIGTERM"
    assert result.grace_seconds == 5
    assert result.killed_with == "SIGKILL"
    assert result.killed_process_group is True


def test_fd_based_execution_survives_delete_while_process_is_running(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    script = b"#!/bin/sh\nsleep 0.2\necho still-running\n"
    script_hash = harness.storage.store_script(script)
    request = make_request(
        harness.module,
        script_hash=script_hash,
        request_id="delete-race",
    )

    async def run_and_delete():
        task = asyncio.create_task(harness.executor.execute(request))
        await asyncio.sleep(0.05)
        harness.storage.delete_script(script_hash)
        return await task

    result = asyncio.run(run_and_delete())

    assert result.status == "success"
    assert result.stdout == b"still-running\n"
    assert result.used_fd_execution is True
    assert os.name != "nt" or result.used_equivalent_windows_safe_handle is True
