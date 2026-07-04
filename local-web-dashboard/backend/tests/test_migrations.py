import sqlite3
from pathlib import Path

import pytest

from backend.app.architecture.constants import (
    MAX_PIPELINE_STEPS,
    NODE_LIFECYCLE_STATES_V1,
)
from backend.app.db import apply_migrations
from backend.app.models import Base


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SQL = (
    PROJECT_ROOT / "backend" / "app" / "db" / "migrations" / "001_core_schema.sql"
)


@pytest.fixture()
def db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    yield connection
    connection.close()


def _insert_node(db: sqlite3.Connection, name: str = "node-a") -> int:
    cursor = db.execute(
        "INSERT INTO node(name, host, status) VALUES (?, ?, ?)",
        (name, "127.0.0.1", NODE_LIFECYCLE_STATES_V1[0]),
    )
    return int(cursor.lastrowid)


def _insert_script(db: sqlite3.Connection, name: str = "script-a") -> int:
    cursor = db.execute(
        "INSERT INTO script(name, content, current_hash) VALUES (?, ?, ?)",
        (name, "#!/bin/sh\ntrue\n", f"sha256-{name}"),
    )
    return int(cursor.lastrowid)


def _insert_folder(db: sqlite3.Connection, name: str = "folder-a") -> int:
    cursor = db.execute("INSERT INTO folder(name) VALUES (?)", (name,))
    return int(cursor.lastrowid)


def _insert_trigger(db: sqlite3.Connection, trigger_type: str = "schedule") -> int:
    cursor = db.execute('INSERT INTO "trigger"(type) VALUES (?)', (trigger_type,))
    trigger_id = int(cursor.lastrowid)
    if trigger_type == "schedule":
        db.execute(
            "INSERT INTO trigger_schedule(trigger_id, interval_seconds) VALUES (?, ?)",
            (trigger_id, 60),
        )
    elif trigger_type == "on_startup":
        db.execute("INSERT INTO trigger_on_startup(trigger_id) VALUES (?)", (trigger_id,))
    return trigger_id


def test_core_migration_applies_on_empty_database(db: sqlite3.Connection) -> None:
    actual_tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }

    assert set(Base.metadata.tables) == actual_tables


def test_foreign_keys_are_enabled_and_enforced(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO node_script(node_id, script_id) VALUES (?, ?)",
            (999, 999),
        )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO node_mtls_identity(node_id, agent_cert_fingerprint) "
            "VALUES (?, ?)",
            (999, "fp-missing-node"),
        )


def test_bootstrap_state_has_no_raw_token_column(db: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(node_bootstrap_state)").fetchall()
    }

    assert "token_hash" in columns
    assert "token" not in columns
    assert "raw_token" not in columns
    assert "bootstrap_token" not in columns


def test_partial_unique_indexes_for_node_script_manual_and_folder_links(
    db: sqlite3.Connection,
) -> None:
    node_id = _insert_node(db)
    script_id = _insert_script(db)
    folder_a = _insert_folder(db, "folder-a")
    folder_b = _insert_folder(db, "folder-b")

    db.execute(
        "INSERT INTO node_script(node_id, script_id) VALUES (?, ?)",
        (node_id, script_id),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO node_script(node_id, script_id) VALUES (?, ?)",
            (node_id, script_id),
        )

    trigger_a = _insert_trigger(db, "schedule")
    trigger_b = _insert_trigger(db, "on_startup")
    db.execute(
        "INSERT INTO node_script(node_id, script_id, trigger_id) VALUES (?, ?, ?)",
        (node_id, script_id, trigger_a),
    )
    db.execute(
        "INSERT INTO node_script(node_id, script_id, trigger_id) VALUES (?, ?, ?)",
        (node_id, script_id, trigger_b),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO node_script(node_id, script_id, trigger_id) VALUES (?, ?, ?)",
            (node_id, script_id, trigger_a),
        )

    db.execute(
        "INSERT INTO node_script(node_id, script_id, folder_id) VALUES (?, ?, ?)",
        (node_id, script_id, folder_a),
    )
    db.execute(
        "INSERT INTO node_script(node_id, script_id, folder_id) VALUES (?, ?, ?)",
        (node_id, script_id, folder_b),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO node_script(node_id, script_id, folder_id) VALUES (?, ?, ?)",
            (node_id, script_id, folder_a),
        )


def test_node_script_has_minimal_last_run_fields_not_delivery_state(
    db: sqlite3.Connection,
) -> None:
    columns = {row["name"] for row in db.execute("PRAGMA table_info(node_script)")}

    assert {
        "last_run_status",
        "last_run_at",
        "last_run_request_id",
        "last_run_error",
    }.issubset(columns)
    assert "delivered_at" not in columns
    assert "uploaded_at" not in columns
    assert "physical_hash_present" not in columns


def test_manual_only_is_null_trigger_id_and_not_trigger_type(
    db: sqlite3.Connection,
) -> None:
    node_id = _insert_node(db)
    script_id = _insert_script(db)

    db.execute(
        "INSERT INTO node_script(node_id, script_id, trigger_id) VALUES (?, ?, NULL)",
        (node_id, script_id),
    )
    row = db.execute("SELECT trigger_id FROM node_script").fetchone()
    assert row["trigger_id"] is None

    with pytest.raises(sqlite3.IntegrityError):
        db.execute('INSERT INTO "trigger"(type) VALUES (?)', ("manual",))


