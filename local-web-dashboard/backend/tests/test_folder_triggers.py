import sqlite3
from pathlib import Path

import pytest

from backend.app.architecture.constants import NODE_LIFECYCLE_STATES_V1
from backend.app.db import apply_migrations


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


def _insert_node(db: sqlite3.Connection, name: str) -> int:
    cursor = db.execute(
        "INSERT INTO node(name, host, status) VALUES (?, ?, ?)",
        (name, "127.0.0.1", NODE_LIFECYCLE_STATES_V1[0]),
    )
    return int(cursor.lastrowid)


def _insert_script(db: sqlite3.Connection, name: str) -> int:
    cursor = db.execute(
        "INSERT INTO script(name, content, current_hash) VALUES (?, ?, ?)",
        (name, "#!/bin/sh\ntrue\n", f"sha256-{name}"),
    )
    return int(cursor.lastrowid)


def _insert_folder(db: sqlite3.Connection, name: str = "folder-a") -> int:
    return int(db.execute("INSERT INTO folder(name) VALUES (?)", (name,)).lastrowid)


def _insert_schedule_trigger(db: sqlite3.Connection, interval_seconds: int = 60) -> int:
    trigger_id = int(
        db.execute('INSERT INTO "trigger"(type) VALUES (?)', ("schedule",)).lastrowid
    )
    db.execute(
        "INSERT INTO trigger_schedule(trigger_id, interval_seconds) VALUES (?, ?)",
        (trigger_id, interval_seconds),
    )
    return trigger_id


def _node_script_rows(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT node_id, script_id, folder_id, trigger_id "
        "FROM node_script ORDER BY node_id, script_id"
    ).fetchall()


def test_folder_node_fanout_creates_node_scripts_for_existing_folder_scripts(
    db: sqlite3.Connection,
) -> None:
    folder_id = _insert_folder(db)
    node_id = _insert_node(db, "node-a")
    script_a = _insert_script(db, "script-a")
    script_b = _insert_script(db, "script-b")

    db.execute(
        "INSERT INTO folder_script(folder_id, script_id) VALUES (?, ?)",
        (folder_id, script_a),
    )
    db.execute(
        "INSERT INTO folder_script(folder_id, script_id) VALUES (?, ?)",
        (folder_id, script_b),
    )
    db.execute(
        "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
        (folder_id, node_id),
    )

    assert [(row["node_id"], row["script_id"], row["folder_id"]) for row in _node_script_rows(db)] == [
        (node_id, script_a, folder_id),
        (node_id, script_b, folder_id),
    ]


def test_folder_script_fanout_creates_node_scripts_for_existing_folder_nodes(
    db: sqlite3.Connection,
) -> None:
    folder_id = _insert_folder(db)
    node_a = _insert_node(db, "node-a")
    node_b = _insert_node(db, "node-b")
    script_id = _insert_script(db, "script-a")

    db.execute(
        "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
        (folder_id, node_a),
    )
    db.execute(
        "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
        (folder_id, node_b),
    )
    db.execute(
        "INSERT INTO folder_script(folder_id, script_id) VALUES (?, ?)",
        (folder_id, script_id),
    )

    assert [(row["node_id"], row["script_id"], row["folder_id"]) for row in _node_script_rows(db)] == [
        (node_a, script_id, folder_id),
        (node_b, script_id, folder_id),
    ]


