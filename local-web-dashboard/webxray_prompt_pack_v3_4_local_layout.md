# web-xray-dashboard — Prompt Pack v3.4 local-layout

**Статус:** v3.4 local-layout patch: v3.3 + адаптация путей под текущую структуру `local-web-dashboard/`, где `MASTER_SESSION_PROMPT.md` и prompt pack лежат в корне, а архитектурные заметки лежат в `Основное/`, `Агент/`, `Скрипты и папки/` и root-файлах.

Этот файл заменяет v2, v3, v3.1 и v3.2 как рабочий порядок промптов. Он сохраняет основную цепочку v2, но добавляет gate-подход: сначала requirement inventory и coverage matrix, потом код. Security/lifecycle gaps теперь считаются блокерами, а не допустимыми xfail/deferred пунктами.

Цель: пройти от пустого репозитория до рабочего backend/agent-фундамента так, чтобы агент не «покрыл заметки словами», а материализовал их в коде, тестах и проверяемых инвариантах.

Главный принцип: каждый промпт делает маленький контрактно-проверяемый слой. Нельзя переходить к следующему промпту, пока текущий не проходит тесты, acceptance criteria и phase-gate.

---

# Local project layout for this run

Этот файл адаптирован под текущую структуру проекта пользователя:

```text
local-web-dashboard/
  MASTER_SESSION_PROMPT.md
  webxray_prompt_pack_v3_4_local_layout.md
  ARCHITECTURE_INDEX.md
  Transactional service boundaries.md
  Основное/
    web-xray-dashboard — Основной дизайн-документ.md
    Онбординг ноды в дашборд.md
  Агент/
    Принцип работы агента ноды.md
    Установка mTLS соединения дашборд - агент.md
    Удаление ноды из дашборда.md
  Скрипты и папки/
    Архитектура папок и материализация связей.md
    Триггеры запуска скриптов.md
    Пайплайны и их архитектура.md
  Excalidraw/                 # reference diagrams only, not source of truth unless prompt says so
  implementation/             # создаётся Prompt 00/00A/00B/00C
  scripts/check_phase_gate.py # создаётся Prompt 00C
```

Правило для coding agent: **не пытайся искать `docs/architecture/` или `docs/prompts/`**. В этой версии source-of-truth paths — именно структура выше. Если пользователь позже перенесёт файлы в `docs/`, сначала обнови `DOC_SOURCE_MANIFEST.md` и этот prompt pack.

# Что изменено в v3 после ревизии v2

V2 был сильным, но всё ещё мог повторить старый сценарий: отдельные модули выглядят реализованными, а глобальная консистентность теряется между ними. Поэтому v3 добавляет обязательные предохранители:

1. **Requirement inventory до кода.** Перед реализацией модель должна извлечь требования из всех заметок в `TRACEABILITY.md`, назначить requirement_id и показать, каким будущим prompt/test это покрывается.
2. **Prompt coverage matrix.** Нельзя начинать код, пока нет таблицы `requirement_id -> prompt_id -> test_id/status`.
3. **Hard gates между фазами.** После каждой фазы аудит не просто “рекомендует”, а выдаёт `GO` или `NO-GO`. При `NO-GO` следующий phase prompt запрещён.
4. **No hidden xfail policy.** `xfail`, TODO, placeholder и documented gaps запрещены в security/lifecycle path: mTLS, fingerprint binding, executor safety, install/uninstall, deletion, GC, transaction boundaries.
5. **Cross-doc conflict check.** Если заметки противоречат друг другу, модель не должна молча выбирать удобный вариант. Она фиксирует конфликт в `implementation/CONFLICTS.md` и использует тематическую заметку как source of truth, если `ARCHITECTURE_INDEX.md` явно не закрывает решение.
6. **Real integration proof.** Для mTLS, AgentClient fingerprint binding, executor bounded output, install/uninstall и deletion flow нужны негативные тесты, которые доказывают, что неправильный путь невозможен.
7. **Per-prompt preflight.** Каждый prompt начинается с inspection: текущий git diff, релевантные docs, existing tests, прошлый audit status. Это снижает риск, что агент “забудет” контекст.

8. **v3.1 phase-gate scope.** `check_phase_gate.py` проверяет только требования, чей `phase_gate` уже достигнут. Требования будущих фаз могут оставаться `planned`, но обязаны иметь `prompt_id`, `expected_test_file` и назначенный `phase_gate`.
9. **v3.2 red-contract correction.** Только Prompt 09 остаётся RED CONTRACT prompt. Prompt 05 больше не имеет права оставлять failing tests в default suite; он создаёт transaction-boundary harness и passing dummy-service tests, а operation-specific checks добавляются в будущих prompts.
10. **v3.1 full mTLS identity lifecycle.** Dashboard client certificate/private key теперь является обязательной частью pairing, AgentClient и agent runtime auth, а не неявной деталью.
11. **v3.1 TLS identity policy.** Agent certificate policy должна либо использовать IP/DNS SAN с hostname verification, либо явно описанную CA validation + post-handshake fingerprint binding policy без `verify=False`.
12. **v3.1 DB-level pipeline materialization.** `INSERT pipeline_step` обязан материализовать `node_script` через SQLite trigger, и это проверяется direct SQL test.
13. **v3.1 SSH host key hardening.** Повторный SSH/repair flow использует сохранённый ed25519 fingerprint, mismatch aborts before password entry, automatic replacement запрещён.
14. **v3.1 bootstrap CSR readiness.** Bootstrap API явно покрывает `202 csr_not_ready`, последующий `200 csr_ready` и `410 bootstrap_closed`.
15. **v3.2 Prompt 05 fix.** Transaction-boundary guardrails больше не блокируют Phase 1 тестами на будущие сервисы; будущие операции фиксируются в `TRANSACTION_CONTRACT_PLAN.md`, а не failing tests.
16. **v3.2 upload hash conflict lock.** Prompt 07 обязан следовать выбранной интерпретации из `CONFLICTS.md`; если конфликт не resolved — `NO-GO`. Рекомендуемая интерпретация: agent считает hash от фактических bytes, client hash не является source of truth.
17. **v3.2 traceability enum.** Установлен единый enum статусов: `planned`, `implemented`, `tested`, `blocked`, `deferred_after_mvp`; алиасы `partial`, `untested`, `xfail`, `todo`, `later`, `covered_by_docs` запрещены.
18. **v3.2 folder trigger cloning hardening.** SQL fan-out не должен напрямую шарить `folder_script.trigger_id`; trigger templates клонируются application-code внутри той же SQLite transaction, по одному независимому trigger на materialized `node_script`.
19. **v3.2 fake mTLS test ban.** FastAPI TestClient/dependency overrides/app-level paired guards не считаются доказательством runtime mTLS. Нужен real TLS listener/socket и извлечение peer cert из actual TLS connection.
20. **v3.2 doc source manifest.** При дублях архитектурных документов агент создаёт `DOC_SOURCE_MANIFEST.md` с chosen path, size, sha256, modified time и причиной выбора.
21. **v3.2 MVP scope lock.** До Stage1/Stage3 должен быть явно решён MVP scope для Xray/components и metrics scripts; unresolved scope = `NO-GO`.
22. **v3.2 admin auth traceability split.** Prompt 12 может тестировать admin handler behavior, но transport-level mTLS protection для admin endpoints остаётся `planned` до Prompt 16.
23. **v3.4 multi-chat workflow.** Добавлен обязательный `MASTER_SESSION_PROMPT.md`: каждый новый чат с coding agent должен начинаться с него, затем выполняется ровно один конкретный prompt из pack’а. Это защищает от context rot и смешивания состояния между сессиями.

---

# Multi-chat workflow — обязательно для работы без context rot

Этот prompt pack рассчитан не только на один длинный чат, но и на серию независимых coding-agent сессий.

Перед запуском любого prompt из этого файла создай/добавь отдельный файл:

```text
MASTER_SESSION_PROMPT.md
```

Каждый новый чат с coding agent должен начинаться так:

```text
1. Вставить содержимое MASTER_SESSION_PROMPT.md.
2. Приложить/дать доступ к текущему репозиторию.
3. Убедиться, что в репозитории есть `ARCHITECTURE_INDEX.md`, `Transactional service boundaries.md`, `Основное/*.md`, `Агент/*.md`, `Скрипты и папки/*.md`. Если `implementation/*` ещё нет, его создадут Prompt 00/00A/00B/00C.
4. Вставить ровно один конкретный prompt из этого pack’а.
5. После выполнения сделать commit, если prompt получил GO.
6. В следующем чате снова начать с MASTER_SESSION_PROMPT.md.
```

Правило: `GLOBAL PROMPT` остаётся локальной шапкой конкретных prompts, но `MASTER_SESSION_PROMPT.md` задаёт правила всей chat-сессии. Если работа идёт в разных чатах, `MASTER_SESSION_PROMPT.md` обязателен.

`MASTER_SESSION_PROMPT.md` должен требовать от coding agent:

- восстановить контекст из файлов, а не из памяти прошлого чата;
- прочитать текущий prompt из `webxray_prompt_pack_v3_4_local_layout.md`;
- проверить `implementation/TRACEABILITY.md`, `implementation/PROMPT_COVERAGE.md`, `implementation/CONFLICTS.md`, `implementation/PHASE_GATES.md`;
- выполнять только один prompt за сессию;
- не переходить к следующему prompt самостоятельно;
- возвращать единый финальный отчёт с `GO/NO-GO` и recommended next prompt.

---

# Hard-stop правила

Агент обязан остановиться и не переходить дальше, если:

- не найдены архитектурные заметки;
- есть `NO-GO` по предыдущему phase audit;
- security/lifecycle requirement закрыт placeholder, TODO, fake, xfail или “later”;
- тесты зелёные только потому, что контракт ослаблен;
- endpoint существует, но не выведен через реальный router/API, когда prompt требует product/API layer;
- `/v1/*` агентского runtime можно поднять без реального mTLS guard;
- `AgentClient` может выполнить protected request без active-node fingerprint binding;
- есть HTTP к агенту внутри SQLite transaction;
- `node_hash_gc` создаётся SQL-триггерами, а не service-code после desired-state diff;
- pipeline step update не материализует новую `node_script` связь;
- executor читает stdout/stderr без bounded streaming.
- `AgentClient` использует `verify=False` или отключает TLS chain validation ради app-level fingerprint check;
- dashboard client certificate/private key lifecycle не реализован, но runtime mTLS считается готовым;
- `check_phase_gate.py` проверяет future-phase blocking requirements как уже обязательные для текущей фазы;
- RED CONTRACT tests из текущей фазы остались failing на phase audit.
- Prompt 05 оставляет failing pytest tests в default suite вместо passing transaction-boundary harness tests.

---


# RED CONTRACT PROMPTS

Некоторые prompts намеренно создают failing contract tests до реализации. Это не xfail/deferred и не ослабление security path.

RED CONTRACT prompts:
- Prompt 09 — executor contract tests before implementation.

Prompt 05 **не является RED CONTRACT** начиная с v3.2. Он обязан оставлять default pytest suite зелёным и проверять transaction-boundary harness на deliberately bad dummy service, а не создавать failing tests на будущие real services.

Правила:
- failing contract tests разрешены только если prompt явно помечен как RED CONTRACT;
- каждый failing test должен быть перечислен в финальном отчёте prompt'а;
- следующий implementation prompt обязан сделать эти tests pass;
- phase audit не может быть `GO`, пока red-contract tests этой фазы остаются failing;
- security/lifecycle `xfail`, placeholder или deferred всё равно запрещены.

---

# Reporting template после каждого prompt

В конце каждого prompt агент обязан вернуть:

```text
Prompt ID:
Changed files:
Added/updated tests:
Commands run:
Test result:
Requirement IDs covered:
Architecture invariants covered:
TRACEABILITY updates:
New risks / deferred items:
Hard-stop violations found:
GO/NO-GO for next prompt:
```

Если `GO/NO-GO` не указан, считай prompt незавершённым.

---

## Как использовать

1. Убедись, что архитектурные заметки уже лежат в текущей структуре проекта: root-файлы `ARCHITECTURE_INDEX.md`, `Transactional service boundaries.md`, а также папки `Основное/`, `Агент/`, `Скрипты и папки/`.
2. Положи prompt-файлы в корень `local-web-dashboard/`:
   - `MASTER_SESSION_PROMPT.md`
   - `webxray_prompt_pack_v3_4_local_layout.md`
3. Каждый новый чат с coding agent начинай с `MASTER_SESSION_PROMPT.md`.
4. После master prompt давай агенту ровно один prompt из этого файла и требуй выполнение только его.
5. После каждого prompt’а требуй:
   - список изменённых файлов;
   - список добавленных тестов;
   - команды, которые были запущены;
   - что осталось не сделано;
   - какие архитектурные инварианты покрыты тестами;
   - `GO/NO-GO for next prompt`.
6. Делай commit после каждого зелёного этапа.
7. Контрольные audit-промпты запускай после каждой крупной фазы.

---

# GLOBAL PROMPT — вставлять в начало каждого промпта

```text
Ты работаешь над проектом web-xray-dashboard.

Перед любым кодом:
1. Найди и прочитай релевантные архитектурные файлы в текущей структуре проекта: `ARCHITECTURE_INDEX.md`, `Transactional service boundaries.md`, `Основное/`, `Агент/`, `Скрипты и папки/`.
2. Найди существующие implementation-файлы и тесты.
3. Не придумывай архитектуру заново, если она уже зафиксирована в заметках.
4. Если код и заметки конфликтуют, приоритет у заметок, но явно укажи конфликт.
5. Не делай unrelated refactor.
6. Не создавай placeholder-реализации под видом готового функционала.
7. Не выполняй HTTP-запросы к агенту внутри SQLite-транзакций.
8. Агент никогда не должен инициировать соединение к dashboard.
9. После pairing все `/v1/*` и `/v1/admin/*` endpoint'ы агента доступны только через mTLS.
10. Dashboard обязан сверять agent certificate fingerprint с active `node` перед каждым штатным request.
11. `node_script` — desired-state, а не факт доставки байт на агент.
12. Агент — dumb executor: он не знает script names, folders, triggers, pipelines или бизнес-логику dashboard.
13. Скрипты на агенте хранятся только по content hash.
14. Все лимиты v1 обязательны, а не advisory.

Рабочий стиль:
- Сначала сделай preflight: прочитай релевантные docs, existing code/tests, `TRACEABILITY.md`, прошлый phase audit и текущий git diff.
- Сначала напиши/обнови тесты, которые фиксируют контракт.
- Потом реализуй минимальный код, чтобы эти тесты прошли.
- После реализации запусти релевантные тесты.
- В финальном отчёте напиши: changed files, tests added/updated, commands run, architecture invariants covered, remaining gaps.
- Если полноценная реализация невозможна в текущей среде, не делай fake-success. Для обычной non-critical feature можно оставить явный failing test и documented gap. Для security/lifecycle/foundation path (`mTLS`, fingerprint binding, executor limits, install/uninstall, deletion, GC, transaction boundaries, bootstrap token secrecy) xfail/deferred запрещены: верни `NO-GO`, объясни блокер и не переходи дальше.
```

---

# PHASE 0 — Architectural ingestion and guardrails

## Prompt 00 — Подготовь репозиторий и архитектурные документы

```text
[GLOBAL PROMPT]

Задача: подготовить проект к реализации с архитектурными guardrails под текущую локальную структуру проекта.

Сделай:
1. Не создавай `docs/architecture/` и `docs/prompts/`. Используй уже существующую структуру проекта. Создай только `implementation/`, если её ещё нет.
2. Убедись, что в корне проекта лежат:
   - `MASTER_SESSION_PROMPT.md`
   - `webxray_prompt_pack_v3_4_local_layout.md`
3. Убедись, что в репозитории лежат все текущие заметки по ожидаемым путям:
   - `ARCHITECTURE_INDEX.md`
   - `Transactional service boundaries.md`
   - `Основное/web-xray-dashboard — Основной дизайн-документ.md`
   - `Основное/Онбординг ноды в дашборд.md`
   - `Агент/Установка mTLS соединения дашборд - агент.md`
   - `Агент/Принцип работы агента ноды.md`
   - `Агент/Удаление ноды из дашборда.md`
   - `Скрипты и папки/Архитектура папок и материализация связей.md`
   - `Скрипты и папки/Триггеры запуска скриптов.md`
   - `Скрипты и папки/Пайплайны и их архитектура.md`
   - `AUDIT_2026-07-03.md`, если он доступен из прошлой попытки.
4. Если есть несколько файлов с одним и тем же архитектурным названием, не угадывай и не смешивай версии. Создай `implementation/DOC_SOURCE_MANIFEST.md` с:
   - chosen source path;
   - file size;
   - sha256;
   - modified time, если доступен;
   - reason this version was chosen.
   Prefer files in the current local layout for this run: root files plus `Основное/`, `Агент/`, `Скрипты и папки/`. Do not mix older File Library versions unless user explicitly requests it. If duplicate current docs conflict, return `NO-GO`.
5. Создай `implementation/README.md` с кратким описанием того, что код должен следовать этим заметкам.
6. Создай `implementation/INVARIANTS.md` и выпиши туда фундаментальные инварианты из `ARCHITECTURE_INDEX.md`.
7. Создай `implementation/TRACEABILITY.md` с обязательными колонками:
   - requirement_id
   - source_doc
   - requirement
   - criticality: blocking / normal / after_mvp
   - prompt_id
   - phase_gate
   - implementation_files_expected
   - test_files_expected
   - implementation_files_actual
   - test_files_actual
   - status: planned / implemented / tested / blocked / deferred_after_mvp
   - evidence

Пока не реализуй backend logic. Это только подготовительный слой.

Acceptance criteria:
- Все документы перечислены и доступны по фактическим путям текущей структуры.
- Есть initial traceability matrix.
- Есть invariant list.
- Нет кода backend/agent, кроме служебных implementation-docs.
```

## Prompt 00A — Requirement inventory без кода

```text
[GLOBAL PROMPT]

Задача: до любой реализации извлечь формальную матрицу требований из всех архитектурных заметок.

Единый enum статусов требований:
- allowed: `planned`, `implemented`, `tested`, `blocked`, `deferred_after_mvp`;
- forbidden aliases: `partial`, `untested`, `xfail`, `todo`, `later`, `covered_by_docs`.

Обязательные колонки TRACEABILITY:
- `requirement_id`;
- `source_doc`;
- `requirement`;
- `criticality: blocking / normal / after_mvp`;
- `prompt_id`;
- `phase_gate`;
- `implementation_files_expected`;
- `test_files_expected`;
- `implementation_files_actual`;
- `test_files_actual`;
- `status`;
- `evidence`.

Сделай:
1. Прочитай все архитектурные файлы в текущей структуре проекта: root-файлы `ARCHITECTURE_INDEX.md`, `Transactional service boundaries.md`, а также папки `Основное/`, `Агент/`, `Скрипты и папки/`.
2. Создай/обнови `implementation/TRACEABILITY.md` так, чтобы каждое требование имело:
   - `requirement_id` в формате `CORE-001`, `MTLS-001`, `AGENT-001`, `ONBOARD-001`, `FOLDER-001`, `TRIGGER-001`, `PIPE-001`, `DELETE-001`, `TX-001`, `API-001`;
   - source document;
   - `criticality: blocking / normal / after_mvp`;
   - expected implementation files;
   - expected tests;
   - prompt_id, который должен закрыть требование;
   - phase_gate, на котором требование обязано стать `tested`;
   - status: planned / implemented / tested / blocked / deferred_after_mvp.
3. Отдельно создай `implementation/PROMPT_COVERAGE.md` с таблицей:
   - requirement_id;
   - prompt_id;
   - test_id/test_file;
   - phase gate;
   - current status.
4. Создай `implementation/BLOCKING_REQUIREMENTS.md` со списком требований, которые нельзя закрыть placeholder/xfail/deferred. Минимум: runtime mTLS, fingerprint binding, bounded executor, request body guards, real install/uninstall plan, deletion lifecycle, GC ownership, transaction boundaries.
5. Если `AUDIT_2026-07-03.md` доступен, каждое known failed area из него должно стать blocking requirement. Если audit-файл недоступен, используй встроенный fallback-list:
   - real mTLS runtime enforcement;
   - per-request fingerprint binding;
   - real SSH install;
   - real uninstall;
   - bounded executor output;
   - fd/fexecve or equivalent;
   - no SQL-trigger-owned node_hash_gc;
   - pipeline update materialization;
   - max_pipeline_steps;
   - missing backend routers;
   - background workers integrated.

Запрещено:
- Писать application code.
- Придумывать требования, которых нет в заметках.
- Оставлять “в целом покрыто” без конкретного requirement_id.

Acceptance criteria:
- Каждое фундаментальное требование из `ARCHITECTURE_INDEX.md` имеет requirement_id.
- Каждое known failed area из `AUDIT_2026-07-03.md` имеет blocking requirement.
- Есть явная связь `requirement -> prompt -> test`.
- Если coverage неполный, финальный статус `NO-GO` для Prompt 01.
```

## Prompt 00B — Cross-doc conflict audit

```text
[GLOBAL PROMPT]

Задача: найти противоречия между архитектурными заметками до начала кода.

Проверь минимум:
1. Agent upload contract: client-supplied hash ignored vs checked for consistency.
2. `node_hash_gc`: кто создаёт queue — SQL trigger или service-code после desired diff.
3. `folder_id` FK behavior: RESTRICT/application-controlled vs accidental cascade.
4. Pipeline history: snapshot-only vs FK `ON DELETE SET NULL`.
5. mTLS responsibility: server-level TLS/client-cert auth vs app-level paired-state guard.
6. Bootstrap close semantics: when exactly token/state is destroyed on both sides.
7. Schedule missed-run policy: skipped, not replayed.
8. MVP scope for Xray/components and metrics scripts:
   - Are `xray_status`, `detect_stack`, `speedtest` required as real MVP scripts?
   - Is Xray installation part of Stage1 MVP?
   - If any part is deferred, update architecture source files in the current local layout explicitly before implementation.

Сделай:
- Создай `implementation/CONFLICTS.md`.
- Для каждого конфликта укажи:
  - source docs;
  - competing interpretations;
  - chosen interpretation;
  - why;
  - required tests.

Правило выбора:
- Если `ARCHITECTURE_INDEX.md` явно закрывает решение — следуй ему.
- Если index только суммирует, а тематическая заметка детальнее — следуй тематической заметке.
- Если невозможно выбрать без продуктового решения — `NO-GO`, не кодить.
- Для upload hash behavior выбранная интерпретация в `CONFLICTS.md` обязательна для Prompt 07. Если конфликт не resolved, Prompt 07 обязан вернуть `NO-GO`, а не выбирать локально.

Acceptance criteria:
- Нет молчаливых архитектурных развилок.
- Все выбранные интерпретации отражены в `TRACEABILITY.md`.
```

## Prompt 00C — Phase gate harness и no-go enforcement

```text
[GLOBAL PROMPT]

Задача: добавить в репозиторий процессные guardrails, которые будут мешать переходить дальше при незакрытом фундаменте.

Сделай:
1. Создай `implementation/PHASE_GATES.md` с gate criteria для каждой фазы.
2. Создай `scripts/check_phase_gate.py` или простой test/helper, который читает `TRACEABILITY.md`/`PROMPT_COVERAGE.md` и принимает CLI-аргумент текущей фазы:
   - `python scripts/check_phase_gate.py --phase phase_0`
   - `python scripts/check_phase_gate.py --phase phase_1`
   - `python scripts/check_phase_gate.py --phase phase_2`
   - и так далее.
3. Скрипт должен проверять только requirements, чей `phase_gate` <= current phase gate. Blocking requirements будущих фаз могут оставаться `planned`, но обязаны иметь `prompt_id`, `expected_test_file` и `phase_gate`.
4. Добавь CI/test command, который запускается после phase audit с конкретной фазой.
5. Добавь правило: security/lifecycle blocking requirement не может иметь status `deferred_after_mvp`, `xfail`, `partial` или `untested`, когда его phase gate уже достигнут.
6. Скрипт должен валидировать единый status enum и падать на forbidden aliases: `partial`, `untested`, `xfail`, `todo`, `later`, `covered_by_docs`.
7. Скрипт должен требовать обязательные колонки TRACEABILITY из Prompt 00A.

Acceptance criteria:
- Можно автоматически получить `GO`/`NO-GO` для конкретной фазы, не блокируя future-phase requirements раньше времени.
- Нельзя случайно продолжить после failed audit без emergency repair prompt.
```

## Prompt 01 — Инициализация mono-repo и test harness

```text
[GLOBAL PROMPT]

Задача: создать минимальный mono-repo skeleton для backend и agent без бизнес-логики.

Предпочтительный стек из заметок:
- Python 3.12
- FastAPI backend
- FastAPI agent
- SQLite + SQLAlchemy asyncio + aiosqlite
- APScheduler
- httpx
- asyncssh
- cryptography
- pytest

Сделай:
1. Создай структуру:
   - `backend/app/...`
   - `backend/tests/...`
   - `agent/webxray_agent/...`
   - `agent/tests/...`
   - `scripts/`
   - `implementation/`
2. Настрой `pyproject.toml` или несколько package configs так, чтобы тесты запускались локально.
3. Добавь минимальные health endpoints:
   - backend: `GET /health`
   - agent bootstrap app: `GET /bootstrap/v1/status`, пока возвращает controlled unpaired/bootstrap state.
4. Добавь negative assertion: runtime `/v1/*` app не экспортируется как plain ASGI production app и не может быть случайно mounted без mTLS context.
5. Добавь smoke tests на импорт приложений и health.
6. Добавь `README.md` с командами запуска тестов.

Запрещено:
- Реализовывать mTLS fake-auth.
- Делать `/v1/scripts/*` доступным без будущего mTLS guard.
- Закладывать SaaS/multitenant модель.

Acceptance criteria:
- `pytest backend/tests agent/tests` проходит.
- Нет бизнес-placeholder'ов, которые выглядят как готовый функционал.
```

## Prompt 02 — Architecture manifest в коде

```text
[GLOBAL PROMPT]

Задача: превратить ключевые архитектурные решения в machine-readable manifest.

Сделай:
1. Создай `backend/app/architecture/constants.py` или аналогичный модуль.
2. Зафиксируй там:
   - node lifecycle states v1;
   - agent limits v1;
   - max_pipeline_steps = 32;
   - trigger types: schedule, on_startup;
   - bootstrap token TTL 15m и absolute window 30m;
   - список agent features v1.
3. Создай тесты, которые проверяют, что эти значения соответствуют `implementation/INVARIANTS.md` и используются из одного источника.
4. Обнови `TRACEABILITY.md` для этих constants.

Acceptance criteria:
- Нет дублирования magic numbers в будущих модулях.
- Все лимиты и lifecycle states имеют тесты.
```

---

# PHASE 1 — Database schema and transaction boundaries

## Prompt 03 — Core SQLite schema + migrations

```text
[GLOBAL PROMPT]

Задача: реализовать v1 core schema строго по `ARCHITECTURE_INDEX.md`, без remote logic.

Сделай миграции и модели для:
1. Node / identity:
   - `node`
   - `node_mtls_identity` или поля на `node`, но обязательно с `agent_cert_fingerprint` binding
   - `node_bootstrap_state`, где хранится token hash/expiry/status, но не raw token
2. Scripts / desired-state:
   - `script(name, content, current_hash, timestamps)`
   - `node_script(folder_id nullable, trigger_id nullable, minimal last-run fields)`
   - `node_hash_gc`
3. Folders:
   - `folder`
   - `folder_node`
   - `folder_script`
   - `node_script.folder_id` behavior must match folder note: application-controlled folder deletion, not accidental blind cascade unless explicitly documented in `CONFLICTS.md`.
4. Triggers:
   - `trigger(type CHECK schedule/on_startup)`
   - `trigger_schedule`
   - `trigger_on_startup`
5. Pipeline:
   - `pipeline(archived default 0)`
   - `pipeline_step`
   - `pipeline_step_arg`
   - `pipeline_run`
   - `pipeline_run_step` with snapshot fields and nullable `step_id`; prefer FK `ON DELETE SET NULL` unless `CONFLICTS.md` documents a deliberate snapshot-only deviation.

Требования:
- Включи SQLite foreign_keys.
- Добавь partial unique indexes для `node_script` manual/no-trigger и manual/with-trigger semantics.
- `manual-only` не должен быть строкой в `trigger`.
- `node_hash_gc` не должен создаваться SQL-триггерами автоматически. Очередь создаёт service-code после desired-state diff.

Tests:
- migration applies on empty DB;
- foreign keys work;
- partial unique indexes behave correctly;
- manual-only = `trigger_id IS NULL`;
- invalid trigger type rejected;
- lifecycle status CHECK works;
- max_pipeline_steps constant exists, даже если enforce будет позже.

Acceptance criteria:
- Все schema tests проходят.
- Нет сетевых операций в миграциях или SQL-триггерах.
- `node_hash_gc` ownership доказан тестом: SQL trigger сам его не создаёт.
```

## Prompt 04 — SQL triggers для folder materialization и trigger cleanup

```text
[GLOBAL PROMPT]

Задача: реализовать только локальную SQLite-материализацию папок и cleanup orphan triggers.

Сделай:
1. SQL triggers для fan-out/revoke по `folder_node` и `folder_script`:
   - добавление node в folder создаёт `node_script` для scripts folder;
   - добавление script в folder создаёт `node_script` для nodes folder;
   - удаление membership удаляет именно materialized rows с этим `folder_id`.
2. Cleanup SQL triggers для orphan `trigger` rows, когда последний reference исчезает или заменяется.
3. Не делай клонирование trigger config в чистом SQL, если архитектура требует app transaction factory.
4. SQL fan-out trigger must not copy `folder_script.trigger_id` directly into `node_script.trigger_id` as a shared trigger. If `folder_script` has a trigger template, service code must clone `trigger` + subtype row per materialized `node_script` inside the same SQLite transaction.
5. Не создавай `node_hash_gc` из SQL triggers.

Tests:
- folder fan-out works;
- folder revoke works;
- manual node_script rows не удаляются при удалении folder membership;
- orphan trigger cleanup works;
- two materialized `node_script` rows from one folder_script do not share the same `trigger_id`;
- editing one materialized trigger does not affect another;
- editing folder template is not retroactive;
- никакой SQL trigger не создаёт remote work и не меняет product-level decisions.

Acceptance criteria:
- Локальная консистентность обеспечивается SQL.
- Всё, что требует пользовательского выбора или desired-state diff, остаётся в service layer.
```

## Prompt 05 — Transaction boundary test harness

```text
[GLOBAL PROMPT]

Prompt 05 is NOT a RED CONTRACT prompt. It is not allowed to leave failing pytest tests in the default suite.

Задача: создать инфраструктуру, которая не даст случайно вызывать агента внутри SQLite transaction, не блокируя Phase 1 тестами на будущие сервисы.

Сделай:
1. Введи service transaction helper / unit-of-work для backend.
2. Введи runtime marker/contextvar или session wrapper, по которому тесты могут доказать, что remote call был post-commit, а не просто “после await”.
3. Введи тестовый fake AgentClient, который падает, если его вызывают внутри active DB transaction.
4. Добавь passing tests на deliberately bad dummy service, который вызывает AgentClient внутри active DB transaction, и докажи, что helper это ловит.
5. Добавь passing tests на deliberately good dummy service, который делает remote call only after commit.
6. Создай `implementation/TRANSACTION_CONTRACT_PLAN.md` со списком будущих операций, которые обязаны использовать этот helper:
   - Prompt 23: `update_script_content`, `delete_script`;
   - Prompt 25: `run_node_script`;
   - Prompt 26: folder membership operations;
   - Prompt 33: `delete_node_local/full`;
   - Prompt 34: GC reconciliation.
7. Не добавляй failing tests для будущих real services до появления этих services. Operation-specific no-HTTP-inside-transaction tests должны появиться в соответствующих implementation prompts.

Acceptance criteria:
- Default pytest suite stays green after Prompt 05.
- Есть reusable test helper, который ловит нарушение `remote-after-commit`.
- Есть `TRANSACTION_CONTRACT_PLAN.md`, связанный с Transactional service boundaries.
- В `TRACEABILITY.md` transaction-boundary requirements остаются `planned` или `implemented`, но не `tested` для future services до соответствующих prompts.
```

# PHASE 2 — Agent foundation

## Prompt 06 — Agent config, state files, permissions

```text
[GLOBAL PROMPT]

Задача: реализовать agent local state/config layer без execute.

Сделай:
1. Agent config paths:
   - install root
   - config dir
   - pairing state dir
   - script storage dir
   - workdir root
   - logs dir
2. Secure file writes:
   - private keys/state secrets: mode 0600
   - directories: restrictive permissions
   - atomic write через temp + rename
3. Agent states:
   - bootstrap_pending
   - paired
   - unpaired
4. Раздели bootstrap app и runtime `/v1/*` app на уровне factory/functions.
5. Не экспортируй plain runtime app так, чтобы его можно было случайно поднять без mTLS.

Tests:
- state transitions persisted;
- permissions on sensitive files;
- bootstrap app существует отдельно;
- runtime app factory requires explicit paired/mTLS context;
- no raw bootstrap token persisted.

Acceptance criteria:
- Нельзя случайно получить paired `/v1/*` через plain ASGI import без guard.
```

## Prompt 07 — Agent script storage by content hash

```text
[GLOBAL PROMPT]

Задача: реализовать storage layer скриптов на агенте.

Перед реализацией:
- Прочитай `implementation/CONFLICTS.md`.
- Для upload hash behavior используй только выбранную интерпретацию из `CONFLICTS.md`.
- Если `CONFLICTS.md` не resolved конфликт `client-supplied hash ignored vs checked`, верни `NO-GO` и не реализуй storage/API.

Контракт:
- Агент хранит скрипты только по content hash.
- Dashboard names ignored by agent.
- Hash считается агентом от фактически полученных bytes.
- Если client передал hash, поведение строго следует `CONFLICTS.md`; агент никогда не доверяет client hash как source of truth. Рекомендуемая интерпретация из агентской заметки: hash всегда считается агентом от фактически полученных bytes, client hash игнорируется или вообще не принимается в контракте.
- Storage quota: 64 MiB.
- Upload limit: 1 MiB.
- Atomic write.
- No symlink attack assumption: dir writable only by agent process, но всё равно не следовать symlink при опасных операциях.

Сделай:
1. `store_script(content) -> hash`.
2. `has_script(hash)`.
3. `delete_script(hash)` idempotent.
4. Quota checks.

Tests:
- same content -> same hash;
- hash from actual bytes;
- upload over 1 MiB rejected;
- storage quota enforced;
- delete missing hash succeeds;
- path traversal hash rejected;
- если `CONFLICTS.md` выбрал ignored behavior: wrong client hash does not affect returned actual hash;
- если `CONFLICTS.md` выбрал checked behavior: wrong client hash returns 409/422 and nothing is stored.
```

## Prompt 08 — Agent API: upload/delete/info body guards

```text
[GLOBAL PROMPT]

Задача: реализовать agent HTTP API без execute, но с правильными request-size guards.

Endpoint'ы:
- `POST /v1/scripts/upload`
- `DELETE /v1/scripts/{hash}`
- `GET /v1/info`

Требования:
- Эти endpoints должны быть доступны только через runtime app, который в реальной эксплуатации будет под mTLS.
- Request body size должен отсеиваться до Pydantic/full parse, насколько возможно в FastAPI/ASGI.
- `GET /v1/info` возвращает version/features/limits.
- `DELETE` idempotent.

Tests:
- upload happy path;
- upload over limit -> 413;
- delete existing/missing -> success;
- info includes all limits;
- unpaired runtime rejects `/v1/*`;
- plain bootstrap app не содержит `/v1/scripts/*`.
```

## Prompt 09 — Agent executor tests first

```text
[GLOBAL PROMPT]

RED CONTRACT PROMPT. На этом шаге нужно создать failing tests, которые выражают executor contract; Prompt 10 обязан сделать их pass. Эти tests не являются xfail/deferred.

Задача: написать contract tests для executor до реализации.

Покрой тестами:
1. Execute by content hash only.
2. Missing hash -> 404 at API/service boundary.
3. Args/env limits:
   - max args count 64
   - max single arg 16 KiB
   - max args total 64 KiB
   - max env count 64
   - max env key 128 bytes
   - max env value 16 KiB
   - max env total 64 KiB
4. Timeout:
   - default 60
   - max 600
   - SIGTERM then 5s grace then SIGKILL process group.
5. Concurrency:
   - global max 2
   - per-hash max 1
   - excess -> 429, not queued silently.
6. stdout/stderr:
   - concurrent bounded readers;
   - stdout >256 KiB -> failed-result `stdout_limit_exceeded`;
   - stderr >256 KiB truncated with flag;
   - no unbounded `communicate()` style buffering.
7. Workdir:
   - per-run workdir;
   - cleanup after success/failure;
   - quota 64 MiB.
8. Resource limits:
   - max processes 32;
   - max open files 64;
   - max memory 256 MiB.
9. Path race:
   - deleting script while running does not affect already-running process.

Если fd/fexecve невозможно реализовать сейчас, это `NO-GO` для agent executor phase, пока архитектурная заметка явно не изменена. Для текущего контракта тест должен фиксировать expected Linux behavior и реализация должна использовать fd-based/equivalent path.

Acceptance criteria:
- На этом шаге можно иметь failing tests, но каждый failing test должен быть перечислен в финальном отчёте.
- Не реализуй executor, пока tests не выражают контракт.
- Phase 2 Audit B не может быть `GO`, если хотя бы один Prompt 09 red-contract test остаётся failing после Prompt 10.
```

## Prompt 10 — Agent executor implementation

```text
[GLOBAL PROMPT]

Задача: реализовать executor так, чтобы прошли tests из Prompt 09.

Сделай:
1. Bounded concurrent stream readers для stdout/stderr.
2. Process group management.
3. Timeout SIGTERM -> grace -> SIGKILL.
4. Concurrency limiter global/per-hash.
5. request validation before execution.
6. Per-run workdir and cleanup.
7. Resource limits via safest available Linux mechanism for current stack.
8. fd/fexecve-like execution or documented equivalent that closes execute/delete race.
9. Refuse to run as root unless explicitly in test mode or install guarantees non-root.

Запрещено:
- `process.communicate()` с последующей проверкой размера.
- Shell execution.
- Path-based execution that reopens script after desired delete race unless architecture explicitly changed and tests reflect it.

Acceptance criteria:
- Agent executor tests pass.
- Все Prompt 09 red-contract tests pass; если любой остаётся failing, Phase 2 Audit B = `NO-GO`.
- Long-running writer cannot DoS memory.
- Delete during run does not break running execution.
```

## Prompt 11 — Agent execute endpoint + request_id idempotency

```text
[GLOBAL PROMPT]

Задача: добавить `POST /v1/scripts/execute` поверх executor.

Контракт:
- Execute synchronous.
- Input: hash, request_id, args, env, timeout.
- Missing hash -> 404.
- Same request_id + same body/hash fingerprint returns cached result within TTL.
- Same request_id + different fingerprint -> conflict.
- request_id cache TTL 3600s, max entries 1024.
- Execute body over 128 KiB -> 413 before full parse if possible.

Tests:
- happy path;
- missing hash;
- idempotent replay;
- request_id conflict;
- cache eviction/TTL;
- body size limit;
- stdout/stderr/timeout result shape matches contract.
```

## Prompt 12 — Agent admin lifecycle: unpair and uninstall

```text
[GLOBAL PROMPT]

Traceability split:
- Prompt 12 may mark admin handler behavior as tested.
- Transport-level mTLS protection for admin endpoints remains `planned` until Prompt 16 and must not be marked `tested` here.

Задача: реализовать admin lifecycle endpoints агента.

Endpoint'ы:
- `POST /v1/admin/unpair`
- `POST /v1/admin/uninstall`

Контракт:
- Доступны только в штатном runtime поверх mTLS.
- `unpair` удаляет local trust к dashboard: trust anchor/CA/pinned cert, agent cert, private key, pairing state. Не обязан удалять scripts/agent binary.
- `uninstall` включает unpair и физически удаляет компоненты web-xray-dashboard: service/unit, install root, config, keys, scripts, workdir, logs, temp files, optional agent user if safe.
- Реализация должна иметь cleanup plan/dry-run mode для тестов, whitelist owned roots и защиту от удаления вне install root.
- Если self-delete невозможен прямо из процесса, реализуй helper/systemd-run pattern или explicit pending self-uninstall mechanism. Не делай fake deletion.

Tests:
- unpair clears pairing state and runtime refuses further commands;
- uninstall invokes cleanup plan for all owned paths;
- idempotent behavior where safe;
- no deletion outside configured owned roots;
- endpoint unavailable on bootstrap app/plain app.
```

---

# PHASE 3 — Bootstrap and real mTLS

## Prompt 13 — Backend bootstrap token service

```text
[GLOBAL PROMPT]

Задача: реализовать backend bootstrap token service.

Контракт:
- Token = 32 random bytes CSPRNG, base64url.
- Raw token never stored in SQLite.
- DB stores hash, expiry, status, node_id/onboarding context.
- TTL 15 minutes.
- Absolute bootstrap window 30 minutes.
- Token exists only between SSH stage1 and successful mTLS pairing.

Сделай:
1. Generate token.
2. Hash token.
3. Validate token hash/expiry/status.
4. Invalidate token after success/failure/timeout.
5. Tests for raw token not persisted.

Acceptance criteria:
- Security tests prove raw token is not in DB/loggable state.
```

## Prompt 14 — Agent bootstrap API: status/csr/certificate

```text
[GLOBAL PROMPT]

Задача: реализовать bootstrap API агента.

Endpoint'ы:
- `GET /bootstrap/v1/status`
- `GET /bootstrap/v1/csr`
- `POST /bootstrap/v1/certificate`

Контракт:
- Только bootstrap-token auth: `Authorization: Bootstrap <token>`.
- Token сравнивается по hash, raw не хранится.
- CSR генерируется на агенте; private key stays local.
- После successful certificate install bootstrap закрывается: endpoints disabled или `410 bootstrap_closed`.
- Bootstrap API не пересекается со штатным `/v1/scripts/*` API.

Tests:
- no token rejected;
- wrong token rejected;
- expired token rejected;
- CSR not ready returns `202 csr_not_ready` / `status=csr_not_ready`;
- later CSR ready returns `200 csr_ready` with CSR;
- certificate install transitions to paired;
- after successful pairing bootstrap returns `410 bootstrap_closed`;
- bootstrap closes after success;
- `/v1/*` not available through bootstrap app.
```

## Prompt 15 — Dashboard CA and cert signing service

```text
[GLOBAL PROMPT]

Задача: реализовать локальный dashboard CA service.

Контракт:
- Dashboard локальный, не SaaS; CA принадлежит одной installation.
- CA private key хранится локально с mode 0600 и защищёнными directory perms.
- Подписывает agent CSR.
- Создаёт или загружает dashboard client certificate/private key для outbound AgentClient.
- Dashboard client private key хранится с mode 0600 и не логируется.
- Сохраняет cert fingerprint/serial/public key fingerprint для binding к active node.
- Удаление node убирает application trust без CRL.
- Определи agent certificate identity policy:
  - либо include node IP/DNS in certificate SAN and keep hostname verification enabled;
  - либо explicitly use CA validation plus post-handshake fingerprint binding without disabling certificate validation.
- Запрещено использовать `verify=False` или отключать TLS validation, заменяя её только app-level fingerprint check.

Tests:
- CA created once and reused;
- private key perms 0600;
- dashboard client cert/key created once and reused;
- dashboard client private key perms 0600;
- cert signed from CSR;
- certificate SAN/policy matches chosen identity policy;
- fingerprint computed consistently;
- no `verify=False` or disabled chain validation in AgentClient TLS config;
- no global/multitenant CA assumptions.
```

## Prompt 16 — Real agent mTLS serving

```text
[GLOBAL PROMPT]

Задача: поднять реальный runtime serving mode агента поверх TLS с обязательным client cert auth.

Контракт:
- Bootstrap listener/app отдельно от runtime mTLS listener/app.
- `/v1/*` and `/v1/admin/*` доступны только если TLS handshake validated dashboard client certificate.
- Agent runtime validates dashboard client cert against installed dashboard client CA/trust anchor or pinned dashboard client certificate policy.
- Plain HTTP runtime не должен существовать как production path.
- `GET /v1/info` тоже protected.
- После pairing bootstrap закрывается.

Сделай:
1. Server startup config для runtime mTLS.
2. Client CA/trust anchor validation.
3. Install/load dashboard client trust policy produced by bootstrap certificate install.
4. Tests with real server socket обязательны. Не использовать `if possible` для security path.

Forbidden for mTLS proof:
- FastAPI TestClient as the only proof;
- dependency override pretending to be client certificate auth;
- app-level paired-state guard as replacement for TLS client cert auth.

Required proof:
- real TLS socket/listener;
- client without cert rejected during TLS/auth layer;
- wrong client cert rejected;
- valid dashboard client cert accepted.

5. Tests:
   - no client cert rejected;
   - wrong client cert rejected;
   - valid dashboard cert accepted;
   - agent runtime rejects clients not signed by trusted dashboard client CA/trust anchor;
   - AgentClient cannot call protected endpoints without client cert/key;
   - plain HTTP rejected/not listening;
   - bootstrap remains token-only before pairing and closed after pairing.

Acceptance criteria:
- Не ограничивайся `_require_paired()`; это не auth.
- Должен быть integration test с реальным TLS socket/client certificate enforcement.
- При отсутствии такого теста верни `NO-GO`, а не green build.
```

## Prompt 17 — Backend AgentClient with per-request fingerprint binding

```text
[GLOBAL PROMPT]

Задача: реализовать backend AgentClient так, чтобы каждый request к агенту проверял active-node fingerprint binding.

Контракт:
- TLS chain validation is necessary but insufficient.
- После TLS handshake backend извлекает peer certificate fingerprint.
- Fingerprint должен совпасть с active `node.agent_cert_fingerprint` или связанной `node_mtls_identity`.
- Deleted/inactive node certificate must be rejected even if CA-valid.
- AgentClient не должен уметь делать protected requests без явной mTLS config.
- AgentClient должен использовать выбранную TLS identity policy:
  - SAN/hostname verification enabled when cert contains node IP/DNS SAN; or
  - CA validation + post-handshake fingerprint binding without disabling certificate validation.
- Forbidden: `verify=False`, disabled TLS chain validation, or replacing TLS verification with only app-level fingerprint check.

Tests:
- valid active node passes;
- CA-valid but wrong fingerprint rejected;
- deleted/inactive node rejected;
- missing mTLS config rejected before network call;
- invalid CA chain rejected;
- valid CA but wrong fingerprint rejected;
- test/static check proves AgentClient does not use `verify=False`;
- all script/admin/info client methods use the same guard;
- peer certificate fingerprint is extracted from the actual TLS connection, not from response JSON/header.
```

## Prompt 18 — mTLS probe and health

```text
[GLOBAL PROMPT]

Задача: реализовать mTLS health/probe service без обхода AgentClient security.

Сделай:
1. `probe_node_mtls(node_id)` calls protected `/v1/info` through verified AgentClient.
2. Updates node reachable/status fields after commit-safe transaction.
3. Does not create trust by itself; only verifies existing binding.
4. Tests for online/offline/wrong fingerprint.

Acceptance criteria:
- Probe не является единственным местом fingerprint проверки; AgentClient проверяет каждый request.
```

---

# PHASE 4 — Onboarding vertical slice

## Prompt 19 — Stage1 SSH installer: real installation plan

```text
[GLOBAL PROMPT]

Задача: реализовать Stage1 onboarding по SSH без placeholder installer.

Контракт:
- SSH используется только на этапе 1.
- Root password never persisted.
- Host key policy:
  - ed25519 is the only accepted host key algorithm;
  - if user provided fingerprint, it must match before password entry; mismatch aborts onboarding;
  - if fingerprint is not provided, explicit TOFU/unsafe mode stores first key and warns user;
  - saved ed25519 fingerprint must match on any repeat SSH/repair flow;
  - automatic host key replacement is forbidden;
  - diagnostics may include expected_fingerprint, received_fingerprint, key_algorithm, node_ip;
  - diagnostics/logs must never include root password, bootstrap token, private keys.
- Stage1 installs:
   - agent files/venv/package
   - non-root service user
   - systemd unit
   - config dirs and permissions
   - bootstrap token hash/expiry state
   - initial bootstrap listener
   - Xray/components only if included in resolved MVP scope
- If MVP scope for Xray/components is unresolved in `CONFLICTS.md`/`DOC_SOURCE_MANIFEST.md`/architecture notes, return `NO-GO` before implementing Stage1.
- After Stage1 SSH channel closes forever.

Сделай:
1. Installer script generation with explicit owned paths.
2. asyncssh service wrapper.
3. Tests with fake SSH runner verifying exact commands/artifacts.
4. Static/dry-run checks for generated install script: non-root user, systemd unit, owned paths, permissions, bootstrap state, no raw root password/token leaks.
5. Optional container/integration hook for later, but unit tests must verify install artifacts now.
6. Do not claim real VPS integration unless tested; add integration-test hook for later.

Acceptance criteria:
- Нет `install_stage1.txt` placeholder.
- Root password not stored in DB/logs.
- Host key mismatch aborts before password entry.
- Automatic host key replacement is impossible in normal path.
- Agent service runs as non-root.
```

## Prompt 20 — Stage2 mTLS onboarding orchestration

```text
[GLOBAL PROMPT]

Задача: реализовать backend Stage2 orchestration: bootstrap -> CSR -> sign -> certificate install -> verified mTLS.

Сделай:
1. Poll bootstrap status until CSR available or TTL/window expired.
2. Fetch CSR with bootstrap token.
3. Sign certificate via dashboard CA.
4. POST certificate to agent bootstrap endpoint. This install must include:
   - signed agent server certificate;
   - proof that agent private key remains local and is never sent to dashboard;
   - dashboard client trust anchor / dashboard client cert validation policy used by runtime mTLS;
   - bootstrap close semantics after verified mTLS.
5. Store fingerprint binding in active node identity.
6. Invalidate bootstrap token.
7. Verify protected `/v1/info` over mTLS with fingerprint binding.
8. Move node status to `metrics_uploading` or failed status.

Tests:
- happy path;
- bootstrap timeout 15/30m behavior;
- bad CSR;
- cert install failure;
- mTLS probe wrong fingerprint;
- token invalidated after success;
- agent rejects dashboard clients outside installed trust policy;
- no SSH after stage1.
```

## Prompt 21 — Stage3 metrics scripts as normal scripts

```text
[GLOBAL PROMPT]

Задача: реализовать Stage3 onboarding: metrics scripts upload + node_script links.

Контракт:
- `xray_status`, `detect_stack`, `speedtest` are normal scripts in dashboard DB, programmatically created.
- Агент не знает их имён.
- Upload uses normal `POST /v1/scripts/upload` over mTLS.
- После физической заливки backend создаёт 3 manual `node_script` rows with `folder_id IS NULL` and schedule triggers as required by notes.
- Metrics scripts must be real enough for MVP, not `echo placeholder`.
- If real speedtest/xray integration is out of MVP, architecture source files in the current local layout must explicitly defer it before this prompt; otherwise placeholder is `NO-GO`.
- speedtest timeout 180s.

Tests:
- scripts created if missing;
- hashes computed from content;
- upload called through AgentClient;
- node_script links created;
- schedule trigger interval 21600s if specified by notes;
- failure moves node to `failed_metrics_upload`.
```

## Prompt 22 — Onboarding public API and product workflow

```text
[GLOBAL PROMPT]

Задача: вывести onboarding наружу через backend API.

Endpoints предложить и реализовать минимально:
- start node onboarding with IP/root password/optional host fingerprint
- get onboarding status
- continue/retry failed stage if безопасно

Требования:
- API не возвращает raw secrets.
- Root password accepted only for immediate stage1, never persisted.
- Status maps to lifecycle states.
- Stage2/Stage3 доступны как internal orchestration, но UI может видеть прогресс.

Tests:
- API happy path through fakes;
- root password not persisted;
- status transitions;
- failure statuses visible.
```

---

# PHASE 5 — Scripts, desired-state, execution

## Prompt 23 — Script CRUD service and API

```text
[GLOBAL PROMPT]

Transaction-boundary requirement: add operation-specific tests from `TRANSACTION_CONTRACT_PLAN.md` proving `update_script_content` and `delete_script` do not call AgentClient inside active DB transaction.

Задача: реализовать dashboard script CRUD.

Контракт:
- Dashboard owns `script.name -> content/current_hash`.
- Agent sees only content hash.
- create_script does not upload remotely by default.
- update_script_content changes DB desired-state and creates `node_hash_gc` after desired diff if old hash no longer needed by active node.
- delete_script cascades local desired-state and creates GC for active affected nodes.
- Remote upload/GC only after commit.

Tests:
- create computes hash;
- update creates GC for old hash only when no longer desired;
- delete creates GC;
- no HTTP inside transaction;
- online proactive upload is best-effort after commit, if implemented;
- offline active node gets pending GC;
- deleted offline node does not get pending cleanup.
```

## Prompt 24 — Manual node_script linking service/API

```text
[GLOBAL PROMPT]

Задача: реализовать ручные desired-state связи script↔node.

Контракт:
- `node_script` means script should be available on node.
- Manual-only is `trigger_id IS NULL`.
- Multiple manual rows for same node/script allowed only when different trigger_id; at most one manual no-trigger row.
- Removing a link may create `node_hash_gc` after desired-state diff.
- No remote upload required at link creation; lazy execute can deliver.

Tests:
- create manual no-trigger link;
- duplicate no-trigger rejected;
- same node/script different trigger links allowed;
- unlink creates GC only if hash no longer desired;
- API response exposes link_id, because execution should be able to target exact link when multiple links exist.
```

## Prompt 25 — Run node script flow

```text
[GLOBAL PROMPT]

Transaction-boundary requirement: add operation-specific tests from `TRANSACTION_CONTRACT_PLAN.md` proving `run_node_script` performs upload/execute remote calls only after local DB commit or outside active transaction.

Задача: реализовать `run_node_script(node_script_id, source)`.

Контракт из transaction boundaries:
1. Before remote: read active node/script/current_hash/link/source metadata, generate request_id, close transaction.
2. Remote: execute(hash, request_id, args, env). If 404, upload(content), then execute again with same request_id.
3. After remote: update minimal last-run fields and schedule next-run if applicable.

Требования:
- Use node_script_id, not ambiguous node_id+script_id, because multiple valid links may exist.
- AgentClient must enforce mTLS + fingerprint binding.
- Pipeline/manual/schedule/on_startup sources are explicit.

Tests:
- happy path execute;
- execute -> 404 -> upload -> execute fallback;
- same request_id reused after upload;
- transport error recorded cleanly;
- no HTTP inside transaction;
- multiple links do not conflict;
- last-run fields update after remote.
```

---

# PHASE 6 — Folders and triggers

## Prompt 26 — Folder service/API with transaction-safe trigger cloning

```text
[GLOBAL PROMPT]

Transaction-boundary requirement: add operation-specific tests from `TRANSACTION_CONTRACT_PLAN.md` proving folder membership operations do not call AgentClient inside active DB transaction.

Задача: реализовать folder operations поверх SQL materialization.

Operations:
- create/update/delete folder;
- add/remove node to/from folder;
- add/remove script to/from folder;
- delete folder with/without preserving materialized links according to notes.

Контракт:
- SQL triggers materialize/revoke node_script rows for folder_id.
- Trigger template cloning is app-code inside same SQLite transaction. Do not copy one shared `folder_script.trigger_id` into all materialized `node_script` rows.
- Folder deletion behavior with checkbox is explicit service decision, not unconditional SQL trigger.
- Removing membership may create node_hash_gc after desired diff.
- No remote operations in transaction.

Tests:
- add node materializes scripts;
- add script materializes nodes;
- remove membership revokes only folder-created links;
- manual links preserved;
- trigger templates cloned independently;
- two materialized `node_script` rows from one folder_script do not share `trigger_id`;
- editing one materialized trigger does not affect another;
- editing template not retroactive;
- GC queued only by service after diff.
```

## Prompt 27 — Trigger service/API

```text
[GLOBAL PROMPT]

Задача: реализовать trigger management.

Контракт:
- Trigger is attribute of concrete link, not standalone public object.
- One node_script row has zero or one trigger.
- Multiple schedules for same node/script = multiple node_script rows.
- Manual execution is not trigger row; it is direct execute path.
- Types: schedule, on_startup.
- Cleanup orphan triggers via SQL cleanup.

Operations:
- set schedule trigger on node_script;
- set on_startup trigger;
- remove trigger;
- clone template trigger for folder materialization.

Tests:
- set/replace/remove trigger;
- old trigger orphan cleaned;
- invalid trigger type rejected;
- manual-only represented as NULL;
- separate materialized clones independent.
```

## Prompt 28 — Scheduler and on-startup runner

```text
[GLOBAL PROMPT]

Задача: реализовать background trigger runners.

Контракт:
- Schedule runner finds due node_script with trigger_schedule.
- Missed runs are skipped, not replayed.
- Next run is planned from current time after run attempt.
- On-startup runner runs on_startup links when backend starts.
- Neither runner is pipeline.
- Runner uses `run_node_script(node_script_id, source)`.

Tests:
- due schedule triggers run;
- missed runs after backend downtime are not replayed;
- next due calculated from now;
- on_startup runs once at startup event;
- transport failures do not block scheduler;
- no HTTP inside transaction.
```

---

# PHASE 7 — Pipelines

## Prompt 29 — Pipeline schema/service CRUD with materialization

```text
[GLOBAL PROMPT]

Задача: реализовать pipeline definitions.

Контракт:
- Pipeline is saved reusable entity, not ad-hoc.
- V1 linear steps only, max 32 steps.
- Step = execute one script on one node.
- Pipeline orchestration lives entirely in dashboard.
- Agent only sees ordinary execute calls.
- INSERT `pipeline_step` must materialize manual `node_script` desired-state via SQLite trigger, matching pipeline architecture note.
- Direct SQL insert into `pipeline_step` must create the `node_script` row without service code; service `add_step` uses the same DB-level guarantee.
- UPDATE `pipeline_step.node_id/script_id` must materialize the new node/script pair either via SQLite trigger or service code in the same SQLite transaction.
- Deleting a step does not revoke node_script link in v1, unless notes are updated; keep asymmetric simplification.

Tests:
- create pipeline;
- add steps ordered;
- enforce max 32;
- direct SQL INSERT into pipeline_step creates manual node_script row;
- service add_step passes through the same DB-level guarantee;
- update step node/script materializes new node_script pair and cannot leave the pair outside node_script;
- no duplicate bad materialization;
- archive pipeline instead of hard delete when history exists.
```

## Prompt 30 — Pipeline args mapping validation

```text
[GLOBAL PROMPT]

Задача: реализовать `pipeline_step_arg` validation.

Контракт:
- Step N may reference output of any previous step < N.
- No forward references.
- V1 passes data through `args`, not `env`.
- Static literal args allowed.
- Previous step stdout must be JSON object.
- Mapping references JSON fields.

Tests:
- static args;
- output field mapping;
- reference to future step rejected;
- reference missing field fails run;
- env mapping rejected/deferred for v2;
- invalid arg shape rejected.
```

## Prompt 31 — Pipeline run engine

```text
[GLOBAL PROMPT]

Задача: реализовать pipeline run orchestration.

Контракт:
- Sequential execution of steps.
- Each step uses `run_node_script`/AgentClient execute flow.
- Stop on first failure:
   - exit_code != 0
   - timed_out
   - transport error
   - stdout not JSON
   - missing mapped field
   - stdout limit exceeded
- No retry and no rollback.
- Pipeline history survives definition changes through snapshots.

Tests:
- happy path with JSON mapping;
- step failure stops later steps;
- timeout stops;
- invalid JSON stdout stops;
- missing field stops;
- snapshots preserved after script/pipeline edits;
- agent sees only execute calls, no pipeline API.
```

## Prompt 32 — Pipeline API

```text
[GLOBAL PROMPT]

Задача: вывести pipeline CRUD/run/history через backend API.

Endpoints предложить и реализовать:
- list/create/update/archive pipelines;
- add/update/delete/reorder steps;
- configure args mapping;
- run pipeline;
- get run status/history/details.

Tests:
- API validates max steps;
- API returns history snapshots;
- archive behavior;
- run endpoint delegates to run engine;
- errors are UI-readable.
```

---

# PHASE 8 — Deletion, GC, background workers

## Prompt 33 — Node deletion service/API

```text
[GLOBAL PROMPT]

Transaction-boundary requirement: add operation-specific tests from `TRANSACTION_CONTRACT_PLAN.md` proving deletion remote calls (`unpair`/`uninstall`) are not executed inside active DB transaction.

Задача: реализовать deletion lifecycle.

Контракт:
1. Delete from dashboard only:
   - if node online: remote `unpair` first, then local delete;
   - if node offline or force local: local delete allowed, UI warning about remaining paired agent/files.
2. Full cleanup:
   - only online with working mTLS;
   - remote `uninstall` first;
   - local delete only after confirmed uninstall.
3. CRL not used in v1.
4. Deleting local node removes application trust because active node/fingerprint binding disappears.
5. Pending cleanup not created for deleted offline node.

Tests:
- online local delete calls unpair before DB delete;
- unpair failure blocks non-force local delete;
- offline force/local delete warns;
- full delete requires online mTLS;
- uninstall failure does not delete local node;
- local delete cascades folder_node/node_script/orphan triggers/node_hash_gc.
```

## Prompt 34 — Node hash GC reconciler

```text
[GLOBAL PROMPT]

Transaction-boundary requirement: add operation-specific tests from `TRANSACTION_CONTRACT_PLAN.md` proving GC remote delete calls are not executed inside active DB transaction.

Задача: реализовать `node_hash_gc` reconciler.

Контракт:
- GC queue is created by service code after desired-state diff, not SQL triggers.
- Reconciler processes only active online nodes.
- Before `DELETE /v1/scripts/{hash}`, recalculate `desired_hashes(node)`.
- If hash became desired again, cancel/mark skipped.
- Agent DELETE idempotent: missing file success.
- Offline active node keeps pending GC.
- Deleted node has no pending cleanup.

Tests:
- pending active online -> delete;
- missing hash success;
- desired again -> cancel/no delete;
- offline active remains pending;
- no remote call inside DB transaction;
- wrong fingerprint rejected through AgentClient.
```

## Prompt 35 — App startup background integration

```text
[GLOBAL PROMPT]

Задача: подключить background processes к backend application lifecycle.

Processes:
- schedule trigger runner;
- on-startup trigger runner;
- node_hash_gc reconciler;
- onboarding/bootstrap poller if asynchronous;
- mTLS health/probe loop if in MVP.

Требования:
- Graceful startup/shutdown.
- No duplicate workers in tests/dev reload unless guarded.
- Failures logged and observable.
- Background jobs use service boundaries and AgentClient security.

Tests:
- app startup registers jobs;
- shutdown stops jobs;
- GC job invokes reconciler;
- on-startup trigger runner invoked once;
- no duplicate scheduler jobs.
```

---

# PHASE 9 — Product backend layer and public contracts

## Prompt 36 — Unified error model and API response contracts

```text
[GLOBAL PROMPT]

Задача: привести backend API к продуктово пригодному виду.

Сделай:
1. Общий error envelope:
   - code
   - message
   - details
   - retryable
   - user_action_required
2. Map domain errors:
   - node_offline
   - mtls_fingerprint_mismatch
   - bootstrap_expired
   - script_missing_uploaded_after_retry_failed
   - pipeline_step_failed
   - gc_pending
   - deletion_requires_online
3. Добавь OpenAPI schemas.
4. Tests на major error mappings.

Acceptance criteria:
- UI сможет показывать понятные сообщения без знания внутренних exceptions.
```

## Prompt 37 — Product API layer: node control panel backend

```text
[GLOBAL PROMPT]

Задача: собрать product-facing backend surface для будущего UI.

Минимальные endpoints:
- list nodes with lifecycle/status/last probe;
- node detail including scripts/folders/triggers/pending GC warnings;
- run script on node_script link;
- trigger metrics refresh;
- list scripts/folders/pipelines;
- dashboard capabilities/version.

Требования:
- Не добавлять новый source of truth.
- Все данные берутся из existing services/schema.
- Remote actions use service layer, not direct AgentClient in routers.
- Responses include enough product state for UI.

Tests:
- API smoke/integration through service fakes;
- no secrets exposed;
- deleted/inactive nodes hidden or marked according to product decision.
```

## Prompt 38 — Security hardening pass

```text
[GLOBAL PROMPT]

Задача: провести targeted security hardening по всему backend+agent.

Проверь и исправь:
1. No plain `/v1/*` agent path.
2. mTLS enforced by real server/client configuration.
3. Per-request fingerprint binding in AgentClient.
4. CA key and agent private key chmod 0600.
5. Raw bootstrap token not in DB/logs.
6. Agent refuses root runtime or install guarantees non-root.
7. Executor no shell, bounded output, resource limits.
8. Request-size guards before full parse where feasible.
9. Path traversal and symlink protections.
10. No network inside DB transaction.

Tests:
- no-cert request rejected;
- wrong cert rejected;
- wrong fingerprint rejected;
- deleted node cert rejected;
- bootstrap closed after pairing;
- body too large rejected;
- long stdout writer cannot grow memory unbounded;
- private key perms.
```

## Prompt 39 — End-to-end vertical slice test

```text
[GLOBAL PROMPT]

Задача: создать e2e/integration vertical slice, который доказывает, что backend foundation работает целиком.

Сценарий:
1. Initialize dashboard DB and CA.
2. Simulate or run Stage1 agent install with bootstrap state.
3. Complete Stage2 bootstrap CSR/cert/mTLS.
4. Verify `/v1/info` over mTLS and fingerprint binding.
5. Stage3 upload metrics scripts and create node_script links.
6. Run one metrics script through `run_node_script`.
7. Update script content and verify old hash GC queued.
8. Process GC and verify agent delete called only after desired re-check.
9. Delete node online local mode and verify unpair before local delete.

Acceptance criteria:
- Test covers the complete core lifecycle.
- Any fake must be explicit and not bypass the invariant being tested.
```

## Prompt 40 — Architecture conformance audit

```text
[GLOBAL PROMPT]

Задача: провести аудит реализации против заметок и `TRACEABILITY.md`.

Сделай:
1. Прочитай все architecture source files in the current local layout.
2. Прочитай весь backend/agent код и тесты.
3. Составь таблицу:
   - requirement
   - source doc
   - implementation files
   - tests
   - status: OK / PARTIAL / MISMATCH / MISSING
   - criticality
   - required fix
4. Особо проверь прошлые failed areas:
   - real mTLS runtime enforcement;
   - per-request fingerprint binding;
   - real SSH install;
   - real uninstall;
   - bounded executor output;
   - fd/fexecve or equivalent;
   - no SQL-trigger-owned node_hash_gc;
   - pipeline update materialization;
   - max_pipeline_steps;
   - missing backend routers;
   - background workers integrated.
5. Не исправляй код в этом prompt, только аудит.

Acceptance criteria:
- Аудит честный и пригоден как next task list.
```

## Prompt 41 — Final no-placeholder / release-readiness sweep

```text
[GLOBAL PROMPT]

Задача: перед feature-разработкой найти всё, что выглядит готовым, но на самом деле placeholder/deferred.

Найди:
- TODO/FIXME/pass/NotImplemented;
- placeholder scripts;
- fake installer/uninstaller;
- tests that assert fake behavior instead of real contract;
- xfail tests that should now pass;
- docs that противоречат code;
- endpoints not exposed;
- services not wired to app startup;
- security-sensitive defaults.

Для каждого пункта:
- файл/строка;
- почему это риск;
- нужно исправить до MVP или можно оставить after-MVP;
- конкретный next prompt для исправления.

Acceptance criteria:
- Не должно остаться скрытых placeholder'ов в security/foundation path.
```

---

# Audit prompts between phases

Правило v3: каждый audit prompt обязан завершиться строкой `PHASE_GATE: GO` или `PHASE_GATE: NO-GO`. При `NO-GO` следующий implementation prompt запрещён; используется только Emergency repair prompt. Audit prompts не должны менять код.

## Audit A — После Phase 1

```text
Проведи аудит только DB/schema/transaction layer. Не меняй код.
Проверь:
- schema соответствует ARCHITECTURE_INDEX;
- SQL triggers не делают product decisions;
- node_hash_gc не создаётся SQL-триггерами;
- manual-only = trigger_id NULL;
- partial unique indexes корректны;
- transaction test harness ловит HTTP inside transaction.
Выдай таблицу OK/PARTIAL/MISMATCH/MISSING.
```

## Audit B — После Phase 2

```text
Проведи аудит agent foundation. Не меняй код.
Проверь:
- нет plain runtime `/v1/*` app;
- upload/delete/info не доступны через bootstrap app;
- script storage по content hash;
- request-size guards;
- executor bounded output, no shell, resource limits, timeout, process group;
- request_id idempotency;
- unpair/uninstall не fake.
```

## Audit C — После Phase 3

```text
Проведи security-аудит bootstrap/mTLS. Не меняй код.
Проверь:
- raw bootstrap token not persisted;
- bootstrap closes after pairing;
- real mTLS client-cert auth on `/v1/*`;
- `GET /v1/info` protected;
- AgentClient rejects wrong fingerprint on every request;
- deleted node cert rejected.
```

## Audit D — После Phase 4

```text
Проведи аудит onboarding lifecycle. Не меняй код.
Проверь:
- SSH only stage1;
- root password not stored;
- real install artifacts;
- bootstrap -> CSR -> cert -> mTLS flow;
- metrics scripts are normal scripts;
- Stage3 creates node_script links and schedule triggers;
- failure statuses correct.
```

## Audit E — После Phase 5/6

```text
Проведи аудит desired-state/scripts/folders/triggers. Не меняй код.
Проверь:
- `node_script` is desired-state only;
- execute -> 404 -> upload -> execute works;
- multiple links same node/script do not break manual run;
- folder fan-out/revoke correct;
- trigger ownership and cleanup correct;
- scheduler skips missed runs.
```

## Audit F — После Phase 7

```text
Проведи аудит pipeline. Не меняй код.
Проверь:
- pipeline dashboard-only;
- max 32 steps;
- step insert/update materializes node_script;
- JSON stdout mapping only to args;
- no env mapping in v1;
- stop on failure;
- history snapshots survive definition changes;
- archive not hard delete with history.
```

## Audit G — После Phase 8/9

```text
Проведи финальный backend integration audit. Не меняй код.
Проверь:
- deletion online calls unpair first;
- full delete calls uninstall first;
- offline delete warns and creates no pending cleanup after node delete;
- GC re-checks desired hashes before delete;
- background workers wired;
- product APIs expose required operations;
- no secrets in API responses.
```

---

# Master pre-generation audit prompt

Используй этот prompt перед тем, как отдавать большой пакет задач другому coding agent, или если кажется, что реализация “почти готова”.

```text
[GLOBAL PROMPT]

Задача: проверить, можно ли продолжать разработку без риска повторить прошлый провал. Код не менять.

Проверь:
1. Каждый фундаментальный инвариант из `ARCHITECTURE_INDEX.md` имеет requirement_id, implementation file и тест.
2. Каждый пункт из `AUDIT_2026-07-03.md` Top-10 либо исправлен тестом, либо является явным `NO-GO`.
3. Нет security/lifecycle xfail.
4. Нет fake success: placeholder installer, placeholder metrics, fake uninstall, fake mTLS, fake fingerprint check, fake executor limits.
5. Есть хотя бы один e2e vertical slice, который проходит onboarding -> mTLS -> metrics -> execute -> GC -> delete.
6. Все backend services, которые нужны UI, выведены через routers/API.
7. Background workers реально registered in app lifecycle.
8. `TRACEABILITY.md` и `PROMPT_COVERAGE.md` совпадают с кодом и тестами.

Выдай:
- `READY_FOR_NEXT_PHASE: YES/NO`;
- таблицу blocking gaps;
- emergency repair prompts для каждого blocker.
```

# Emergency repair prompt template

```text
[GLOBAL PROMPT]

У нас есть конкретное архитектурное нарушение:
<PASTE AUDIT ITEM>

Задача:
1. Найди все места, где это нарушение проявляется.
2. Сначала добавь failing regression tests.
3. Исправь минимально возможным изменением.
4. Проверь, что не сломал соседние инварианты.
5. Обнови `TRACEABILITY.md`.
6. В финале дай changed files, tests, commands, risk notes.

Запрещено:
- замазывать тест;
- менять архитектурный контракт без явной правки architecture source files in the current local layout;
- делать fake implementation.
```


---

# v3.2 patch verification checklist

Перед запуском coding agent убедись, что этот файл содержит все v3.1 правки:

- `check_phase_gate.py --phase ...` checks only requirements whose `phase_gate` <= current phase.
- RED CONTRACT prompts explicitly named: Prompt 09 only; Prompt 05 explicitly not RED CONTRACT and default suite must stay green.
- Prompt 10 must make all Prompt 09 executor contract tests pass.
- Dashboard client certificate/private key lifecycle is part of Prompt 15/16/20.
- Agent certificate SAN/identity policy forbids `verify=False` and disabled chain validation.
- Bootstrap API tests include `202 csr_not_ready`, later `200 csr_ready`, and `410 bootstrap_closed`.
- Stage1 SSH host key policy uses ed25519, mismatch aborts before password entry, and automatic replacement is forbidden.
- Pipeline `INSERT pipeline_step` materialization is DB-level SQLite trigger with direct SQL test.
- `AUDIT_2026-07-03.md` is optional input, but missing audit file triggers built-in failed-area blocking requirements.

Final intended status: `READY_FOR_CODING_AGENT: YES`.


# v3.2 stabilization checklist

Перед запуском coding agent проверь, что prompt pack содержит:

- Prompt 05 is NOT RED CONTRACT and must not leave failing default tests.
- `TRANSACTION_CONTRACT_PLAN.md` is introduced, and future operation-specific transaction tests are assigned to Prompts 23/25/26/33/34.
- Prompt 07 must follow upload-hash decision from `CONFLICTS.md` or return `NO-GO`.
- TRACEABILITY uses the single status enum: `planned`, `implemented`, `tested`, `blocked`, `deferred_after_mvp`.
- Forbidden status aliases are rejected: `partial`, `untested`, `xfail`, `todo`, `later`, `covered_by_docs`.
- Folder trigger fan-out does not share template `trigger_id`; service code clones trigger + subtype rows per materialized link inside the same transaction.
- mTLS proof cannot rely only on FastAPI TestClient, dependency overrides, or app-level paired guards.
- AgentClient extracts peer fingerprint from actual TLS connection, not response JSON/header.
- `DOC_SOURCE_MANIFEST.md` is required if duplicate architecture docs exist.
- MVP scope for Xray/components and metrics scripts must be resolved before Stage1/Stage3.
- Prompt 12 separates admin handler behavior from transport-level mTLS protection.

Final readiness after v3.4: `READY_FOR_CODING_AGENT: YES`, assuming all architecture docs are present in the current local layout, prompt files are in the repository root, every new chat starts with `MASTER_SESSION_PROMPT.md`, and Prompt 00 starts with `DOC_SOURCE_MANIFEST.md`.
