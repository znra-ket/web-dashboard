# CONFLICTS.md

Prompt ID: Prompt 00B
Scope: cross-document architecture conflict audit before implementation.

Resolution rule:

- If `ARCHITECTURE_INDEX.md` explicitly closes a decision, follow it.
- If the index summarizes and a thematic note is more detailed, follow the thematic note.
- If a product decision is required and cannot be inferred from existing notes, stop with `NO-GO`.

## C-001 Agent Upload Hash Contract

| Field | Content |
|---|---|
| source docs | `ARCHITECTURE_INDEX.md`; `Агент/Принцип работы агента ноды.md` |
| competing interpretations | (A) Upload accepts content and client-supplied hash, and the agent checks consistency. (B) Upload accepts script bytes/source, ignores any client-supplied hash field, computes SHA-256 from actually received bytes, and returns that hash. |
| chosen interpretation | B. The agent is the source of truth for uploaded bytes: it computes hash from actual received bytes and ignores any client-supplied hash. Dashboard may compare the returned hash to its own expected `script.current_hash` outside the agent upload contract. |
| why | `ARCHITECTURE_INDEX.md` is a summary. The agent note gives the detailed endpoint contract: `script_source` is the upload body, any `hash` field is ignored, and the returned hash is computed by the agent. This also preserves the dumb-executor boundary: the agent stores bytes by hash and does not trust dashboard metadata. |
| required tests | Prompt 07/08: upload with no hash returns SHA-256 of bytes; upload with an incorrect client `hash` field still stores/returns the hash of actual bytes; duplicate upload is idempotent; dashboard-side tests may assert returned hash matches expected content hash before marking reconciliation successful. |

Impact:

- Prompt 07 must use this interpretation. If implementation cannot satisfy it, Prompt 07 returns `NO-GO`.
- `AGENT-002` is the traceability row for this decision.

## C-002 `node_hash_gc` Ownership

| Field | Content |
|---|---|
| source docs | `ARCHITECTURE_INDEX.md`; `Transactional service boundaries.md`; `Агент/Принцип работы агента ноды.md`; `Скрипты и папки/Архитектура папок и материализация связей.md` |
| competing interpretations | (A) SQL triggers create `node_hash_gc` whenever bindings change. (B) Service code creates `node_hash_gc` after comparing desired-state before/after a local DB change. |
| chosen interpretation | B. `node_hash_gc` is created by service code after desired-state diff, inside the local service operation, and remote delete happens only after commit. |
| why | The architecture index explicitly says old hashes are removed through reconciliation, not SQL triggers. Transaction boundaries state SQL triggers do not make network/product decisions. Folder notes say SQL triggers only materialize local `node_script` rows; GC requires desired-state comparison and post-commit remote reconciliation. |
| required tests | Prompt 05/34: no HTTP during SQLite transaction; service creates GC only when old hash leaves `desired_hashes(node)`; SQL migration tests assert no SQL trigger inserts into `node_hash_gc`; reconciler rechecks desired hashes before `DELETE /v1/scripts/{hash}`. |

Impact:

- `TX-007`, `TX-008`, and `TX-009` carry this decision.

## C-003 `node_script.folder_id` FK Behavior

| Field | Content |
|---|---|
| source docs | `Скрипты и папки/Архитектура папок и материализация связей.md`; `Transactional service boundaries.md`; `Агент/Удаление ноды из дашборда.md` |
| competing interpretations | (A) `node_script.folder_id` cascades automatically when a folder is deleted. (B) `node_script.folder_id` is RESTRICT/application-controlled; service code explicitly chooses whether to keep links as manual or delete them before deleting the folder. |
| chosen interpretation | B. `node_script.folder_id` is nullable, application-controlled, and protected from accidental folder delete by RESTRICT. Folder deletion behavior is a service operation that runs in one SQLite transaction. |
| why | The folder note explicitly states `folder_id` is RESTRICT and cases 6/7 are user/product decisions. Cascade is used for `folder_node` and `folder_script`, not for `node_script.folder_id`. |
| required tests | Prompt 03/26: migration test confirms FK behavior; deleting a folder directly with materialized `node_script` rows fails or is not a supported path; service tests cover delete-with-keep-links and delete-with-remove-links in one transaction. |

