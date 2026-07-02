from __future__ import annotations

import asyncio
import os
import shlex
import shutil
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
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
            timed_out = False
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()

        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecutionResult(
            exit_code=None if timed_out else process.returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_ms=duration_ms,
            timed_out=timed_out,
        )
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        shutil.rmtree(workdir, ignore_errors=True)


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
