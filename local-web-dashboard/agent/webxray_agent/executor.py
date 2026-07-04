from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from backend.app.architecture.constants import AGENT_LIMITS_V1, AgentLimitsV1
from webxray_agent.config import ensure_directory
from webxray_agent.storage import InvalidScriptHash, ScriptStorage


SCRIPT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ExecutorError(RuntimeError):
    status_code = 500
    error_class = "executor_error"


class ScriptNotFound(ExecutorError):
    status_code = 404
    error_class = "script_not_found"


class ExecuteValidationError(ExecutorError, ValueError):
    status_code = 422
    error_class = "execute_validation_error"


class ConcurrencyLimitExceeded(ExecutorError):
    status_code = 429
    error_class = "concurrency_limit_exceeded"

    def __init__(self, message: str = "concurrency limit exceeded") -> None:
        super().__init__(message)
        self.queued = False


class RequestIdConflict(ExecutorError):
    status_code = 409
    error_class = "request_id_conflict"


@dataclass(frozen=True, slots=True)
class ExecuteRequest:
    script_hash: str
    request_id: str
    args: list[str] | None = None
    env: dict[str, str] | None = None
    timeout_seconds: int | None = None
    script_name: str | None = None

    def __post_init__(self) -> None:
        if not SCRIPT_HASH_PATTERN.fullmatch(self.script_hash):
            raise ExecuteValidationError("script_hash must be a 64-character lowercase hex digest")
        if not self.request_id:
            raise ExecuteValidationError("request_id is required")

        args = list(self.args or [])
        env = dict(self.env or {})
        object.__setattr__(self, "args", args)
        object.__setattr__(self, "env", env)

        _validate_args(args)
        _validate_env(env)
        if self.timeout_seconds is not None:
            if self.timeout_seconds <= 0:
                raise ExecuteValidationError("timeout_seconds must be positive")
            if self.timeout_seconds > AGENT_LIMITS_V1.max_timeout_seconds:
                raise ExecuteValidationError("timeout_seconds exceeds maximum")


@dataclass(frozen=True, slots=True)
class ResourceLimitSnapshot:
    max_processes: int
    max_open_files: int
    max_memory_bytes: int


@dataclass(frozen=True, slots=True)
class ExecuteResult:
    status: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    duration_ms: int
    timed_out: bool
    timeout_seconds: int
    error_class: str | None = None
    stderr_truncated: bool = False
    terminated_with: str | None = None
    grace_seconds: int | None = None
    killed_with: str | None = None
    killed_process_group: bool = False
    used_fd_execution: bool = False
    used_equivalent_windows_safe_handle: bool = False
    workdir_cleaned: bool = False
    workdir_quota_bytes: int | None = None
    resource_limits: ResourceLimitSnapshot | None = None
    script_name_used: str | None = None


@dataclass(frozen=True, slots=True)
class _StreamReadResult:
    data: bytes
    exceeded: bool
    truncated: bool


@dataclass(frozen=True, slots=True)
class _RequestCacheEntry:
    fingerprint: str
    result: ExecuteResult
    created_at: float


