from dataclasses import dataclass

from app.models.node import NodeLifecycleStatus


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    statements: tuple[str, ...]


NODE_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in NodeLifecycleStatus)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version="0001_foundation",
        description="Create foundation tables",
        statements=(
            f"""
            CREATE TABLE IF NOT EXISTS node (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              address TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN ({NODE_STATUS_VALUES})),
              agent_cert_fingerprint TEXT UNIQUE,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
        ),
    ),
    Migration(
        version="0002_node_and_script_domain",
        description="Create node and script domain schema",
        statements=(
            "ALTER TABLE node RENAME COLUMN address TO host",
            "ALTER TABLE node RENAME COLUMN status TO lifecycle_status",
            "ALTER TABLE node ADD COLUMN agent_port INTEGER NOT NULL DEFAULT 8443",
            "ALTER TABLE node ADD COLUMN ssh_host_key_fingerprint TEXT",
            """
            CREATE TABLE IF NOT EXISTS script (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              content TEXT NOT NULL,
              current_hash TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
        ),
    ),
    Migration(
        version="0003_folders_and_node_script_links",
        description="Create folders and script-node binding tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS folder (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS folder_node (
              folder_id INTEGER NOT NULL REFERENCES folder(id) ON DELETE CASCADE,
              node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
              PRIMARY KEY (folder_id, node_id),
              UNIQUE (folder_id, node_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS folder_script (
              id INTEGER PRIMARY KEY,
              folder_id INTEGER NOT NULL REFERENCES folder(id) ON DELETE CASCADE,
              script_id INTEGER NOT NULL REFERENCES script(id) ON DELETE CASCADE,
              trigger_id INTEGER,
              UNIQUE (folder_id, script_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS node_script (
              id INTEGER PRIMARY KEY,
              node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
              script_id INTEGER NOT NULL REFERENCES script(id) ON DELETE CASCADE,
              folder_id INTEGER REFERENCES folder(id) ON DELETE CASCADE,
              trigger_id INTEGER,
              last_run_at TEXT,
              last_success_at TEXT,
              last_error TEXT,
              last_duration_ms INTEGER
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_node_script_folder
            ON node_script(node_id, script_id, folder_id)
            WHERE folder_id IS NOT NULL
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_node_script_manual_no_trigger
            ON node_script(node_id, script_id)
            WHERE folder_id IS NULL AND trigger_id IS NULL
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_node_script_manual_with_trigger
            ON node_script(node_id, script_id, trigger_id)
            WHERE folder_id IS NULL AND trigger_id IS NOT NULL
            """,
        ),
    ),
    Migration(
        version="0004_trigger_schema",
        description="Create trigger schema and bind trigger references",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS trigger (
              id INTEGER PRIMARY KEY,
              type TEXT NOT NULL CHECK (type IN ('schedule', 'on_startup'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS trigger_schedule (
              trigger_id INTEGER PRIMARY KEY REFERENCES trigger(id) ON DELETE CASCADE,
              interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS trigger_on_startup (
              trigger_id INTEGER PRIMARY KEY REFERENCES trigger(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE folder_script_new (
              id INTEGER PRIMARY KEY,
              folder_id INTEGER NOT NULL REFERENCES folder(id) ON DELETE CASCADE,
              script_id INTEGER NOT NULL REFERENCES script(id) ON DELETE CASCADE,
              trigger_id INTEGER REFERENCES trigger(id) ON DELETE RESTRICT,
              UNIQUE (folder_id, script_id)
            )
            """,
            """
            INSERT INTO folder_script_new (id, folder_id, script_id, trigger_id)
            SELECT id, folder_id, script_id, trigger_id FROM folder_script
            """,
            "DROP TABLE folder_script",
            "ALTER TABLE folder_script_new RENAME TO folder_script",
            "DROP INDEX IF EXISTS ux_node_script_folder",
            "DROP INDEX IF EXISTS ux_node_script_manual_no_trigger",
            "DROP INDEX IF EXISTS ux_node_script_manual_with_trigger",
            """
            CREATE TABLE node_script_new (
              id INTEGER PRIMARY KEY,
              node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
              script_id INTEGER NOT NULL REFERENCES script(id) ON DELETE CASCADE,
              folder_id INTEGER REFERENCES folder(id) ON DELETE CASCADE,
              trigger_id INTEGER REFERENCES trigger(id) ON DELETE RESTRICT,
              last_run_at TEXT,
              last_success_at TEXT,
              last_error TEXT,
              last_duration_ms INTEGER
            )
            """,
            """
            INSERT INTO node_script_new (
              id,
              node_id,
              script_id,
              folder_id,
              trigger_id,
              last_run_at,
              last_success_at,
              last_error,
              last_duration_ms
            )
            SELECT
              id,
              node_id,
              script_id,
              folder_id,
              trigger_id,
              last_run_at,
              last_success_at,
              last_error,
              last_duration_ms
            FROM node_script
            """,
            "DROP TABLE node_script",
            "ALTER TABLE node_script_new RENAME TO node_script",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_node_script_folder
            ON node_script(node_id, script_id, folder_id)
            WHERE folder_id IS NOT NULL
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_node_script_manual_no_trigger
            ON node_script(node_id, script_id)
            WHERE folder_id IS NULL AND trigger_id IS NULL
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_node_script_manual_with_trigger
            ON node_script(node_id, script_id, trigger_id)
            WHERE folder_id IS NULL AND trigger_id IS NOT NULL
            """,
        ),
    ),
    Migration(
        version="0005_folder_materialization_triggers",
        description="Materialize folder links into node_script rows",
        statements=(
            """
            CREATE TRIGGER IF NOT EXISTS trg_folder_node_fanout
            AFTER INSERT ON folder_node
            BEGIN
              INSERT OR IGNORE INTO node_script (node_id, script_id, folder_id, trigger_id)
              SELECT NEW.node_id, fs.script_id, NEW.folder_id, NULL
              FROM folder_script fs
              WHERE fs.folder_id = NEW.folder_id;
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_folder_script_fanout
            AFTER INSERT ON folder_script
            BEGIN
              INSERT OR IGNORE INTO node_script (node_id, script_id, folder_id, trigger_id)
              SELECT fn.node_id, NEW.script_id, NEW.folder_id, NULL
              FROM folder_node fn
              WHERE fn.folder_id = NEW.folder_id;
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_folder_node_revoke
            AFTER DELETE ON folder_node
            BEGIN
              DELETE FROM node_script
              WHERE node_id = OLD.node_id
                AND folder_id = OLD.folder_id;
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_folder_script_revoke
            AFTER DELETE ON folder_script
            BEGIN
              DELETE FROM node_script
              WHERE script_id = OLD.script_id
                AND folder_id = OLD.folder_id;
            END
            """,
        ),
    ),
    Migration(
        version="0006_orphan_trigger_cleanup",
        description="Cleanup trigger rows when link ownership is removed",
        statements=(
            """
            CREATE TRIGGER IF NOT EXISTS trg_cleanup_orphan_trigger_ns_del
            AFTER DELETE ON node_script
            WHEN OLD.trigger_id IS NOT NULL
            BEGIN
              DELETE FROM trigger
              WHERE id = OLD.trigger_id
                AND NOT EXISTS (SELECT 1 FROM node_script WHERE trigger_id = OLD.trigger_id)
                AND NOT EXISTS (SELECT 1 FROM folder_script WHERE trigger_id = OLD.trigger_id);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_cleanup_orphan_trigger_ns_upd
            AFTER UPDATE OF trigger_id ON node_script
            WHEN OLD.trigger_id IS NOT NULL AND OLD.trigger_id IS NOT NEW.trigger_id
            BEGIN
              DELETE FROM trigger
              WHERE id = OLD.trigger_id
                AND NOT EXISTS (SELECT 1 FROM node_script WHERE trigger_id = OLD.trigger_id)
                AND NOT EXISTS (SELECT 1 FROM folder_script WHERE trigger_id = OLD.trigger_id);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_cleanup_orphan_trigger_fs_del
            AFTER DELETE ON folder_script
            WHEN OLD.trigger_id IS NOT NULL
            BEGIN
              DELETE FROM trigger
              WHERE id = OLD.trigger_id
                AND NOT EXISTS (SELECT 1 FROM node_script WHERE trigger_id = OLD.trigger_id)
                AND NOT EXISTS (SELECT 1 FROM folder_script WHERE trigger_id = OLD.trigger_id);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_cleanup_orphan_trigger_fs_upd
            AFTER UPDATE OF trigger_id ON folder_script
            WHEN OLD.trigger_id IS NOT NULL AND OLD.trigger_id IS NOT NEW.trigger_id
            BEGIN
              DELETE FROM trigger
              WHERE id = OLD.trigger_id
                AND NOT EXISTS (SELECT 1 FROM node_script WHERE trigger_id = OLD.trigger_id)
                AND NOT EXISTS (SELECT 1 FROM folder_script WHERE trigger_id = OLD.trigger_id);
            END
            """,
        ),
    ),
    Migration(
        version="0007_node_hash_gc_queue",
        description="Create local node hash GC queue",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS node_hash_gc (
              id INTEGER PRIMARY KEY,
              node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
              hash TEXT NOT NULL,
              reason TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'done', 'cancelled', 'failed')),
              attempts INTEGER NOT NULL DEFAULT 0,
              last_attempt_at TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE (node_id, hash)
            )
            """,
        ),
    ),
    Migration(
        version="0008_node_bootstrap_token",
        description="Create node bootstrap token lifecycle table",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS node_bootstrap_token (
              id INTEGER PRIMARY KEY,
              node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
              token_hash TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              bootstrap_window_expires_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'consumed', 'expired', 'cancelled')),
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_node_bootstrap_token_node_status
            ON node_bootstrap_token(node_id, status)
            """,
        ),
    ),
)
