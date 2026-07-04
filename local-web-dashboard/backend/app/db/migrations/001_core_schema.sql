PRAGMA foreign_keys = ON;

CREATE TABLE node (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  host TEXT NOT NULL,
  port INTEGER NOT NULL DEFAULT 443 CHECK (port > 0 AND port <= 65535),
  status TEXT NOT NULL CHECK (
    status IN (
      'installing_agent',
      'bootstrap_pending',
      'mtls_pairing',
      'metrics_uploading',
      'active',
      'failed_install',
      'failed_bootstrap_timeout',
      'failed_mtls_pairing',
      'failed_metrics_upload',
      'unpairing',
      'uninstalling',
      'deleting_local'
    )
  ),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE node_mtls_identity (
  node_id INTEGER PRIMARY KEY REFERENCES node(id) ON DELETE CASCADE,
  agent_cert_fingerprint TEXT NOT NULL UNIQUE,
  agent_public_key_fingerprint TEXT,
  agent_cert_serial TEXT,
  issued_at TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE node_bootstrap_state (
  node_id INTEGER PRIMARY KEY REFERENCES node(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  absolute_expires_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'closed', 'expired')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE script (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  content TEXT NOT NULL,
  current_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE folder (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE "trigger" (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('schedule', 'on_startup')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE trigger_schedule (
  trigger_id INTEGER PRIMARY KEY REFERENCES "trigger"(id) ON DELETE CASCADE,
  interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0)
);

CREATE TABLE trigger_on_startup (
  trigger_id INTEGER PRIMARY KEY REFERENCES "trigger"(id) ON DELETE CASCADE
);

CREATE TABLE folder_node (
  folder_id INTEGER NOT NULL REFERENCES folder(id) ON DELETE CASCADE,
  node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (folder_id, node_id)
);

CREATE TABLE folder_script (
  folder_id INTEGER NOT NULL REFERENCES folder(id) ON DELETE CASCADE,
  script_id INTEGER NOT NULL REFERENCES script(id) ON DELETE CASCADE,
  trigger_id INTEGER REFERENCES "trigger"(id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (folder_id, script_id)
);

CREATE TABLE node_script (
  id INTEGER PRIMARY KEY,
  node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
  script_id INTEGER NOT NULL REFERENCES script(id) ON DELETE CASCADE,
  folder_id INTEGER REFERENCES folder(id) ON DELETE RESTRICT,
  trigger_id INTEGER REFERENCES "trigger"(id) ON DELETE RESTRICT,
  last_run_status TEXT CHECK (
    last_run_status IS NULL OR last_run_status IN ('success', 'failed', 'timeout', 'transport_error')
  ),
  last_run_at TEXT,
  last_run_request_id TEXT,
  last_run_error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX ux_node_script_folder
  ON node_script(node_id, script_id, folder_id)
  WHERE folder_id IS NOT NULL;

CREATE UNIQUE INDEX ux_node_script_manual_no_trigger
  ON node_script(node_id, script_id)
  WHERE folder_id IS NULL AND trigger_id IS NULL;

CREATE UNIQUE INDEX ux_node_script_manual_with_trigger
  ON node_script(node_id, script_id, trigger_id)
  WHERE folder_id IS NULL AND trigger_id IS NOT NULL;

CREATE TABLE node_hash_gc (
  id INTEGER PRIMARY KEY,
  node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
  hash TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (reason IN ('script_deleted', 'script_updated', 'binding_removed')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'cancelled', 'failed')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_attempt_at TEXT,
  UNIQUE (node_id, hash)
);

CREATE TABLE pipeline (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE pipeline_step (
  id INTEGER PRIMARY KEY,
  pipeline_id INTEGER NOT NULL REFERENCES pipeline(id) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK (position > 0),
  node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
  script_id INTEGER NOT NULL REFERENCES script(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (pipeline_id, position)
);

CREATE TABLE pipeline_step_arg (
  id INTEGER PRIMARY KEY,
  step_id INTEGER NOT NULL REFERENCES pipeline_step(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK (source_type IN ('static', 'step_output')),
  static_value TEXT,
  source_step_id INTEGER REFERENCES pipeline_step(id) ON DELETE CASCADE,
  source_json_path TEXT,
  UNIQUE (step_id, name)
);

CREATE TABLE pipeline_run (
  id INTEGER PRIMARY KEY,
  pipeline_id INTEGER NOT NULL REFERENCES pipeline(id) ON DELETE RESTRICT,
  status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'cancelled')),
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT
);

CREATE TABLE pipeline_run_step (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES pipeline_run(id) ON DELETE CASCADE,
  step_id INTEGER REFERENCES pipeline_step(id) ON DELETE SET NULL,
  step_position INTEGER NOT NULL,
  node_id_snapshot INTEGER NOT NULL,
  script_id_snapshot INTEGER NOT NULL,
  script_name_snapshot TEXT NOT NULL,
  script_hash_snapshot TEXT NOT NULL,
  resolved_args_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'success', 'failed', 'skipped')),
  stdout TEXT,
  stderr TEXT,
  exit_code INTEGER,
  error_class TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TRIGGER trg_folder_node_fanout
AFTER INSERT ON folder_node
BEGIN
  INSERT OR IGNORE INTO node_script (node_id, script_id, folder_id)
  SELECT NEW.node_id, fs.script_id, NEW.folder_id
  FROM folder_script fs
  WHERE fs.folder_id = NEW.folder_id;
END;

CREATE TRIGGER trg_folder_script_fanout
AFTER INSERT ON folder_script
BEGIN
  INSERT OR IGNORE INTO node_script (node_id, script_id, folder_id)
  SELECT fn.node_id, NEW.script_id, NEW.folder_id
  FROM folder_node fn
  WHERE fn.folder_id = NEW.folder_id;
END;

CREATE TRIGGER trg_folder_node_revoke
AFTER DELETE ON folder_node
BEGIN
  DELETE FROM node_script
  WHERE node_id = OLD.node_id
    AND folder_id = OLD.folder_id;
END;

CREATE TRIGGER trg_folder_script_revoke
AFTER DELETE ON folder_script
BEGIN
  DELETE FROM node_script
  WHERE script_id = OLD.script_id
    AND folder_id = OLD.folder_id;
END;

CREATE TRIGGER trg_node_script_trigger_cleanup_after_update
AFTER UPDATE OF trigger_id ON node_script
WHEN OLD.trigger_id IS NOT NULL
BEGIN
  DELETE FROM "trigger"
  WHERE id = OLD.trigger_id
    AND NOT EXISTS (SELECT 1 FROM node_script WHERE trigger_id = OLD.trigger_id)
    AND NOT EXISTS (SELECT 1 FROM folder_script WHERE trigger_id = OLD.trigger_id);
END;

CREATE TRIGGER trg_node_script_trigger_cleanup_after_delete
AFTER DELETE ON node_script
WHEN OLD.trigger_id IS NOT NULL
BEGIN
  DELETE FROM "trigger"
  WHERE id = OLD.trigger_id
    AND NOT EXISTS (SELECT 1 FROM node_script WHERE trigger_id = OLD.trigger_id)
    AND NOT EXISTS (SELECT 1 FROM folder_script WHERE trigger_id = OLD.trigger_id);
END;

CREATE TRIGGER trg_folder_script_trigger_cleanup_after_update
AFTER UPDATE OF trigger_id ON folder_script
WHEN OLD.trigger_id IS NOT NULL
BEGIN
  DELETE FROM "trigger"
  WHERE id = OLD.trigger_id
    AND NOT EXISTS (SELECT 1 FROM node_script WHERE trigger_id = OLD.trigger_id)
    AND NOT EXISTS (SELECT 1 FROM folder_script WHERE trigger_id = OLD.trigger_id);
END;

CREATE TRIGGER trg_folder_script_trigger_cleanup_after_delete
AFTER DELETE ON folder_script
WHEN OLD.trigger_id IS NOT NULL
BEGIN
  DELETE FROM "trigger"
  WHERE id = OLD.trigger_id
    AND NOT EXISTS (SELECT 1 FROM node_script WHERE trigger_id = OLD.trigger_id)
    AND NOT EXISTS (SELECT 1 FROM folder_script WHERE trigger_id = OLD.trigger_id);
END;