Impact:

- `FOLDER-006` and `TX-004` carry this decision.

## C-004 Pipeline History: Snapshot vs FK Links

| Field | Content |
|---|---|
| source docs | `Скрипты и папки/Пайплайны и их архитектура.md`; `Агент/Удаление ноды из дашборда.md`; `ARCHITECTURE_INDEX.md` |
| competing interpretations | (A) Pipeline run history is snapshot-only and should not depend on live FK links. (B) `pipeline_run_step.step_id` uses FK `ON DELETE SET NULL`, so history can keep an optional link to the former definition. |
| chosen interpretation | Both, with clear ownership: denormalized snapshot fields are the source of truth for history; `step_id ON DELETE SET NULL` is only an optional pointer to the current/former definition and must not be required to render history. |
| why | The pipeline note explicitly defines `pipeline_run_step` as a snapshot containing denormalized `node_id`, `script_id`, resolved args, stdout/stderr, status, and also allows `step_id` to become null. These are compatible if snapshot fields are authoritative. |
| required tests | Prompt 29/31/33: completed pipeline run remains readable after deleting a pipeline step; history remains readable after deleting a node; UI/API response uses snapshot fields when `step_id IS NULL`; pipeline deletion with history archives the pipeline instead of hard delete. |

Impact:

- `PIPE-006` and `DELETE-003` carry this decision.

## C-005 mTLS Responsibility

| Field | Content |
|---|---|
| source docs | `ARCHITECTURE_INDEX.md`; `Основное/web-xray-dashboard — Основной дизайн-документ.md`; `Агент/Установка mTLS соединения дашборд - агент.md`; `Агент/Принцип работы агента ноды.md`; `Агент/Удаление ноды из дашборда.md` |
| competing interpretations | (A) App-level paired-state guards or dependency checks are enough to protect `/v1/*`. (B) Protected agent endpoints require real mTLS server/client-certificate authentication, and dashboard additionally validates peer certificate binding to an active `node`. |
| chosen interpretation | B. Agent regular and admin endpoints are protected by real mTLS runtime. Dashboard must also verify actual TLS peer certificate fingerprint/public-key fingerprint/serial against active `node` before every regular request. App-level paired-state guard alone is insufficient. |
| why | The architecture index explicitly closes this as an invariant: TLS validation alone is insufficient without active-node binding. The mTLS note says runtime mTLS is the post-pairing trust carrier. The prompt hard-stop forbids fake app-level fingerprint-only TLS. |
| required tests | Prompt 16/17/18: real TLS listener/socket negative tests reject no client cert, wrong client cert, invalid CA, and unpaired states; AgentClient cannot make protected request without client cert/key; dashboard rejects valid-chain peer cert not bound to active `node`; no `verify=False`. |

Impact:

- `API-004`, `MTLS-001`, `MTLS-005`, `MTLS-006`, and `MTLS-008` carry this decision.

## C-006 Bootstrap Close Semantics

| Field | Content |
|---|---|
| source docs | `Агент/Установка mTLS соединения дашборд - агент.md`; `Основное/Онбординг ноды в дашборд.md`; `ARCHITECTURE_INDEX.md` |
| competing interpretations | (A) Destroy bootstrap token/state immediately after certificate is sent to the agent. (B) Keep bootstrap token/state until the agent installs the certificate, restarts/enables mTLS, and dashboard confirms mTLS with a probe; then destroy both sides. |
| chosen interpretation | B. Certificate delivery is not enough. Bootstrap closes only after successful mTLS probe. If agent restart/mTLS activation fails, bootstrap token is retained until retry or TTL/absolute-window expiry. |
| why | The mTLS note explicitly states token destruction happens only after restart succeeds and dashboard confirms mTLS. This prevents a dead-end state where bootstrap is destroyed before the regular mTLS channel works. |
| required tests | Prompt 13/14/20: token stored only as hash/status/expiry; certificate install without successful mTLS probe does not close bootstrap; after successful probe dashboard marks paired and agent returns `410 bootstrap_closed` or disables bootstrap; expired token rejected after TTL/absolute window. |

