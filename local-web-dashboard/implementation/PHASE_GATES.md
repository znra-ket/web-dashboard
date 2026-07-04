# PHASE_GATES.md

Prompt ID: Prompt 00C
Scope: process guardrails for deciding `GO`/`NO-GO` by implementation phase.

## Rule Summary

- `TRACEABILITY.md` is the source of requirement status.
- `PROMPT_COVERAGE.md` is the source of `requirement -> prompt -> test` coverage.
- Future-phase requirements may stay `planned`, but every future blocking requirement must already have `prompt_id`, `phase_gate`, and expected test mapping.
- When a requirement's `phase_gate` is reached, it must be `tested`.
- Security/lifecycle/foundation blocking requirements cannot be closed with `deferred_after_mvp`, `partial`, `untested`, `xfail`, `todo`, `later`, or `covered_by_docs`.
- A failed phase audit means `NO-GO`. Continue only through an emergency repair prompt that fixes the failing requirement or its mapping.

## Phase Order

| phase | included phase_gate values | criteria |
|---|---|---|
| `phase_0` | guardrail files only | `TRACEABILITY.md`, `PROMPT_COVERAGE.md`, `BLOCKING_REQUIREMENTS.md`, `CONFLICTS.md`, and this file exist and are machine-readable. Future blocking requirements may remain `planned` if fully mapped. |
| `phase_1` | `foundation`, `foundation_schema`, `schema_triggers`, `transaction_boundaries` | Mono-repo/test harness, architecture manifest, core schema/migrations, SQL materialization triggers, and transaction-boundary tests are `tested`. |
| `phase_2` | `agent_foundation`, `agent_storage`, `agent_api`, `executor` | Agent config/state/storage/API/body guards and bounded executor contract/implementation are `tested`. |
| `phase_3` | `onboarding_security`, `lifecycle`, `mtls_runtime` | Bootstrap token secrecy, bootstrap API, CA signing, real mTLS runtime, AgentClient active-node binding, admin unpair/uninstall are `tested`. |
| `phase_4` | `onboarding` | Stage1/Stage2/Stage3 onboarding workflow and MVP metrics scripts are `tested`. |
| `phase_5` | `folder_service`, `triggers`, `scheduler`, `pipeline`, `reconciliation` | Script CRUD/link/run flows, folder/trigger/scheduler/pipeline services, pipeline run engine, node deletion, and hash GC reconciler are `tested`. |
| `phase_6` | `background_workers`, `api_contracts` | Startup background integrations and unified/product API contracts are `tested`. |
| `phase_7` | `release_readiness` | End-to-end vertical slice, architecture conformance audit, and no-placeholder release readiness sweep are complete. |

## Commands

Run a phase audit after the corresponding implementation/audit prompt:

```powershell
python scripts/check_phase_gate.py --phase phase_0
python scripts/check_phase_gate.py --phase phase_1
python scripts/check_phase_gate.py --phase phase_2
python scripts/check_phase_gate.py --phase phase_3
python scripts/check_phase_gate.py --phase phase_4
python scripts/check_phase_gate.py --phase phase_5
python scripts/check_phase_gate.py --phase phase_6
python scripts/check_phase_gate.py --phase phase_7
```

CI/test command for a phase audit:

```powershell
python scripts/check_phase_gate.py --phase phase_0
```

Replace `phase_0` with the current phase in CI once implementation advances.

## GO/NO-GO Semantics

- `GO`: all due requirements for the selected phase and earlier phases are `tested`, required columns are present, status enum is valid, and every requirement has coverage mapping.
- `NO-GO`: any due requirement is not `tested`, any status alias is forbidden, any required column is missing, any blocking requirement lacks prompt/test/phase mapping, or any security/lifecycle/foundation blocking requirement is deferred or otherwise fake-closed.
