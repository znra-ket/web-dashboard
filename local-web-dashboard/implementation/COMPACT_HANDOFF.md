# COMPACT_HANDOFF.md

Read `MASTER_SESSION_PROMPT.md` and follow it strictly.

Working folder:
`C:\Users\znra2\Documents\web dashboard\local-web-dashboard`

Use active compact control files as source of truth:
- `implementation/CURRENT_STATE.md`
- `implementation/NEXT_PROMPT.md`
- `implementation/PHASE_GATES.md`
- `implementation/BLOCKING_REQUIREMENTS.md`
- `implementation/OPEN_RISKS.md`
- `webxray_prompt_pack_v3_4_local_layout.md`

Do not read full `TRACEABILITY.md` or `PROMPT_COVERAGE.md` unless the current prompt explicitly requires targeted audit evidence.

Current state:
- Last completed implementation prompt: Prompt 14.
- Prompt 10 executor implementation is tested in current agent tests.
- Prompt 11 agent-side execute `request_id` cache is tested in current agent tests.
- Prompt 12 admin handler/runtime behavior is tested, but admin mTLS transport remains planned.
- Prompt 13 backend bootstrap token service remains planned in current audit state.
- Prompt 14 agent bootstrap API is tested in current agent tests.
- Targeted test run: 51 passed, 1 warning.
- Phase gate `phase_2` currently returns NO-GO due older foundation/transaction rows.

Next coding prompt:
- Execute only Prompt 15 - Dashboard CA and cert signing service.

Prompt 15 guardrails:
- Connect to Prompt 14 CSR/certificate needs.
- Do not implement Prompt 16/17/18/20+ early.
- Do not mark real mTLS, AgentClient binding, onboarding, deletion, scheduler, pipeline, or backend script execution as tested.

After completion:
- Update compact control files.
- Keep `COMPACT_HANDOFF.md` under 80 lines.
- Update only targeted audit rows if tests genuinely prove the status change.
