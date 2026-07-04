import asyncio
from pathlib import Path

import pytest

from backend.app.architecture.constants import AGENT_LIMITS_V1
from agent.tests.executor_contract_support import make_harness, make_request


def _assert_validation_error(module, func) -> None:
    with pytest.raises(module.ExecuteValidationError) as exc_info:
        func()
    assert exc_info.value.status_code == 422


def test_args_limits_are_enforced(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)

    _assert_validation_error(
        harness.module,
        lambda: make_request(harness.module, args=["x"] * (AGENT_LIMITS_V1.max_args_count + 1)),
    )
    _assert_validation_error(
        harness.module,
        lambda: make_request(harness.module, args=["x" * (AGENT_LIMITS_V1.max_single_arg_bytes + 1)]),
    )
    _assert_validation_error(
        harness.module,
        lambda: make_request(
            harness.module,
            args=["x" * 1024] * ((AGENT_LIMITS_V1.max_args_total_bytes // 1024) + 1),
        ),
    )


def test_env_limits_are_enforced(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)

    _assert_validation_error(
        harness.module,
        lambda: make_request(
            harness.module,
            env={f"K{i}": "v" for i in range(AGENT_LIMITS_V1.max_env_count + 1)},
        ),
    )
    _assert_validation_error(
        harness.module,
        lambda: make_request(
            harness.module,
            env={"K" * (AGENT_LIMITS_V1.max_env_key_bytes + 1): "v"},
        ),
    )
    _assert_validation_error(
        harness.module,
        lambda: make_request(
            harness.module,
            env={"K": "v" * (AGENT_LIMITS_V1.max_single_env_value_bytes + 1)},
        ),
    )
    _assert_validation_error(
        harness.module,
        lambda: make_request(
            harness.module,
            env={f"K{i}": "v" * 1024 for i in range((AGENT_LIMITS_V1.max_env_total_bytes // 1024) + 1)},
        ),
    )


def test_timeout_max_600_seconds_is_enforced(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)

    _assert_validation_error(
        harness.module,
        lambda: make_request(
            harness.module,
            timeout_seconds=AGENT_LIMITS_V1.max_timeout_seconds + 1,
        ),
    )


def test_global_concurrency_limit_2_returns_429_not_silent_queue(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    hashes = [
        harness.storage.store_script(b"#!/bin/sh\nsleep 1\n"),
        harness.storage.store_script(b"#!/bin/sh\nsleep 1\necho second\n"),
        harness.storage.store_script(b"#!/bin/sh\nsleep 1\necho third\n"),
    ]

    async def run_three():
        first = asyncio.create_task(harness.executor.execute(make_request(harness.module, script_hash=hashes[0], request_id="g1")))
        second = asyncio.create_task(harness.executor.execute(make_request(harness.module, script_hash=hashes[1], request_id="g2")))
        await asyncio.sleep(0.05)
        with pytest.raises(harness.module.ConcurrencyLimitExceeded) as exc_info:
            await harness.executor.execute(make_request(harness.module, script_hash=hashes[2], request_id="g3"))
        assert exc_info.value.status_code == 429
        assert exc_info.value.queued is False
        await asyncio.gather(first, second)

    asyncio.run(run_three())


def test_per_hash_concurrency_limit_1_returns_429_not_silent_queue(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    script_hash = harness.storage.store_script(b"#!/bin/sh\nsleep 1\n")

    async def run_two_same_hash():
        first = asyncio.create_task(
            harness.executor.execute(make_request(harness.module, script_hash=script_hash, request_id="h1"))
        )
        await asyncio.sleep(0.05)
        with pytest.raises(harness.module.ConcurrencyLimitExceeded) as exc_info:
            await harness.executor.execute(make_request(harness.module, script_hash=script_hash, request_id="h2"))
        assert exc_info.value.status_code == 429
        assert exc_info.value.queued is False
        await first

    asyncio.run(run_two_same_hash())


def test_stdout_over_256_kib_fails_with_stdout_limit_exceeded(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    script_hash = harness.storage.store_script(
        b"#!/bin/sh\npython - <<'PY'\nprint('x' * (256 * 1024 + 1))\nPY\n"
    )

    result = asyncio.run(
        harness.executor.execute(make_request(harness.module, script_hash=script_hash))
    )

    assert result.status == "failed"
    assert result.error_class == "stdout_limit_exceeded"
    assert len(result.stdout) <= AGENT_LIMITS_V1.max_stdout_bytes


def test_stderr_over_256_kib_is_truncated_with_flag(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    script_hash = harness.storage.store_script(
        b"#!/bin/sh\npython - <<'PY'\nimport sys\nsys.stderr.write('e' * (256 * 1024 + 1))\nPY\n"
    )

    result = asyncio.run(
        harness.executor.execute(make_request(harness.module, script_hash=script_hash))
    )

    assert result.stderr_truncated is True
    assert len(result.stderr) == AGENT_LIMITS_V1.max_stderr_bytes


def test_executor_uses_concurrent_bounded_readers_not_unbounded_communicate(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)

    assert harness.executor.uses_concurrent_bounded_readers is True
    assert harness.executor.uses_unbounded_communicate is False
