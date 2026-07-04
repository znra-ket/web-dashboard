import hashlib
from pathlib import Path

import pytest

from webxray_agent.config import AgentPaths
from webxray_agent.constants import (
    MAX_AGENT_SCRIPT_STORAGE_BYTES,
    MAX_SCRIPT_UPLOAD_BYTES,
)
from webxray_agent.storage import (
    InvalidScriptHash,
    ScriptStorage,
    ScriptStorageQuotaExceeded,
    ScriptUploadTooLarge,
)


def _storage(tmp_path: Path, **limits: int) -> ScriptStorage:
    paths = AgentPaths.from_install_root(tmp_path / "agent")
    return ScriptStorage(paths, **limits)


def test_same_content_returns_same_hash_and_single_physical_file(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    content = b"#!/bin/sh\necho hello\n"

    first_hash = storage.store_script(content)
    second_hash = storage.store_script(content)

    assert first_hash == second_hash
    assert storage.has_script(first_hash) is True
    assert len(list(storage.root.iterdir())) == 1


def test_hash_is_computed_from_actual_bytes(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    content = b"actual bytes"

    actual_hash = storage.store_script(content)

    assert actual_hash == hashlib.sha256(content).hexdigest()
    assert (storage.root / actual_hash).read_bytes() == content


def test_wrong_client_hash_is_ignored_and_actual_hash_is_returned(
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    content = b"agent computes this"
    wrong_client_hash = "0" * 64

    actual_hash = storage.store_script(content, client_hash=wrong_client_hash)

    assert actual_hash == hashlib.sha256(content).hexdigest()
    assert actual_hash != wrong_client_hash
    assert storage.has_script(actual_hash) is True
    assert storage.has_script(wrong_client_hash) is False


def test_upload_over_one_mib_is_rejected(tmp_path: Path) -> None:
    storage = _storage(tmp_path)

    with pytest.raises(ScriptUploadTooLarge):
        storage.store_script(b"x" * (MAX_SCRIPT_UPLOAD_BYTES + 1))

    assert not storage.root.exists() or list(storage.root.iterdir()) == []


def test_storage_quota_is_enforced(tmp_path: Path) -> None:
    storage = _storage(tmp_path, storage_quota_bytes=10)

    first_hash = storage.store_script(b"12345")
    second_hash = storage.store_script(b"67890")

    with pytest.raises(ScriptStorageQuotaExceeded):
        storage.store_script(b"overflow")

    assert storage.has_script(first_hash)
    assert storage.has_script(second_hash)
    assert sum(path.stat().st_size for path in storage.root.iterdir()) == 10


def test_storage_quota_default_matches_manifest() -> None:
    storage = ScriptStorage(AgentPaths.from_install_root(Path("unused")))

    assert storage.upload_limit_bytes == MAX_SCRIPT_UPLOAD_BYTES
    assert storage.storage_quota_bytes == MAX_AGENT_SCRIPT_STORAGE_BYTES


def test_delete_missing_hash_succeeds(tmp_path: Path) -> None:
    storage = _storage(tmp_path)

    storage.delete_script("a" * 64)

    assert storage.has_script("a" * 64) is False


def test_delete_existing_hash_is_idempotent(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    script_hash = storage.store_script(b"delete me")

    storage.delete_script(script_hash)
    storage.delete_script(script_hash)

    assert storage.has_script(script_hash) is False


@pytest.mark.parametrize(
    "bad_hash",
    [
        "../escape",
        "abc/def",
        "A" * 64,
        "g" * 64,
        "a" * 63,
        "a" * 65,
    ],
)
def test_path_traversal_and_invalid_hashes_are_rejected(
    tmp_path: Path,
    bad_hash: str,
) -> None:
    storage = _storage(tmp_path)

    with pytest.raises(InvalidScriptHash):
        storage.has_script(bad_hash)
    with pytest.raises(InvalidScriptHash):
        storage.delete_script(bad_hash)


def test_symlink_named_like_hash_is_not_treated_as_stored_script(
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    storage.root.mkdir(parents=True)
    script_hash = "a" * 64
    target = tmp_path / "outside"
    target.write_text("outside", encoding="utf-8")

    try:
        (storage.root / script_hash).symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available in this environment")

    assert storage.has_script(script_hash) is False

    storage.delete_script(script_hash)
    assert target.read_text(encoding="utf-8") == "outside"