Impact:

- `MTLS-002`, `MTLS-003`, `MTLS-004`, `MTLS-007`, and `ONBOARD-006` carry this decision.

## C-007 Schedule Missed-Run Policy

| Field | Content |
|---|---|
| source docs | `ARCHITECTURE_INDEX.md`; `Скрипты и папки/Триггеры запуска скриптов.md` |
| competing interpretations | (A) Missed schedule runs are replayed/caught up when backend restarts. (B) Missed schedule runs are skipped; next run is planned from current time. |
| chosen interpretation | B. Missed schedule runs are skipped, not replayed. |
| why | `ARCHITECTURE_INDEX.md` lists "Missed schedule runs не догоняются" as a closed v1 decision. The trigger note explains this avoids bursts of stale maintenance/speedtest jobs after dashboard downtime. |
| required tests | Prompt 28: scheduler startup after downtime does not enqueue historical runs; next due is computed from current time; last-run fields remain diagnostic only. |

Impact:

- `TRIGGER-006` carries this decision.

## C-008 MVP Scope: Xray Components and Metrics Scripts

| Field | Content |
|---|---|
| source docs | `Основное/web-xray-dashboard — Основной дизайн-документ.md`; `Основное/Онбординг ноды в дашборд.md`; `Агент/Принцип работы агента ноды.md`; `ARCHITECTURE_INDEX.md`; `Скрипты и папки/Архитектура папок и материализация связей.md`; `Скрипты и папки/Триггеры запуска скриптов.md` |
| competing interpretations | (A) Xray installation and metric scripts are illustrative and can be deferred from MVP. (B) Stage1 installs Xray and related components, and Stage3 requires real metric scripts `xray_status`, `detect_stack`, `speedtest` as normal scripts with schedule triggers. |
| chosen interpretation | B. Xray installation is part of Stage1 MVP. `xray_status`, `detect_stack`, and `speedtest` are real MVP scripts, uploaded through the normal script mechanism and linked to the node with independent schedule triggers. |
| why | CORE says dashboard performs initial VPS setup including Xray and related components. Onboarding details Stage1 as installing Xray, related components, and the agent. Stage3 explicitly says metrics upload plus `node_script`+schedule links are required for onboarding completion. No source marks these as after-MVP. |
| required tests | Prompt 19/21/22: Stage1 installation plan includes Xray/components and agent installation; Stage3 creates/uses real metric script rows; metrics upload uses normal upload; three manual `node_script` rows are created with independent schedule triggers; onboarding is not `active` if metrics upload/linking fails. |

Impact:

- `ONBOARD-001`, `ONBOARD-005`, `AGENT-011`, and new traceability rows `ONBOARD-007`, `ONBOARD-008` carry this decision.

## C-009 Agent API `/v1/info` After Pairing

| Field | Content |
|---|---|
| source docs | `Агент/Принцип работы агента ноды.md`; `ARCHITECTURE_INDEX.md`; `Агент/Установка mTLS соединения дашборд - агент.md` |
| competing interpretations | (A) `/v1/info` is public because it only returns version/features/limits. (B) `/v1/info` is a regular `/v1/*` endpoint and therefore protected by mTLS after pairing. |
| chosen interpretation | B. `/v1/info` is part of the regular post-pairing agent API surface and must require mTLS after pairing. |
| why | The agent note lists `/v1/info` in the regular API list and says that list is over established mTLS except bootstrap. The hard-stop list forbids making `/v1/info` public after pairing. |
| required tests | Prompt 08/16: `/v1/info` returns version/features/limits over mTLS; unpaired/plain HTTP access to post-pairing `/v1/info` is rejected. |

Impact:

- `AGENT-011`, `API-004`, and `MTLS-008` carry this decision.
