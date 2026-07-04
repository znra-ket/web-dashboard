# Transactional service boundaries

**Автор:** znra  
**Статус:** Черновик / implementation boundary spec  
**Дата:** 02.07.2026  
**Ссылается на:** ARCHITECTURE_INDEX.md, CORE.md, Принцип_работы_агента_ноды.md, Архитектура_папок_и_материализация_связей.md, Триггеры_запуска_скриптов.md, Удаление_ноды_из_дашборда.md

---

## Контекст и охват

Эта заметка фиксирует границы транзакций для v1 backend. Цель — не смешивать локальную консистентность SQLite с сетевыми операциями на агентах.

Общее правило:

```text
Локальный desired-state меняется в одной SQLite-транзакции.
Remote-действия на агентах выполняются только после commit.
Если remote-действие не удалось, БД не откатывается автоматически; создаётся pending-состояние или показывается ошибка в зависимости от lifecycle-сценария.
```

SQL-триггеры используются только для локальной материализации/очистки внутри SQLite. Они не вызывают сеть, не создают HTTP-задачи и не принимают product-level решений.

---

## Типы действий

### Local transaction

Действия, которые должны быть атомарны:

- вставка/обновление/удаление строк SQLite;
- fan-out/revoke папок через SQL-триггеры;
- создание/замена trigger-сущностей;
- создание `node_hash_gc` после пересчёта desired-state;
- смена lifecycle status ноды.

### Post-commit reconciliation

Действия после успешного commit:

- `POST /v1/scripts/upload`;
- `POST /v1/scripts/execute`;
- `DELETE /v1/scripts/{hash}`;
- `POST /v1/admin/unpair`;
- `POST /v1/admin/uninstall`;
- bootstrap polling;
- mTLS probe.

### Pending work

Создаётся, когда remote-действие относится к активной сущности, но не может быть выполнено сейчас:

- `node_hash_gc` для active offline node;
- retry schedule для failed transient remote operations;
- onboarding status `failed_*`, если процесс требует ручного restart/repair.

Pending cleanup **не создаётся** для удалённой offline-ноды, потому что после `DELETE FROM node` нет активной сущности, к которой его можно привязать.

---

## Service operations

### `create_script(name, content)`

**Transaction:**

1. Посчитать `current_hash`.
2. Создать `script(name, content, current_hash)`.
3. Commit.

**After commit:**

- remote upload не обязателен;
- скрипт попадёт на ноду лениво при первом `execute`, если будет создана связь.

---

### `update_script_content(script_id, new_content)`

**Transaction:**

1. Считать `old_hash` и затронутые active `node_id` через `node_script`.
2. Посчитать `new_hash`.
3. Обновить `script.content/current_hash`.
4. Для каждой затронутой active ноды пересчитать `desired_hashes(node)`.
5. Если `old_hash` больше не desired для ноды — `INSERT OR IGNORE INTO node_hash_gc`.
6. Commit.

**After commit:**

- для online-нод можно best-effort загрузить `new_hash`;
- pending GC обрабатывается reconciler'ом;
- если upload не удался, обычный `execute → 404 → upload → execute` остаётся fallback.

---

### `delete_script(script_id)`

**Transaction:**

1. Считать `old_hash` и затронутые active `node_id`.
2. Удалить `script`.
3. Каскады удаляют `folder_script`, `node_script`, pipeline steps, если так задано схемой.
4. Cleanup-триггеры удаляют orphan triggers.
5. Для каждой затронутой active ноды пересчитать `desired_hashes(node)`.
6. Если `old_hash` больше не desired — создать `node_hash_gc`.
7. Commit.

**After commit:**

- online GC выполняется best-effort;
- offline active node остаётся с pending GC;
- отсутствие hash на агенте считается успешным GC.

---

### `add_node_to_folder(folder_id, node_id)`

**Transaction:**

1. `INSERT INTO folder_node`.
2. SQL-триггер создаёт materialized `node_script` строки.
3. Код приложения клонирует шаблонные triggers из `folder_script` в созданные `node_script`, если они есть.
4. Commit.

**After commit:**

- upload скриптов на ноду не обязателен;
- lazy execution flow доставит hash при первом запуске.

