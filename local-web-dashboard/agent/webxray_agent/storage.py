from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from webxray_agent.config import PUBLIC_FILE_MODE, AgentPaths, ensure_directory
from webxray_agent.constants import (
    MAX_AGENT_SCRIPT_STORAGE_BYTES,
    MAX_SCRIPT_UPLOAD_BYTES,
)


SCRIPT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ScriptStorageError(RuntimeError):
    pass


class InvalidScriptHash(ScriptStorageError, ValueError):
    pass


class ScriptUploadTooLarge(ScriptStorageError):
    pass


class ScriptStorageQuotaExceeded(ScriptStorageError):
    pass


class ScriptStorage:
    def __init__(
        self,
        paths: AgentPaths,
        *,
        upload_limit_bytes: int = MAX_SCRIPT_UPLOAD_BYTES,
        storage_quota_bytes: int = MAX_AGENT_SCRIPT_STORAGE_BYTES,
    ) -> None:
        self.paths = paths
        self.root = paths.script_storage_dir
        self.upload_limit_bytes = upload_limit_bytes
        self.storage_quota_bytes = storage_quota_bytes

    def store_script(self, content: bytes, client_hash: str | None = None) -> str:
        if len(content) > self.upload_limit_bytes:
            raise ScriptUploadTooLarge("script content exceeds upload limit")

        actual_hash = hashlib.sha256(content).hexdigest()
        target_path = self._path_for_hash(actual_hash)
        ensure_directory(self.root)

        if self._regular_file_exists(target_path):
            return actual_hash

        current_usage = self._storage_usage_bytes()
        if current_usage + len(content) > self.storage_quota_bytes:
            raise ScriptStorageQuotaExceeded("script storage quota exceeded")

        self._atomic_write_new_file(target_path, content)
        return actual_hash

    def has_script(self, script_hash: str) -> bool:
        return self._regular_file_exists(self._path_for_hash(script_hash))

    def delete_script(self, script_hash: str) -> None:
        path = self._path_for_hash(script_hash)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except IsADirectoryError as exc:
            raise InvalidScriptHash("script hash path is not a regular file") from exc

    def _path_for_hash(self, script_hash: str) -> Path:
        if not SCRIPT_HASH_PATTERN.fullmatch(script_hash):
            raise InvalidScriptHash("script hash must be a 64-character lowercase hex digest")
        return self.root / script_hash

    def _regular_file_exists(self, path: Path) -> bool:
        try:
            return path.is_file() and not path.is_symlink()
        except OSError:
            return False

    def _storage_usage_bytes(self) -> int:
        ensure_directory(self.root)
        total = 0
        with os.scandir(self.root) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                total += entry.stat(follow_symlinks=False).st_size
        return total

    def _atomic_write_new_file(self, target_path: Path, content: bytes) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{target_path.name}.", dir=self.root)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as temp_file:
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.chmod(temp_path, PUBLIC_FILE_MODE)
            os.replace(temp_path, target_path)
            os.chmod(target_path, PUBLIC_FILE_MODE)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