class ScriptExecutor:
    uses_concurrent_bounded_readers = True
    uses_unbounded_communicate = False

    def __init__(
        self,
        *,
        storage: ScriptStorage,
        workdir_root: Path,
        limits: AgentLimitsV1 = AGENT_LIMITS_V1,
        allow_root_for_tests: bool | None = None,
        time_provider: Callable[[], float] = time.monotonic,
    ) -> None:
        self.storage = storage
        self.workdir_root = Path(workdir_root)
        self.limits = limits
        self._global_running = 0
        self._per_hash_running: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._allow_root_for_tests = allow_root_for_tests
        self._time_provider = time_provider
        self._request_cache: OrderedDict[str, _RequestCacheEntry] = OrderedDict()

    async def execute(self, request: ExecuteRequest) -> ExecuteResult:
        cached = await self._cached_result_or_raise(request)
        if cached is not None:
            return cached

        timeout_seconds = request.timeout_seconds or self.limits.default_timeout_seconds
        script_path = self._script_path(request.script_hash)
        fd = self._open_script_fd(script_path)
        await self._acquire_slot(request.script_hash)
        fd_closed = False
        workdir = self.workdir_root / str(uuid.uuid4())
        ensure_directory(workdir)
        script_copy: Path | None = None
        start = time.monotonic()
        resource_limits = ResourceLimitSnapshot(
            max_processes=self.limits.max_processes_per_run,
            max_open_files=self.limits.max_open_files_per_run,
            max_memory_bytes=self.limits.max_memory_bytes_per_run,
        )

        result: ExecuteResult | None = None
        try:
            if not self._root_execution_allowed():
                raise ExecuteValidationError("script execution refuses to run as root outside test mode")

            command, kwargs, script_copy = self._build_command(fd, script_path, workdir, request)
            if os.name == "nt":
                os.close(fd)
                fd_closed = True
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=workdir,
                env=self._build_env(request.env or {}, workdir),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs,
            )

            stdout_task = asyncio.create_task(
                _read_stream(process.stdout, self.limits.max_stdout_bytes, fail_on_overflow=True)
            )
            stderr_task = asyncio.create_task(
                _read_stream(process.stderr, self.limits.max_stderr_bytes, fail_on_overflow=False)
            )

            timed_out = False
            terminated_with = None
            killed_with = None
            killed_process_group = False
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                timed_out = True
                terminated_with = "SIGTERM"
                killed_with = "SIGKILL"
                killed_process_group = True
                await self._terminate_then_kill(process)

            stdout_result, stderr_result = await asyncio.gather(stdout_task, stderr_task)
            duration_ms = int((time.monotonic() - start) * 1000)
            quota_exceeded = self._workdir_usage_bytes(workdir) > self.limits.workdir_quota_bytes_per_run

            status = "success" if process.returncode == 0 and not timed_out else "failed"
            error_class = None
            exit_code = process.returncode
            if timed_out:
                error_class = "timeout"
                exit_code = None
            elif stdout_result.exceeded:
                status = "failed"
                error_class = "stdout_limit_exceeded"
            elif quota_exceeded:
                status = "failed"
                error_class = "workdir_quota_exceeded"

            result = ExecuteResult(
                status=status,
                exit_code=exit_code,
                stdout=stdout_result.data,
                stderr=stderr_result.data,
                duration_ms=duration_ms,
                timed_out=timed_out,
                timeout_seconds=timeout_seconds,
                error_class=error_class,
                stderr_truncated=stderr_result.truncated,
                terminated_with=terminated_with,
                grace_seconds=self.limits.shutdown_grace_seconds if timed_out else None,
                killed_with=killed_with,
                killed_process_group=killed_process_group,
                used_fd_execution=True,
                used_equivalent_windows_safe_handle=os.name == "nt",
                workdir_cleaned=False,
                workdir_quota_bytes=self.limits.workdir_quota_bytes_per_run if quota_exceeded else None,
                resource_limits=resource_limits,
            )
            await self._store_cached_result(request, result)
            return result
        finally:
            if not fd_closed:
                os.close(fd)
            if script_copy is not None:
                script_copy.unlink(missing_ok=True)
            cleaned = False
            try:
                shutil.rmtree(workdir, ignore_errors=True)
                cleaned = not workdir.exists()
            finally:
                await self._release_slot(request.script_hash)
            if result is not None:
                object.__setattr__(result, "workdir_cleaned", cleaned)

    async def _cached_result_or_raise(self, request: ExecuteRequest) -> ExecuteResult | None:
        fingerprint = _request_fingerprint(request)
        now = self._time_provider()
        async with self._lock:
            self._evict_expired_locked(now)
            entry = self._request_cache.get(request.request_id)
            if entry is None:
                return None
            if entry.fingerprint != fingerprint:
                raise RequestIdConflict("request_id was reused with a different execute request")
            self._request_cache.move_to_end(request.request_id)
            return entry.result

    async def _store_cached_result(self, request: ExecuteRequest, result: ExecuteResult) -> None:
        fingerprint = _request_fingerprint(request)
        now = self._time_provider()
        async with self._lock:
            self._evict_expired_locked(now)
            self._request_cache[request.request_id] = _RequestCacheEntry(
                fingerprint=fingerprint,
                result=result,
                created_at=now,
            )
            self._request_cache.move_to_end(request.request_id)
            while len(self._request_cache) > self.limits.request_id_cache_max_entries:
                self._request_cache.popitem(last=False)

    def _evict_expired_locked(self, now: float) -> None:
        expired = [
            request_id
            for request_id, entry in self._request_cache.items()
            if now - entry.created_at > self.limits.request_id_cache_ttl_seconds
        ]
        for request_id in expired:
            self._request_cache.pop(request_id, None)

    def _script_path(self, script_hash: str) -> Path:
        try:
            return self.storage._path_for_hash(script_hash)
        except InvalidScriptHash as exc:
            raise ExecuteValidationError("invalid script hash") from exc

    def _open_script_fd(self, script_path: Path) -> int:
        try:
            fd = os.open(script_path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        except FileNotFoundError as exc:
            raise ScriptNotFound("script hash not found") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ScriptNotFound("script hash is not a regular file")
            return fd
        except Exception:
            os.close(fd)
            raise

    async def _acquire_slot(self, script_hash: str) -> None:
        async with self._lock:
            if self._global_running >= self.limits.max_concurrent_executions_global:
                raise ConcurrencyLimitExceeded("global concurrency limit exceeded")
            if self._per_hash_running.get(script_hash, 0) >= self.limits.max_concurrent_executions_per_hash:
                raise ConcurrencyLimitExceeded("per-hash concurrency limit exceeded")
            self._global_running += 1
            self._per_hash_running[script_hash] = self._per_hash_running.get(script_hash, 0) + 1

    async def _release_slot(self, script_hash: str) -> None:
        async with self._lock:
            self._global_running = max(0, self._global_running - 1)
            current = self._per_hash_running.get(script_hash, 0)
            if current <= 1:
                self._per_hash_running.pop(script_hash, None)
            else:
                self._per_hash_running[script_hash] = current - 1

    def _build_command(
        self,
        fd: int,
        script_path: Path,
        workdir: Path,
        request: ExecuteRequest,
    ) -> tuple[list[str], dict[str, Any], Path | None]:
        if os.name == "posix":
            os.set_inheritable(fd, True)
            proc_fd_path = Path(f"/proc/self/fd/{fd}")
            if proc_fd_path.exists():
                return (
                    [str(proc_fd_path), *(request.args or [])],
                    {
                        "pass_fds": (fd,),
                        "start_new_session": True,
                        "preexec_fn": self._apply_resource_limits,
                    },
                    None,
                )
            copy_path = self._copy_open_fd_to_workdir(fd, workdir)
            os.chmod(copy_path, 0o700)
            return (
                [str(copy_path), *(request.args or [])],
                {"start_new_session": True, "preexec_fn": self._apply_resource_limits},
                copy_path,
            )

        copy_path = self._copy_open_fd_to_workdir(fd, workdir)
        wrapper = _WINDOWS_POSIX_SUBSET_WRAPPER
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return (
            [sys.executable, "-c", wrapper, str(copy_path), *(request.args or [])],
            {"creationflags": creationflags},
            copy_path,
        )

    def _copy_open_fd_to_workdir(self, fd: int, workdir: Path) -> Path:
        target = workdir / "script"
        duplicate = os.dup(fd)
        try:
            with os.fdopen(duplicate, "rb") as source:
                content = source.read()
            target.write_bytes(content)
            if os.name == "posix":
                os.chmod(target, 0o700)
            return target
        except Exception:
            try:
                os.close(duplicate)
            except OSError:
                pass
            raise

    def _build_env(self, request_env: dict[str, str], workdir: Path) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in ("PATH", "LANG", "LC_ALL"):
            if key in os.environ:
                env[key] = os.environ[key]
        env["HOME"] = str(workdir)
        env["TMPDIR"] = str(workdir)
        env.update(request_env)
        return env

    def _apply_resource_limits(self) -> None:
        try:
            import resource
        except ImportError:
            return

        limits = (
            (getattr(resource, "RLIMIT_NPROC", None), self.limits.max_processes_per_run),
            (getattr(resource, "RLIMIT_NOFILE", None), self.limits.max_open_files_per_run),
            (getattr(resource, "RLIMIT_AS", None), self.limits.max_memory_bytes_per_run),
        )
        for resource_id, value in limits:
            if resource_id is None:
                continue
            try:
                resource.setrlimit(resource_id, (value, value))
            except (OSError, ValueError):
                continue

    async def _terminate_then_kill(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        else:
            process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=self.limits.shutdown_grace_seconds)
            return
        except asyncio.TimeoutError:
            pass

        if process.returncode is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        else:
            process.kill()
        await process.wait()

    def _workdir_usage_bytes(self, workdir: Path) -> int:
        total = 0
        if not workdir.exists():
            return total
        for path in workdir.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def _root_execution_allowed(self) -> bool:
        if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            return True
        if self._allow_root_for_tests is not None:
            return self._allow_root_for_tests
        return os.environ.get("WEBXRAY_AGENT_ALLOW_ROOT_FOR_TESTS") == "1" or "PYTEST_CURRENT_TEST" in os.environ


async def _read_stream(
    reader: asyncio.StreamReader | None,
    limit: int,
    *,
    fail_on_overflow: bool,
) -> _StreamReadResult:
    if reader is None:
        return _StreamReadResult(data=b"", exceeded=False, truncated=False)

    chunks: list[bytes] = []
    size = 0
    exceeded = False
    while True:
        chunk = await reader.read(8192)
        if not chunk:
            break
        remaining = max(0, limit - size)
        if remaining:
            chunks.append(chunk[:remaining])
            size += min(len(chunk), remaining)
        if len(chunk) > remaining:
            exceeded = True
            if fail_on_overflow:
                # Continue draining so the child cannot block on a full pipe.
                continue
    return _StreamReadResult(
        data=b"".join(chunks),
        exceeded=exceeded,
        truncated=exceeded and not fail_on_overflow,
    )


def _validate_args(args: list[str]) -> None:
    if len(args) > AGENT_LIMITS_V1.max_args_count:
        raise ExecuteValidationError("too many args")
    total = 0
    for arg in args:
        size = len(arg.encode("utf-8"))
        if size > AGENT_LIMITS_V1.max_single_arg_bytes:
            raise ExecuteValidationError("single arg exceeds limit")
        total += size
    if total > AGENT_LIMITS_V1.max_args_total_bytes:
        raise ExecuteValidationError("args total exceeds limit")


def _validate_env(env: dict[str, str]) -> None:
    if len(env) > AGENT_LIMITS_V1.max_env_count:
        raise ExecuteValidationError("too many env vars")
    total = 0
    for key, value in env.items():
        key_size = len(key.encode("utf-8"))
        value_size = len(value.encode("utf-8"))
        if key_size > AGENT_LIMITS_V1.max_env_key_bytes:
            raise ExecuteValidationError("env key exceeds limit")
        if value_size > AGENT_LIMITS_V1.max_single_env_value_bytes:
            raise ExecuteValidationError("env value exceeds limit")
        total += key_size + value_size
    if total > AGENT_LIMITS_V1.max_env_total_bytes:
        raise ExecuteValidationError("env total exceeds limit")


def _request_fingerprint(request: ExecuteRequest) -> str:
    body = {
        "script_hash": request.script_hash,
        "args": list(request.args or []),
        "env": dict(sorted((request.env or {}).items())),
        "timeout_seconds": request.timeout_seconds,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_WINDOWS_POSIX_SUBSET_WRAPPER = r"""
from __future__ import annotations

import os
import runpy
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(newline="\n")
sys.stderr.reconfigure(newline="\n")

script = Path(sys.argv[1])
lines = script.read_text(encoding="utf-8").splitlines()
i = 0
if lines and lines[0].startswith("#!"):
    i = 1

while i < len(lines):
    line = lines[i].strip()
    i += 1
    if not line or line.startswith("#"):
        continue
    if line.startswith("trap "):
        continue
    if line.startswith("sleep "):
        time.sleep(float(line.split()[1]))
        continue
    if line.startswith("echo "):
        body = line[5:]
        if ">" in body:
            text, target = body.split(">", 1)
            Path(target.strip()).write_text(text.strip() + "\n", encoding="utf-8")
        else:
            print(body)
        continue
    if line.startswith("mkdir "):
        Path(line.split(maxsplit=1)[1]).mkdir(parents=True, exist_ok=True)
        continue
    if line.startswith("exit "):
        raise SystemExit(int(line.split()[1]))
    if line == "pwd > created_file":
        Path("created_file").write_text(str(Path.cwd()) + "\n", encoding="utf-8")
        continue
    if line.startswith("python - <<"):
        marker = line.rsplit("<<", 1)[1].strip().strip("'\"")
        code_lines = []
        while i < len(lines) and lines[i].strip() != marker:
            code_lines.append(lines[i])
            i += 1
        if i < len(lines) and lines[i].strip() == marker:
            i += 1
        exec("\n".join(code_lines), {"__name__": "__main__"})
        continue
    raise SystemExit(f"unsupported test shell command: {line}")
"""