def test_invalid_trigger_type_is_rejected(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('INSERT INTO "trigger"(type) VALUES (?)', ("pipeline_step",))


def test_lifecycle_status_check_uses_v1_states(db: sqlite3.Connection) -> None:
    node_id = _insert_node(db, "valid-state-node")
    assert node_id > 0

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO node(name, host, status) VALUES (?, ?, ?)",
            ("bad-state-node", "127.0.0.2", "unpaired"),
        )


def test_folder_materialization_and_revoke_do_not_create_hash_gc(
    db: sqlite3.Connection,
) -> None:
    node_id = _insert_node(db)
    script_id = _insert_script(db)
    folder_id = _insert_folder(db)

    db.execute(
        "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
        (folder_id, node_id),
    )
    db.execute(
        "INSERT INTO folder_script(folder_id, script_id) VALUES (?, ?)",
        (folder_id, script_id),
    )

    assert db.execute("SELECT COUNT(*) FROM node_script").fetchone()[0] == 1

    db.execute(
        "DELETE FROM folder_node WHERE folder_id = ? AND node_id = ?",
        (folder_id, node_id),
    )

    assert db.execute("SELECT COUNT(*) FROM node_script").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM node_hash_gc").fetchone()[0] == 0


def test_folder_delete_is_restricted_until_application_handles_node_script(
    db: sqlite3.Connection,
) -> None:
    node_id = _insert_node(db)
    script_id = _insert_script(db)
    folder_id = _insert_folder(db)

    db.execute(
        "INSERT INTO node_script(node_id, script_id, folder_id) VALUES (?, ?, ?)",
        (node_id, script_id, folder_id),
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM folder WHERE id = ?", (folder_id,))

    db.execute("DELETE FROM node_script WHERE folder_id = ?", (folder_id,))
    db.execute("DELETE FROM folder WHERE id = ?", (folder_id,))
    assert db.execute("SELECT COUNT(*) FROM folder").fetchone()[0] == 0


def test_orphan_trigger_cleanup_is_local_only(db: sqlite3.Connection) -> None:
    node_id = _insert_node(db)
    script_id = _insert_script(db)
    trigger_id = _insert_trigger(db, "schedule")

    cursor = db.execute(
        "INSERT INTO node_script(node_id, script_id, trigger_id) VALUES (?, ?, ?)",
        (node_id, script_id, trigger_id),
    )
    node_script_id = int(cursor.lastrowid)

    db.execute(
        "UPDATE node_script SET trigger_id = NULL WHERE id = ?",
        (node_script_id,),
    )

    assert (
        db.execute('SELECT COUNT(*) FROM "trigger" WHERE id = ?', (trigger_id,)).fetchone()[
            0
        ]
        == 0
    )


def test_pipeline_history_keeps_snapshot_when_step_is_deleted(
    db: sqlite3.Connection,
) -> None:
    node_id = _insert_node(db)
    script_id = _insert_script(db)
    pipeline_id = int(
        db.execute("INSERT INTO pipeline(name) VALUES (?)", ("pipeline-a",)).lastrowid
    )
    assert db.execute("SELECT archived FROM pipeline").fetchone()["archived"] == 0

    step_id = int(
        db.execute(
            "INSERT INTO pipeline_step(pipeline_id, position, node_id, script_id) "
            "VALUES (?, ?, ?, ?)",
            (pipeline_id, 1, node_id, script_id),
        ).lastrowid
    )
    run_id = int(
        db.execute(
            "INSERT INTO pipeline_run(pipeline_id, status) VALUES (?, ?)",
            (pipeline_id, "running"),
        ).lastrowid
    )
    db.execute(
        "INSERT INTO pipeline_run_step("
        "run_id, step_id, step_position, node_id_snapshot, script_id_snapshot, "
        "script_name_snapshot, script_hash_snapshot, status"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            step_id,
            1,
            node_id,
            script_id,
            "script-a",
            "sha256-script-a",
            "success",
        ),
    )

    db.execute("DELETE FROM pipeline_step WHERE id = ?", (step_id,))
    row = db.execute(
        "SELECT step_id, node_id_snapshot, script_id_snapshot, script_name_snapshot "
        "FROM pipeline_run_step"
    ).fetchone()

    assert row["step_id"] is None
    assert row["node_id_snapshot"] == node_id
    assert row["script_id_snapshot"] == script_id
    assert row["script_name_snapshot"] == "script-a"


def test_migrations_and_sql_triggers_have_no_remote_logic(
    db: sqlite3.Connection,
) -> None:
    migration_sql = MIGRATION_SQL.read_text(encoding="utf-8").lower()
    for forbidden in ("http://", "https://", "httpx", "requests.", "curl ", "socket"):
        assert forbidden not in migration_sql

    trigger_sql = "\n".join(
        row["sql"].lower()
        for row in db.execute("SELECT sql FROM sqlite_master WHERE type = 'trigger'")
    )
    assert "node_hash_gc" not in trigger_sql
    assert "insert into node_hash_gc" not in trigger_sql


def test_max_pipeline_steps_constant_exists_for_future_enforcement() -> None:
    assert MAX_PIPELINE_STEPS == 32
