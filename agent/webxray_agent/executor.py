from __future__ import annotations

import asyncio
import os
import signal
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class ScriptExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    error_class: str | None = None
    stderr_truncated: bool = False


ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR")


def sweep_workdirs(workdir_root: Path) -> None:
    workdir_root.mkdir(parents=True, exist_ok=True)
    for child in workdir_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)


async def execute_script(
    script_path: Path,
    workdir_root: Path,
    args: list[str],
    request_env: dict[str, str],
    timeout_seconds: int,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    shutdown_grace_seconds: int,
) -> ExecutionResult:
    if not script_path.exists():
        raise FileNotFoundError(script_path)

    command = _command_from_shebang(script_path) + [str(script_path), *args]
    workdir_root.mkdir(parents=True, exist_ok=True)
    workdir = workdir_root / str(uuid4())
    workdir.mkdir(parents=False)
    env = _execution_env(request_env, workdir)
    start = time.monotonic()
    process = None

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=workdir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_subprocess_group_kwargs(),
        )
        communicate_task = asyncio.create_task(process.communicate())
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                asyncio.shield(communicate_task),
                timeout=timeout_seconds,
            )
            timed_out = False
        except asyncio.TimeoutError:
            timed_out = True
            await _terminate_process_group(process, shutdown_grace_seconds)
            stdout_bytes, stderr_bytes = await communicate_task

        duration_ms = int((time.monotonic() - start) * 1000)
        stderr, stderr_truncated = _decode_stderr(stderr_bytes, max_stderr_bytes)
        if len(stdout_bytes) > max_stdout_bytes:
            return ExecutionResult(
                exit_code=None,
                stdout="",
                stderr=stderr,
                duration_ms=duration_ms,
                timed_out=timed_out,
                error_class="stdout_limit_exceeded",
                stderr_truncated=stderr_truncated,
            )

        return ExecutionResult(
            exit_code=None if timed_out else process.returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            stderr_truncated=stderr_truncated,
        )
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        shutil.rmtree(workdir, ignore_errors=True)


def _subprocess_group_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def _terminate_process_group(
    process: asyncio.subprocess.Process,
    shutdown_grace_seconds: int,
) -> None:
    if process.returncode is not None:
        return

    if os.name == "nt":
        process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    try:
        await asyncio.wait_for(process.wait(), timeout=shutdown_grace_seconds)
        return
    except asyncio.TimeoutError:
        pass

    if process.returncode is not None:
        return

    if os.name == "nt":
        process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    await process.wait()


def _decode_stderr(stderr_bytes: bytes, max_stderr_bytes: int) -> tuple[str, bool]:
    if len(stderr_bytes) <= max_stderr_bytes:
        return (stderr_bytes.decode("utf-8", errors="replace"), False)
    return (stderr_bytes[:max_stderr_bytes].decode("utf-8", errors="replace"), True)


def _command_from_shebang(script_path: Path) -> list[str]:
    with script_path.open("rb") as script_file:
        first_line = script_file.readline(512).decode("utf-8", errors="replace").strip()

    if not first_line.startswith("#!"):
        raise ScriptExecutionError("Script must start with a shebang")

    shebang_parts = shlex.split(first_line[2:].strip())
    if not shebang_parts:
        raise ScriptExecutionError("Script shebang is empty")

    command = shebang_parts[0]
    command_args = shebang_parts[1:]

    if Path(command).name == "env":
        if not command_args:
            raise ScriptExecutionError("env shebang must name an interpreter")
        interpreter = _resolve_interpreter(command_args[0])
        return [interpreter, *command_args[1:]]

    return [_resolve_interpreter(command), *command_args]


def _resolve_interpreter(command: str) -> str:
    command_name = Path(command).name.lower()
    if command_name in {"python", "python3", "python.exe", "python3.exe"}:
        return sys.executable

    if Path(command).is_absolute() and Path(command).exists():
        return command

    resolved = shutil.which(command)
    if resolved is None:
        resolved = shutil.which(Path(command).name)
    if resolved is None:
        raise ScriptExecutionError(f"Interpreter not found: {command}")
    return resolved


def _execution_env(request_env: dict[str, str], workdir: Path) -> dict[str, str]:
    env = {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}
    env.update(request_env)
    env.setdefault("TMPDIR", str(workdir))
    return env
