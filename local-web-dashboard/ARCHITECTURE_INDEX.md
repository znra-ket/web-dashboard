# ARCHITECTURE_INDEX.md

**Автор:** znra  
**Статус:** Черновик / implementation index  
**Дата:** 02.07.2026  
**Назначение:** сводный индекс текущей v1-архитектуры web-xray-dashboard

---

## Цель документа

Этот документ не заменяет тематические заметки. Он собирает текущую архитектуру в одну точку, чтобы перед реализацией было видно:

- какие инварианты считаются фундаментальными;
- какие таблицы входят в v1 core schema;
- какие HTTP endpoint'ы должен поддерживать агент;
- какие фоновые процессы есть на стороне дашборда;
- какие lifecycle-состояния имеет нода;
- какие решения считаются закрытыми для v1;
- какие вопросы сознательно оставлены на v2/после MVP.

Source of truth по деталям остаётся в отдельных заметках: CORE, агент, mTLS, онбординг, папки, триггеры, pipeline, удаление ноды и transactional boundaries.

---

## Фундаментальные инварианты

1. **Dashboard локальный, не SaaS.** Один инстанс дашборда управляется одним владельцем/командой.
2. **Одна нода принадлежит одной инсталляции дашборда.** Нода не должна одновременно управляться двумя разными дашбордами.
3. **Соединение всегда инициирует дашборд.** Агент никогда не открывает соединение к дашборду сам.
4. **После онбординга штатный транспорт — mTLS.** SSH используется только на этапе первичной установки агента.
5. **Агент — dumb executor.** Агент не знает имён скриптов, папок, pipeline, trigger-семантики и бизнес-логики.
6. **Скрипты на агенте хранятся по content hash.** Дашборд хранит `script.name → current_hash`, агент хранит только физические файлы по hash.
7. **`node_script` — desired-state, а не факт доставки.** Строка означает “скрипт должен быть доступен на ноде”. Физическая доставка может произойти лениво через `execute → 404 → upload → execute`.
8. **Физический мусор чистится через reconciliation.** Старые hash удаляются через `node_hash_gc`, а не через SQL-триггеры и не как обязательная часть локальной транзакции.
9. **mTLS-сертификат агента валиден для дашборда только вместе с активной `node`.** Успешная TLS-проверка недостаточна: fingerprint сертификата должен совпасть с активной записью в БД.
10. **Online-удаление ноды разрывает доверие агента к дашборду.** Даже “удалить только из дашборда” сначала выполняет `unpair`, если нода online.
11. **Offline-нода не блокирует локальные desired-state изменения.** Remote-долги создаются только если сущность остаётся активной в БД.
12. **Pipeline — orchestration на стороне дашборда.** Агент видит только последовательность обычных `execute`.

---

## Основные документы

| Документ | Роль |
|---|---|
| `web-xray-dashboard — Основной дизайн-документ.md` | CORE-инварианты, границы продукта, общий стек |
| `Онбординг ноды в дашборд.md` | Добавление новой ноды: SSH → bootstrap → mTLS → метрики |
| `Установка mTLS соединения дашборд - агент.md` | Bootstrap trust chain, CSR, сертификаты, fingerprint validation |
| `Принцип работы агента ноды.md` | Agent API, upload/execute/delete, лимиты, admin endpoints |
| `Архитектура папок и материализация связей.md` | `folder`, `folder_node`, `folder_script`, `node_script`, fan-out/revoke |
| `Триггеры запуска скриптов.md` | `trigger`, schedule/on_startup/manual-only, missed-run policy, last-run fields |
| `Пайплайны и их архитектура.md` | Pipeline definition/run model, step output mapping, archival deletion |
| `Удаление ноды из дашборда.md` | Local delete, `unpair`, full cleanup, offline deletion |
| `Transactional service boundaries.md` | Какие операции должны выполняться в одной БД-транзакции и что происходит после commit |

---

## Core tables v1

### Node / identity

- `node`
  - активная управляемая нода;
  - хранит адрес/метаданные/status;
  - содержит или связывается с mTLS identity.
- `node_mtls_identity` или поля на `node`
  - `agent_cert_fingerprint` как обязательный binding;
  - опционально `agent_public_key_fingerprint`, `agent_cert_serial`, `issued_at`, `expires_at`.
- `node_bootstrap_state`
  - временное состояние онбординга;
  - хранит status, expiry, token hash, но не raw token.

### Scripts / desired-state

- `script`
  - `name`, `content`, `current_hash`, timestamps;
  - дашборд владеет именем и содержимым.
- `node_script`
  - desired availability скрипта на ноде;
  - `trigger_id` nullable;
  - `folder_id` nullable;
  - минимальные last-run поля.
- `node_hash_gc`
  - очередь known-garbage physical cleanup;
  - создаётся после изменения desired-state, если hash больше не нужен активной ноде.

### Folders

- `folder`
- `folder_node`
- `folder_script`
  - v1: не более одного шаблонного `trigger_id` на пару `(folder_id, script_id)`;
  - правка шаблонного триггера не ретроактивна для уже материализованных `node_script`.

### Triggers

