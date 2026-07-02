from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path


HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ScriptTooLargeError(ValueError):
    pass


class InvalidHashError(ValueError):
    pass


def calculate_script_hash(script_bytes: bytes) -> str:
    return hashlib.sha256(script_bytes).hexdigest()


def validate_hash(script_hash: str) -> None:
    if HASH_RE.fullmatch(script_hash) is None:
        raise InvalidHashError("Invalid script hash")


def store_script_atomically(
    storage_dir: Path,
    script_source: str,
    max_script_upload_bytes: int,
) -> str:
    script_bytes = script_source.encode("utf-8")
    if len(script_bytes) > max_script_upload_bytes:
        raise ScriptTooLargeError("Script upload exceeds maximum size")

    script_hash = calculate_script_hash(script_bytes)
    storage_dir.mkdir(parents=True, exist_ok=True)
    target_path = storage_dir / script_hash

    if target_path.exists():
        return script_hash

    fd, temp_path_raw = tempfile.mkstemp(prefix=f".{script_hash}.", dir=storage_dir)
    temp_path = Path(temp_path_raw)

    try:
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(script_bytes)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        if target_path.exists():
            temp_path.unlink(missing_ok=True)
            return script_hash

        os.replace(temp_path, target_path)
        _fsync_directory(storage_dir)
        return script_hash
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def delete_script(storage_dir: Path, script_hash: str) -> None:
    validate_hash(script_hash)
    (storage_dir / script_hash).unlink(missing_ok=True)


def script_path(storage_dir: Path, script_hash: str) -> Path:
    validate_hash(script_hash)
    return storage_dir / script_hash


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return

    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
