# MASTER_SESSION_PROMPT.md

Ты работаешь в проекте web-xray-dashboard.

Рабочая папка проекта:
C:\Users\znra2\Documents\web dashboard\local-web-dashboard

Твоя задача — помогать в prompt-by-prompt реализации проекта без потери архитектурных требований, без fake-success и без scope creep.

---

## 1. Главный режим работы

Всегда сначала восстанови состояние из файлов репозитория, а не из истории чата.

История чата — низкоприоритетный источник.
Файлы проекта — source of truth.

Перед выполнением любой задачи сначала прочитай:

- webxray_prompt_pack_v3_4_local_layout.md
- implementation/CURRENT_STATE.md, если существует
- implementation/NEXT_PROMPT.md, если существует
- implementation/PHASE_GATES.md, если существует
- implementation/BLOCKING_REQUIREMENTS.md, если существует
- implementation/OPEN_RISKS.md, если существует
- implementation/CONFLICTS.md, если существует
- implementation/TRANSACTION_CONTRACT_PLAN.md, если существует

Не читай полностью implementation/TRACEABILITY.md и implementation/PROMPT_COVERAGE.md по умолчанию.

Эти файлы audit/reference-only:
- implementation/TRACEABILITY.md
- implementation/PROMPT_COVERAGE.md

Читай или обновляй их только если:
- текущий prompt явно требует traceability/audit update;
- phase gate check упал и нужны evidence по requirement;
- пользователь явно попросил audit;
- нужно обновить конкретные строки, затронутые текущим prompt.

---

## 2. Два допустимых типа задач

Есть только два нормальных режима задачи.

### A. Coding prompt mode

Используй этот режим, когда пользователь просит выполнить конкретный prompt из webxray_prompt_pack_v3_4_local_layout.md.

Правила:
- Выполняй только указанный Prompt ID.
- Не переходи к следующему prompt.
- Не реализуй future requirements.
- Не расширяй scope.
- Не исправляй “заодно” соседние подсистемы.
- Не меняй архитектурные решения без явного требования.
- Не помечай future requirements как tested.
- Не делай fake-success.

### B. Control/meta mode

Используй этот режим, когда пользователь просит reorganize/control/guardrails/handoff/audit/meta cleanup.

Правила:
- Не меняй backend/agent/frontend продуктовый код.
- Не выполняй coding prompts.
- Меняй только control/guardrail/handoff файлы.
- Не удаляй старые guardrail-файлы без явного плана миграции.
- Не создавай новую огромную матрицу вместо старой.
- Цель control/meta mode — уменьшить context load, но сохранить контроль требований.

---

## 3. Scope discipline

Перед началом работы явно определи:

- текущий режим: coding prompt или control/meta;
- текущий Prompt ID, если это coding prompt;
- какие файлы можно менять;
- какие файлы нельзя менять;
- какие requirements можно переводить в tested;
- какие requirements должны остаться planned.

Если Prompt ID не указан и это не очевидная control/meta задача — остановись и верни NO-GO с просьбой указать Prompt ID или подтвердить meta-task.

---

## 4. Архитектурные инварианты проекта

Никогда не нарушай эти правила:

- Dashboard локальный, не SaaS.
- Один dashboard владеет одной node; multi-owner не поддерживается.
- Dashboard всегда инициирует соединения; agent никогда не звонит обратно.
- SSH используется только для Stage1 onboarding.
- Root password не хранится после Stage1.
- Bootstrap token временный и не хранится в raw виде.
- Runtime после onboarding работает через mTLS.
- Agent — dumb executor.
- Agent не знает script names, folders, triggers, pipelines или dashboard business logic.
- Agent хранит scripts по content hash.
- node_script — desired-state, не physical delivery fact.
- Execute flow: execute -> 404 -> upload -> execute.
- Remote HTTP к agent запрещён внутри активной SQLite transaction.
- Remote calls только после commit.
- SQL triggers делают только локальную материализацию/cleanup.
- node_hash_gc создаётся service-code после desired-state diff, не SQL trigger.
- mTLS certificate chain validation alone is insufficient.
- Dashboard должен bind actual peer certificate fingerprint/public key/serial к active node.
- Deleted node cert становится invalid через отсутствие active-node binding; CRL в v1 нет.
- Online dashboard-only deletion сначала unpair, потом local delete.
- Full cleanup требует успешный uninstall, потом local delete.
- Offline dashboard-only deletion local-only с warning.
- Pipeline orchestration только на dashboard side.
- Agent видит pipeline steps как обычные execute calls.
- Missed schedule runs skipped, not replayed.

---

## 5. Transaction rules

Для backend service logic:

- Local desired-state changes должны быть в одной SQLite transaction.
- Remote agent HTTP calls запрещены внутри transaction.
- Используй backend/app/services/transaction.py и существующий transaction guard.
- Для операций вида run_node_script:
  - read transaction before remote call;
  - remote call outside transaction;
  - update transaction after remote result.
- Не скрывай transaction violations через mocks.

---

## 6. Security rules

Запрещено:

- verify=False для TLS.
- fake mTLS через dependency override как единственное доказательство.
- считать app-level paired-state guard заменой real mTLS.
- логировать private keys, raw bootstrap tokens или secret material.
- хранить raw bootstrap token.
- делать plain runtime ASGI app без paired/mTLS context.
- делать shell=True executor.
- использовать path-based execution, если prompt требует fd/fexecve/equivalent safe handle.
- удалять произвольные filesystem paths вне web-xray-owned whitelist.

---

## 7. Phase gates

Перед выполнением coding prompt проверь текущие phase gates.

Phase gate может быть GO только если:
- все blocking requirements для этой фазы implemented/tested согласно правилам проекта;
- нет planned/blocking requirements, которые уже должны быть закрыты в этой фазе;
- нет known open risk, который блокирует фазу.

Не делай phase gate GO ради продвижения, если evidence слабый.

---

## 8. Status rules

Разрешённые статусы:

- planned
- implemented
- tested
- blocked
- deferred_after_mvp

Запрещены как официальные статусы:

- partial
- done-ish
- probably done
- covered by docs
- later
- todo
- xfail как доказательство выполнения

tested можно ставить только если:
- есть реальная implementation;
- есть tests;
- tests прошли;
- evidence указано в compact state или targeted traceability rows.

---

## 9. Compact control system

Обычная работа теперь должна использовать компактные файлы:

ACTIVE каждый чат:
- implementation/CURRENT_STATE.md
- implementation/NEXT_PROMPT.md
- implementation/PHASE_GATES.md
- implementation/BLOCKING_REQUIREMENTS.md
- implementation/OPEN_RISKS.md
- implementation/COMPACT_HANDOFF.md

REFERENCE/AUDIT only:
- implementation/TRACEABILITY.md
- implementation/PROMPT_COVERAGE.md
- implementation/CONFLICTS.md
- implementation/TRANSACTION_CONTRACT_PLAN.md

После каждого coding prompt обнови:

- implementation/CURRENT_STATE.md
- implementation/NEXT_PROMPT.md
- implementation/COMPACT_HANDOFF.md
- implementation/PHASE_GATES.md, если изменился
- implementation/OPEN_RISKS.md, если изменился
- targeted TRACEABILITY/PROMPT_COVERAGE rows only if required

COMPACT_HANDOFF.md должен быть максимум 80 строк.

---

## 10. Работа с тестами

Перед coding изменениями:
- найди relevant tests для текущего prompt;
- прочитай failing tests;
- не меняй tests, чтобы искусственно сделать green.

После изменений:
- запусти tests, требуемые текущим prompt;
- затем запусти broader relevant suite, если prompt этого требует.

Если тесты нельзя запустить — честно укажи почему.
Не заявляй “passed”, если tests не запускались.

---

## 11. Когда возвращать NO-GO

Верни NO-GO вместо fake-success, если:

- Prompt ID не указан для coding task.
- Не найден prompt pack.
- Не найден required architecture/control file.
- Требование prompt невозможно выполнить без нарушения архитектуры.
- Тесты противоречат architecture notes.
- Нужна real mTLS/socket proof, а доступен только fake TestClient proof.
- Требуется безопасный executor, но нельзя реализовать fd/fexecve/equivalent safe handle.
- Требуется удаление filesystem paths без whitelisted ownership.
- Реализация требует scope creep в будущие prompts.

NO-GO должен содержать:
- что блокирует;
- какие файлы/тесты это показывают;
- минимальный безопасный следующий шаг.

---

## 12. Финальный ответ после каждой задачи

Финальный ответ должен быть компактным.

Для coding prompt:
- Prompt ID;
- changed files;
- tests run;
- test result;
- requirements covered;
- phase gate changes;
- remaining risks;
- next recommended prompt;
- GO/NO-GO.

Для control/meta task:
- changed control files;
- new workflow;
- what files are active vs audit-only;
- next recommended coding prompt;
- short bootstrap prompt for next coding chat.

Не вставляй огромные таблицы в финальный ответ.
Не копируй полный TRACEABILITY.md или PROMPT_COVERAGE.md в чат.

---

## 13. Default next-chat bootstrap format

Когда обновляешь COMPACT_HANDOFF.md, добавь короткий bootstrap prompt такого формата:

Прочитай MASTER_SESSION_PROMPT.md и строго следуй ему.

Рабочая папка:
C:\Users\znra2\Documents\web dashboard\local-web-dashboard

Используй compact control files как source of truth:
- implementation/CURRENT_STATE.md
- implementation/NEXT_PROMPT.md
- implementation/PHASE_GATES.md
- implementation/BLOCKING_REQUIREMENTS.md
- implementation/OPEN_RISKS.md
- webxray_prompt_pack_v3_4_local_layout.md

Не читай полный TRACEABILITY.md или PROMPT_COVERAGE.md, если текущий prompt явно этого не требует.

Выполни только prompt, указанный в implementation/NEXT_PROMPT.md.

Не реализуй future requirements.
Не помечай future requirements как tested.
Не расширяй scope.
После выполнения обнови compact control files и дай COMPACT_HANDOFF максимум 80 строк.