def test_folder_revoke_removes_only_materialized_rows_and_keeps_manual_rows(
    db: sqlite3.Connection,
) -> None:
    folder_id = _insert_folder(db)
    node_id = _insert_node(db, "node-a")
    script_id = _insert_script(db, "script-a")

    db.execute(
        "INSERT INTO node_script(node_id, script_id) VALUES (?, ?)",
        (node_id, script_id),
    )
    db.execute(
        "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
        (folder_id, node_id),
    )
    db.execute(
        "INSERT INTO folder_script(folder_id, script_id) VALUES (?, ?)",
        (folder_id, script_id),
    )

    assert db.execute("SELECT COUNT(*) FROM node_script").fetchone()[0] == 2

    db.execute(
        "DELETE FROM folder_node WHERE folder_id = ? AND node_id = ?",
        (folder_id, node_id),
    )

    rows = db.execute(
        "SELECT folder_id, trigger_id FROM node_script WHERE node_id = ? AND script_id = ?",
        (node_id, script_id),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["folder_id"] is None
    assert rows[0]["trigger_id"] is None


def test_folder_script_revoke_removes_only_rows_for_that_folder_script(
    db: sqlite3.Connection,
) -> None:
    folder_id = _insert_folder(db)
    node_a = _insert_node(db, "node-a")
    node_b = _insert_node(db, "node-b")
    script_a = _insert_script(db, "script-a")
    script_b = _insert_script(db, "script-b")

    for node_id in (node_a, node_b):
        db.execute(
            "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
            (folder_id, node_id),
        )
    for script_id in (script_a, script_b):
        db.execute(
            "INSERT INTO folder_script(folder_id, script_id) VALUES (?, ?)",
            (folder_id, script_id),
        )

    db.execute(
        "DELETE FROM folder_script WHERE folder_id = ? AND script_id = ?",
        (folder_id, script_a),
    )

    rows = _node_script_rows(db)
    assert [(row["node_id"], row["script_id"]) for row in rows] == [
        (node_a, script_b),
        (node_b, script_b),
    ]


def test_sql_fanout_does_not_copy_folder_template_trigger(
    db: sqlite3.Connection,
) -> None:
    folder_id = _insert_folder(db)
    node_a = _insert_node(db, "node-a")
    node_b = _insert_node(db, "node-b")
    script_id = _insert_script(db, "script-a")
    template_trigger = _insert_schedule_trigger(db, 60)

    db.execute(
        "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
        (folder_id, node_a),
    )
    db.execute(
        "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
        (folder_id, node_b),
    )
    db.execute(
        "INSERT INTO folder_script(folder_id, script_id, trigger_id) VALUES (?, ?, ?)",
        (folder_id, script_id, template_trigger),
    )

    rows = _node_script_rows(db)
    assert len(rows) == 2
    assert {row["trigger_id"] for row in rows} == {None}
    assert (
        db.execute(
            "SELECT trigger_id FROM folder_script WHERE folder_id = ? AND script_id = ?",
            (folder_id, script_id),
        ).fetchone()["trigger_id"]
        == template_trigger
    )


def test_materialized_trigger_copies_are_independent_when_service_clones_them(
    db: sqlite3.Connection,
) -> None:
    folder_id = _insert_folder(db)
    node_a = _insert_node(db, "node-a")
    node_b = _insert_node(db, "node-b")
    script_id = _insert_script(db, "script-a")

    for node_id in (node_a, node_b):
        db.execute(
            "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
            (folder_id, node_id),
        )
    db.execute(
        "INSERT INTO folder_script(folder_id, script_id) VALUES (?, ?)",
        (folder_id, script_id),
    )

    materialized_ids = [
        row["id"]
        for row in db.execute(
            "SELECT id FROM node_script WHERE folder_id = ? ORDER BY node_id",
            (folder_id,),
        )
    ]
    trigger_a = _insert_schedule_trigger(db, 60)
    trigger_b = _insert_schedule_trigger(db, 60)
    db.execute(
        "UPDATE node_script SET trigger_id = ? WHERE id = ?",
        (trigger_a, materialized_ids[0]),
    )
    db.execute(
        "UPDATE node_script SET trigger_id = ? WHERE id = ?",
        (trigger_b, materialized_ids[1]),
    )

    db.execute(
        "UPDATE trigger_schedule SET interval_seconds = ? WHERE trigger_id = ?",
        (240, trigger_a),
    )

    intervals = {
        row["trigger_id"]: row["interval_seconds"]
        for row in db.execute(
            "SELECT trigger_id, interval_seconds FROM trigger_schedule ORDER BY trigger_id"
        )
    }
    assert intervals[trigger_a] == 240
    assert intervals[trigger_b] == 60


def test_editing_folder_template_trigger_is_not_retroactive(
    db: sqlite3.Connection,
) -> None:
    folder_id = _insert_folder(db)
    node_id = _insert_node(db, "node-a")
    script_id = _insert_script(db, "script-a")
    template_trigger = _insert_schedule_trigger(db, 60)

    db.execute(
        "INSERT INTO folder_node(folder_id, node_id) VALUES (?, ?)",
        (folder_id, node_id),
    )
    db.execute(
        "INSERT INTO folder_script(folder_id, script_id, trigger_id) VALUES (?, ?, ?)",
        (folder_id, script_id, template_trigger),
    )

    materialized_before = db.execute(
        "SELECT trigger_id FROM node_script WHERE folder_id = ?",
        (folder_id,),
    ).fetchone()["trigger_id"]

    db.execute(
        "UPDATE trigger_schedule SET interval_seconds = ? WHERE trigger_id = ?",
        (3600, template_trigger),
    )
    new_template_trigger = _insert_schedule_trigger(db, 7200)
    db.execute(
        "UPDATE folder_script SET trigger_id = ? WHERE folder_id = ? AND script_id = ?",
        (new_template_trigger, folder_id, script_id),
    )

    materialized_after = db.execute(
        "SELECT trigger_id FROM node_script WHERE folder_id = ?",
        (folder_id,),
    ).fetchone()["trigger_id"]

    assert materialized_before is None
    assert materialized_after is None


def test_orphan_trigger_cleanup_after_last_reference_disappears_or_is_replaced(
    db: sqlite3.Connection,
) -> None:
    folder_id = _insert_folder(db)
    node_id = _insert_node(db, "node-a")
    script_id = _insert_script(db, "script-a")
    trigger_id = _insert_schedule_trigger(db, 60)
    replacement_trigger = _insert_schedule_trigger(db, 120)

    db.execute(
        "INSERT INTO folder_script(folder_id, script_id, trigger_id) VALUES (?, ?, ?)",
        (folder_id, script_id, trigger_id),
    )
    db.execute(
        "INSERT INTO node_script(node_id, script_id, trigger_id) VALUES (?, ?, ?)",
        (node_id, script_id, trigger_id),
    )

    db.execute(
        "UPDATE node_script SET trigger_id = ? WHERE node_id = ? AND script_id = ?",
        (replacement_trigger, node_id, script_id),
    )
    assert db.execute(
        'SELECT COUNT(*) FROM "trigger" WHERE id = ?',
        (trigger_id,),
    ).fetchone()[0] == 1

    db.execute(
        "DELETE FROM folder_script WHERE folder_id = ? AND script_id = ?",
        (folder_id, script_id),
    )
    assert db.execute(
        'SELECT COUNT(*) FROM "trigger" WHERE id = ?',
        (trigger_id,),
    ).fetchone()[0] == 0
    assert db.execute(
        'SELECT COUNT(*) FROM "trigger" WHERE id = ?',
        (replacement_trigger,),
    ).fetchone()[0] == 1


def test_sql_triggers_do_not_create_remote_work_or_product_level_decisions(
    db: sqlite3.Connection,
) -> None:
    trigger_sql = "\n".join(
        row["sql"].lower()
        for row in db.execute("SELECT sql FROM sqlite_master WHERE type = 'trigger'")
    )
    migration_sql = MIGRATION_SQL.read_text(encoding="utf-8").lower()

    assert "insert into node_hash_gc" not in trigger_sql
    assert "node_hash_gc" not in trigger_sql
    fanout_triggers = db.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'trigger' AND name LIKE 'trg_folder_%fanout'"
    ).fetchall()
    assert {row["name"] for row in fanout_triggers} == {
        "trg_folder_node_fanout",
        "trg_folder_script_fanout",
    }
    for row in fanout_triggers:
        insert_columns = row["sql"].lower().split("node_script", 1)[1].split(")", 1)[0]
        assert "trigger_id" not in insert_columns

    for forbidden in (
        "http://",
        "https://",
        "httpx",
        "requests.",
        "curl ",
        "socket",
        "subprocess",
        "powershell",
    ):
        assert forbidden not in migration_sql
