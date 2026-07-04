# DOC_SOURCE_MANIFEST.md

Prompt ID: Prompt 00
Created: 2026-07-04
Scope: current local layout only. Do not use `docs/architecture/` or `docs/prompts/` for this run.

## Selection Policy

- Prefer the files in the current local layout: repository root plus `Основное/`, `Агент/`, and `Скрипты и папки/`.
- Do not mix older File Library versions unless the user explicitly requests it.
- If duplicate current documents with the same architectural title appear, stop with `NO-GO` before implementation.
- `AUDIT_2026-07-03.md` is optional for Prompt 00 and was not present in the project root at creation time.

## Chosen Sources

| chosen_source_path | file_size_bytes | sha256 | modified_time | reason_this_version_was_chosen |
|---|---:|---|---|---|
| `MASTER_SESSION_PROMPT.md` | 14453 | `c7fa00bc7981bfb75eca82c084879e75fe5c2068a8632e18d7e4ad03ae8efb72` | 2026-07-04 13:29:03 +03:00 | Required session guardrail file in current local layout root. |
| `webxray_prompt_pack_v3_4_local_layout.md` | 89978 | `a0edaaceecf106befcbc73667c420bce911aa42f1e63023f86654f44de52276d` | 2026-07-04 13:29:03 +03:00 | Required prompt pack in current local layout root. |
| `ARCHITECTURE_INDEX.md` | 12817 | `0e4bb6eb080470e018312989424303a35661d03671a3f0e93a8b56c5509adacf` | 2026-07-02 12:42:01 +03:00 | Current root architecture index and source for fundamental invariants. |
| `Transactional service boundaries.md` | 10266 | `62aec998af3dbfd7dd3568adfbb838df0093927f5b7ed9e564fab773a47f27d5` | 2026-07-02 12:42:01 +03:00 | Current root transaction-boundary spec. |
| `Основное/web-xray-dashboard — Основной дизайн-документ.md` | 7917 | `35f0be50eed730b10b6fb66e1c9f5db585aaec7b8f242560ce24b559a5964197` | 2026-07-02 12:42:11 +03:00 | Current CORE/product constraints document. |
| `Основное/Онбординг ноды в дашборд.md` | 14616 | `d41493fd4a89b401b4d56ae57699665f89a2ce2403ad38a017d09bb4be016af8` | 2026-07-02 12:42:16 +03:00 | Current onboarding flow document. |
| `Агент/Установка mTLS соединения дашборд - агент.md` | 28951 | `9999c59f8b534bcd2a05329b737637a7c9df378cb83d59369ec0e76d5ba7c091` | 2026-07-02 12:42:19 +03:00 | Current bootstrap trust chain and runtime mTLS document. |
| `Агент/Принцип работы агента ноды.md` | 40314 | `85f730158ba83f72668e2581c9de55fbe7308e38b3b74c0ba98b183101c77ac9` | 2026-07-02 12:42:23 +03:00 | Current agent API, executor, storage, and limits document. |
| `Агент/Удаление ноды из дашборда.md` | 35114 | `1e0d154f85766ea8f5555293b9b873805fb09c89edab13cc176eb472fa21a459` | 2026-07-02 12:01:35 +03:00 | Current node deletion, unpair, and uninstall lifecycle document. |
| `Скрипты и папки/Архитектура папок и материализация связей.md` | 44885 | `e21eae396ec23ca0abff75ea03cee68a6c19c6f13644bfd19501181628c1b751` | 2026-07-02 12:42:28 +03:00 | Current folders and `node_script` materialization document. |
| `Скрипты и папки/Триггеры запуска скриптов.md` | 42072 | `a8796b2158fcc3d9fc50ef4614ac0bc3d86207ace7f848665e2fe94744144ed9` | 2026-07-02 12:42:32 +03:00 | Current trigger model and scheduler semantics document. |
| `Скрипты и папки/Пайплайны и их архитектура.md` | 23989 | `9f4765c6a91589e1dd13abb6b828509726e59465d79d3705eb7173267f0e00ca` | 2026-07-02 12:42:36 +03:00 | Current pipeline definition and run semantics document. |

## Optional Sources

| source_path | status | reason |
|---|---|---|
| `AUDIT_2026-07-03.md` | `blocked` | Optional prior audit file was not present in the project root during Prompt 00. |

## Duplicate Check

Each expected architecture document title was found once in the current local layout:

- `ARCHITECTURE_INDEX.md`
- `Transactional service boundaries.md`
- `web-xray-dashboard — Основной дизайн-документ.md`
- `Онбординг ноды в дашборд.md`
- `Установка mTLS соединения дашборд - агент.md`
- `Принцип работы агента ноды.md`
- `Удаление ноды из дашборда.md`
- `Архитектура папок и материализация связей.md`
- `Триггеры запуска скриптов.md`
- `Пайплайны и их архитектура.md`
