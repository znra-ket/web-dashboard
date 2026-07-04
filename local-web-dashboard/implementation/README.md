# implementation/

This directory contains implementation guardrails for `web-xray-dashboard`.

Code and tests must follow the architecture notes selected in `DOC_SOURCE_MANIFEST.md`. The source of truth for this run is the current local layout:

- root architecture and prompt files;
- `Основное/`;
- `Агент/`;
- `Скрипты и папки/`.

Do not create or depend on `docs/architecture/` or `docs/prompts/` for this implementation path.

Prompt 00 creates only this preparation layer. Backend and agent logic must be introduced by later prompts, with tests and traceability updates for each prompt.

Allowed requirement statuses:

- `planned`
- `implemented`
- `tested`
- `blocked`
- `deferred_after_mvp`
