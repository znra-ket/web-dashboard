from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from uuid import UUID

from webxray_agent.schemas import ScriptExecuteRequest, ScriptExecuteResponse


class ExecutionLimiter:
    def __init__(self, global_limit: int, per_hash_limit: int) -> None:
        self._global_limit = global_limit
        self._per_hash_limit = per_hash_limit
        self._global_running = 0
        self._per_hash_running: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, script_hash: str) -> bool:
        async with self._lock:
            per_hash_running = self._per_hash_running.get(script_hash, 0)
            if (
                self._global_running >= self._global_limit
                or per_hash_running >= self._per_hash_limit
            ):
                return False

            self._global_running += 1
            self._per_hash_running[script_hash] = per_hash_running + 1
            return True

    async def release(self, script_hash: str) -> None:
        async with self._lock:
            self._global_running = max(0, self._global_running - 1)
            per_hash_running = self._per_hash_running.get(script_hash, 0) - 1
            if per_hash_running <= 0:
                self._per_hash_running.pop(script_hash, None)
            else:
                self._per_hash_running[script_hash] = per_hash_running


@dataclass(frozen=True)
class IdempotencyEntry:
    fingerprint: str
    response: ScriptExecuteResponse
    created_at: float


class RequestIdCache:
    def __init__(self, ttl_seconds: int, max_entries: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[str, IdempotencyEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(
        self,
        request_id: UUID,
        fingerprint: str,
    ) -> tuple[str, ScriptExecuteResponse | None]:
        async with self._lock:
            self._purge_expired()
            cache_key = str(request_id)
            entry = self._entries.get(cache_key)
            if entry is None:
                return ("miss", None)
            if entry.fingerprint != fingerprint:
                return ("conflict", None)

            self._entries.move_to_end(cache_key)
            return ("hit", entry.response)

    async def store(
        self,
        request_id: UUID,
        fingerprint: str,
        response: ScriptExecuteResponse,
    ) -> None:
        async with self._lock:
            self._purge_expired()
            self._entries[str(request_id)] = IdempotencyEntry(
                fingerprint=fingerprint,
                response=response,
                created_at=time.monotonic(),
            )
            self._entries.move_to_end(str(request_id))
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired_keys = [
            cache_key
            for cache_key, entry in self._entries.items()
            if now - entry.created_at >= self._ttl_seconds
        ]
        for cache_key in expired_keys:
            self._entries.pop(cache_key, None)


def execution_fingerprint(payload: ScriptExecuteRequest, timeout_seconds: int) -> str:
    body = {
        "args": payload.args,
        "env": dict(sorted(payload.env.items())),
        "hash": payload.hash,
        "timeout_seconds": timeout_seconds,
    }
    serialized = json.dumps(body, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
