# INVARIANTS.md

Prompt ID: Prompt 00
Source: `ARCHITECTURE_INDEX.md`

## Fundamental Invariants

1. Dashboard is local, not SaaS. One dashboard instance is operated by one owner or team.
2. One node belongs to one dashboard installation. A node must not be managed by two dashboard installations at the same time.
3. The dashboard always initiates connections. The agent never opens a connection to the dashboard.
4. After onboarding, the regular transport is mTLS. SSH is used only for initial agent installation.
5. The agent is a dumb executor. It does not know script names, folders, pipelines, trigger semantics, or dashboard business logic.
6. Scripts on the agent are stored by content hash. The dashboard stores `script.name -> current_hash`; the agent stores physical files by hash only.
7. `node_script` is desired-state, not delivery fact. Physical delivery may happen lazily through `execute -> 404 -> upload -> execute`.
8. Physical garbage is cleaned through reconciliation. Old hashes are removed through `node_hash_gc`, not SQL triggers and not as a mandatory part of the local transaction.
9. An agent mTLS certificate is valid for the dashboard only together with an active `node`. TLS validation alone is insufficient; the certificate fingerprint must match an active DB record.
10. Online node deletion breaks the agent trust in the dashboard. Even "delete only from dashboard" first performs `unpair` if the node is online.
11. An offline node does not block local desired-state changes. Remote debt is created only if the entity remains active in the DB.
12. Pipeline orchestration belongs to the dashboard. The agent sees only a sequence of ordinary `execute` calls.

## Session Hard Stops

The coding prompts also require these hard stops to stay true throughout implementation:

- `verify=False`, disabled TLS chain validation, and fake application-level fingerprint-only TLS are forbidden.
- Protected `AgentClient` requests require client certificate/key and active-node fingerprint binding.
- SQL triggers do not perform network operations and do not make product-level decisions.
- Local desired-state changes happen inside SQLite transactions; remote HTTP calls to agents happen only after commit.
- `node_hash_gc` is created by service code after desired-state diff, not by a SQL trigger.
- Executor v1 must enforce upload, body, stdout, stderr, timeout, concurrency, request_id cache, process, open file, memory, and workdir limits.
- Placeholder, fake-success, and deferred claims are forbidden for security, lifecycle, and foundation paths.

## Machine-Readable Manifest Source Values

The runtime constants in `backend/app/architecture/constants.py` must mirror this block exactly. The block is intentionally plain text so tests can compare the code manifest to the architecture source without adding parser dependencies.

### Node Lifecycle States v1
```text
installing_agent
bootstrap_pending
mtls_pairing
metrics_uploading
active
failed_install
failed_bootstrap_timeout
failed_mtls_pairing
failed_metrics_upload
unpairing
uninstalling
deleting_local
```

### Agent Limits v1
```text
max_script_upload_bytes=1048576
max_agent_script_storage_bytes=67108864
max_execute_body_bytes=131072
max_args_count=64
max_single_arg_bytes=16384
max_args_total_bytes=65536
max_env_count=64
max_env_key_bytes=128
max_single_env_value_bytes=16384
max_env_total_bytes=65536
max_stdout_bytes=262144
max_stderr_bytes=262144
default_timeout_seconds=60
max_timeout_seconds=600
speedtest_timeout_seconds=180
shutdown_grace_seconds=5
max_concurrent_executions_global=2
max_concurrent_executions_per_hash=1
request_id_cache_ttl_seconds=3600
request_id_cache_max_entries=1024
max_processes_per_run=32
max_open_files_per_run=64
max_memory_bytes_per_run=268435456
workdir_quota_bytes_per_run=67108864
```

### Trigger Types v1
```text
schedule
on_startup
```

### Bootstrap Token v1
```text
bootstrap_token_bytes=32
bootstrap_token_ttl_seconds=900
bootstrap_absolute_window_seconds=1800
```

### Agent Features v1
```text
script_upload
script_execute
script_delete
admin_unpair
admin_uninstall
```

### Pipeline Limits v1
```text
max_pipeline_steps=32
```