---

### `remove_node_from_folder(folder_id, node_id)`

**Transaction:**

1. Считать hash-и, которые могли стать ненужными этой ноде.
2. `DELETE FROM folder_node`.
3. SQL-триггер удаляет materialized `node_script` rows с этим `folder_id`.
4. Cleanup triggers удаляют orphan trigger rows.
5. Пересчитать `desired_hashes(node)`.
6. Для ненужных hash создать `node_hash_gc`.
7. Commit.

**After commit:**

- online GC best-effort;
- offline active node получает pending GC.

---

### `add_script_to_folder(folder_id, script_id, trigger_template?)`

**Transaction:**

1. Создать `folder_script`.
2. Если есть trigger template — создать `trigger` + subtype row и записать `folder_script.trigger_id`.
3. SQL-триггер создаёт materialized `node_script` для всех нод папки.
4. Код приложения клонирует trigger template в materialized rows.
5. Commit.

**After commit:**

- upload на online-ноды допускается как best-effort, но не обязателен.

---

### `remove_script_from_folder(folder_id, script_id)`

**Transaction:**

1. Считать затронутые active nodes и `old_hash`.
2. Удалить `folder_script`.
3. SQL-триггеры удаляют materialized `node_script`.
4. Cleanup-триггеры удаляют orphan triggers.
5. Пересчитать `desired_hashes(node)` для затронутых нод.
6. Создать `node_hash_gc`, если hash больше не desired.
7. Commit.

**After commit:**

- GC выполняется как обычный post-commit reconciliation.

---

### `set_node_script_trigger(node_script_id, trigger_config | NULL)`

**Transaction:**

1. Если старый `trigger_id` есть — заменить/обнулить ссылку через UPDATE владеющей строки.
2. Если новый trigger нужен — создать `trigger` + subtype row через application factory.
3. Cleanup SQL-триггер удалит старый orphan trigger, если на него больше нет ссылок.
4. Commit.

**After commit:**

- scheduler перечитывает активные trigger rows;
- remote-действий нет.

---

### `run_node_script(node_script_id, source)`

**Transaction before remote:**

1. Считать active node, script, current_hash, trigger/source metadata.
2. Сгенерировать `request_id` для нового логического запуска.
3. Commit/закрыть read transaction.

**Remote:**

1. `POST /v1/scripts/execute(hash, request_id, args, env)`.
2. Если агент вернул `404` — выполнить `upload(content)` и повторить execute с тем же `request_id`.

**Transaction after remote:**

1. Обновить minimal last-run поля на `node_script`.
2. Для schedule-trigger обновить next due по правилу v1.
3. Commit.

---

### `delete_node_local(node_id, force=False)`

**Если node online и force=False:** сначала выполнить `unpair` как отдельную remote-операцию. После успешного `unpair` — локальная транзакция удаления.

**Transaction:**

1. Пометить node как `deleting_local` или сразу удалить строку.
2. `DELETE FROM node`.
3. FK/SQL cleanup удаляют `folder_node`, `node_script`, orphan triggers, `node_hash_gc`.
4. Commit.

**After commit:**

- remote cleanup не создаётся;
- если нода была offline/force local delete, UI предупреждает о возможном оставшемся paired-agent.

---

### `delete_node_full(node_id)`

**Precondition:** node online, mTLS работает.

**Remote first:**

1. `POST /v1/admin/uninstall`.
2. Дождаться подтверждения.

**Transaction after success:**

1. `DELETE FROM node`.
2. FK/cleanup чистят локальное desired-state.
3. Commit.

Если remote uninstall не подтверждён, node не удаляется автоматически.

---

### `archive_pipeline(pipeline_id)`

**Transaction:**

1. `UPDATE pipeline SET archived = 1 WHERE id = :id`.
2. Commit.

`pipeline_run` остаётся читаемым. Hard delete pipeline с историей не является штатным v1-путём.

---

## Правило remote-after-commit

Ни один HTTP-запрос к агенту не должен выполняться внутри SQLite-транзакции. Это защищает от долгих блокировок БД, сетевых зависаний и состояний, где локальная транзакция откатывается после частично выполненной remote-операции.