- `trigger`
  - `type IN ('schedule', 'on_startup')`;
  - `manual-only` не является строкой trigger, а выражается как `trigger_id IS NULL`.
- `trigger_schedule`
- `trigger_on_startup`

### Pipeline

- `pipeline`
  - `archived INTEGER NOT NULL DEFAULT 0`;
  - удаление pipeline с историей в v1 = archive, не hard delete.
- `pipeline_step`
- `pipeline_step_arg`
- `pipeline_run`
- `pipeline_run_step`

---

## Agent HTTP API v1

### Script API

```text
POST   /v1/scripts/upload
POST   /v1/scripts/execute
DELETE /v1/scripts/{hash}
GET    /v1/info
```

Ключевые свойства:

- upload принимает content и hash, агент проверяет соответствие;
- execute работает по hash, синхронно, с `request_id`;
- `DELETE /v1/scripts/{hash}` идемпотентен: отсутствие файла = успех;
- `GET /v1/info` возвращает version/features/limits.

### Admin lifecycle API

```text
POST /v1/admin/unpair
POST /v1/admin/uninstall
```

- `unpair` удаляет pairing-state и доверие агента к дашборду, но не обязан удалять скрипты/агента.
- `uninstall` включает `unpair` и физически удаляет компоненты web-xray-dashboard с VPS.
- Оба endpoint'а доступны только поверх действующего mTLS.

### Bootstrap API

```text
GET  /bootstrap/v1/status
GET  /bootstrap/v1/csr
POST /bootstrap/v1/certificate
```

- Используется только между SSH-установкой агента и успешным mTLS pairing.
- Требует `Authorization: Bootstrap <token>`.
- После successful pairing отключается или отвечает `410 bootstrap_closed`.

---

## Agent limits v1

| Параметр | Значение |
|---|---:|
| `max_script_upload_bytes` | 1 MiB |
| `max_agent_script_storage_bytes` | 64 MiB |
| `max_execute_body_bytes` | 128 KiB |
| `max_args_count` | 64 |
| `max_args_total_bytes` | 64 KiB |
| `max_env_count` | 64 |
| `max_env_total_bytes` | 64 KiB |
| `max_stdout_bytes` | 256 KiB |
| `max_stderr_bytes` | 256 KiB |
| `default_timeout_seconds` | 60 |
| `max_timeout_seconds` | 600 |
| `speedtest_timeout_seconds` | 180 |
| `max_concurrent_executions_global` | 2 |
| `max_concurrent_executions_per_hash` | 1 |
| `request_id_cache_ttl_seconds` | 3600 |
| `request_id_cache_max_entries` | 1024 |
| `max_processes_per_run` | 32 |
| `max_open_files_per_run` | 64 |
| `max_memory_bytes_per_run` | 256 MiB |
| `workdir_quota_bytes_per_run` | 64 MiB |
| `max_pipeline_steps` | 32 |

---

## Node lifecycle states v1

Строка `node` существует только для ноды, которую дашборд ещё считает частью своей локальной модели. Полностью удалённая нода обычно выражается отсутствием строки.

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

Рекомендуемое поле:

```sql
status TEXT NOT NULL CHECK (status IN (...))
```

Состояние `unpaired` — состояние агента на VPS, а не активной строки `node` в БД дашборда.

---

## Background / scheduled processes

- **Schedule trigger runner**
  - ищет due `node_script` с `trigger_schedule`;
  - пропущенные из-за выключенного backend срабатывания не догоняются;
  - next run планируется от текущего времени.
- **On-startup trigger runner**
  - при старте backend запускает `on_startup` связи;
  - не является pipeline.
- **Node hash GC reconciler**
  - обрабатывает `node_hash_gc` для active online nodes;
  - перед delete(hash) заново проверяет `desired_hashes(node)`.
- **Onboarding poller**
  - опрашивает bootstrap endpoint до CSR/TTL.
- **mTLS health/probe**
  - используется для проверки, что paired agent reachable.

---

## Решения, закрытые для v1

- CRL не используется.
- Bootstrap token: 32 random bytes, base64url, TTL 15 минут, absolute window 30 минут.
- Raw bootstrap-token не хранится в SQLite.
- Автоматическое продолжение bootstrap после падения дашборда не поддерживается.
- Missed schedule runs не догоняются.
- Pipeline deletion with history = `archived = 1`.
- Folder-level multiple triggers не поддерживаются в v1.
- Общая `script_run` история не является блокером v1.
- Pipeline history остаётся технической частью pipeline, а не общей observability-моделью.
- Offline active node получает pending GC; offline deleted node не получает pending cleanup.

---

## Намеренно оставлено на v2 / после MVP

- Полноценная история всех запусков (`script_run`).
- UI для подробного delivery-state по каждому hash на каждой ноде.
- Multiple folder-level triggers.
- Pipeline DAG/branch/merge.
- `env` mapping между шагами pipeline.
- `script.output_schema` для UI-конструктора pipeline.
- CRL/OCSP или распределённая PKI.
- Pending cleanup для удаляемой offline-ноды.
- Agent auto-update.
- Ротация dashboard CA при компрометации дашборда.
