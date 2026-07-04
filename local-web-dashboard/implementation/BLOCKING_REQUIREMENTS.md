# BLOCKING_REQUIREMENTS.md

Prompt ID: Prompt 00A
Scope: requirements that cannot be closed by placeholder, fake-success, deferred claim, or xfail.

`AUDIT_2026-07-03.md` was not present in the project root. The Prompt 00A fallback failed-area list is therefore included below.

| requirement_id | blocking area | source | prompt_id | phase_gate | why blocking |
|---|---|---|---|---|---|
| MTLS-008 | Real mTLS runtime enforcement | Prompt 00A fallback; mTLS notes | Prompt 16 | mtls_runtime | Protected agent API must be enforced by real mTLS listener/socket behavior, not app-level guards. |
| MTLS-005 | Per-request active-node fingerprint binding | mTLS notes; deletion notes | Prompt 17 | mtls_runtime | TLS chain validation alone is insufficient; dashboard must bind peer cert to active `node`. |
| MTLS-003 | Bootstrap token secrecy | mTLS notes | Prompt 13 | onboarding_security | Raw bootstrap tokens must not be persisted or logged. |
| AGENT-007 | Bounded executor limits | agent notes | Prompt 10 | executor | Agent must not be an unbounded job runner. |
| AGENT-008 | Bounded executor output | Prompt 00A fallback; agent notes | Prompt 10 | executor | Reading process output without stdout/stderr limits can exhaust node resources. |
| AGENT-006 | fd/fexecve or equivalent execute/delete safety | Prompt 00A fallback; agent notes | Prompt 10 | executor | Execute/delete race must be addressed without shell-based fake success. |
| AGENT-003 | Request body guards | agent notes | Prompt 08 | agent_api | Upload/body limits must reject oversized or slow requests. |
| ONBOARD-002 | Real SSH install plan | Prompt 00A fallback; onboarding notes | Prompt 19 | onboarding_security | SSH is the only Stage1 trust channel and cannot be mocked as ready. |
| ONBOARD-007 | Real Xray/components Stage1 install | `implementation/CONFLICTS.md#c-008-mvp-scope-xray-components-and-metrics-scripts`; onboarding notes | Prompt 19 | onboarding_security | Stage1 MVP includes Xray, related components, and agent installation. |
| ONBOARD-008 | Real MVP metrics scripts and linking | `implementation/CONFLICTS.md#c-008-mvp-scope-xray-components-and-metrics-scripts`; onboarding notes | Prompt 21 | onboarding | Metrics scripts are required for onboarding completion and cannot be placeholder success. |
| DELETE-003 | Real uninstall | Prompt 00A fallback; deletion notes | Prompt 33 | lifecycle | Full cleanup must be confirmed by agent before local deletion. |
| DELETE-001 | Deletion lifecycle and online unpair | deletion notes | Prompt 33 | lifecycle | Online deletion must break agent trust before local deletion. |
| TX-007 | GC ownership by service code | Prompt 00A fallback; folder/transaction notes | Prompt 34 | reconciliation | `node_hash_gc` must not be created by SQL trigger or network side effects. |
| TX-001 | SQLite transaction boundaries | transaction notes | Prompt 05 | transaction_boundaries | Local desired-state must be atomic. |
| TX-002 | No remote HTTP inside SQLite transaction | transaction notes | Prompt 05 | transaction_boundaries | Network calls inside DB transactions are explicitly forbidden. |
| PIPE-004 | Pipeline update materialization | Prompt 00A fallback; pipeline notes | Prompt 29 | pipeline | Pipeline-only nodes must still enter script update distribution via `node_script`. |
| PIPE-008 | `max_pipeline_steps` | Prompt 00A fallback; architecture index | Prompt 30 | pipeline | Pipeline size limit is part of v1 limits. |
| API-005 | Missing backend routers | Prompt 00A fallback | Prompt 36 | api_contracts | Implemented services must be reachable through product API contracts. |
| API-006 | Background workers integrated | Prompt 00A fallback; architecture index | Prompt 35 | background_workers | Scheduler, startup runner, GC, onboarding poller, and mTLS probe are required v1 background processes. |

## Forbidden Closure Patterns

- No `xfail`, placeholder, fake-success, or "documented gap" closure for any row above.
- No app-level substitute for mTLS runtime enforcement.
- No `verify=False` or disabled TLS chain validation.
- No peer fingerprint from JSON/header in place of the actual TLS peer certificate.
- No shell-based or unbounded executor implementation marked ready.
- No SQL-trigger-owned network work or SQL-trigger-owned `node_hash_gc`.
