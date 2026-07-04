# CURRENT_STATE.md

Mode: control/meta compact state.
Last completed implementation prompt: Prompt 14.
Source of truth restored from repo files, targeted Prompt 10-14 evidence, and current tests.

## Test Evidence

- `python -m pytest agent/tests/test_executor_contract.py agent/tests/test_executor_limits.py agent/tests/test_executor_safety.py agent/tests/test_agent_execute_endpoint.py agent/tests/test_agent_admin.py agent/tests/test_bootstrap_api.py agent/tests/test_bootstrap.py agent/tests/test_config_state.py agent/tests/test_runtime_guardrails.py`
- Result: 51 passed, 1 warning.
- `python scripts/check_phase_gate.py --phase phase_2`
- Result: NO-GO. Existing due rows still not `tested`: `CORE-001`, `CORE-004`, `AGENT-001`, `TX-001`, `TX-002`, `TX-003`, `TX-004`, `TX-005`.

## Closed By Prompt 10

- Agent executor is implemented.
- `POST /v1/scripts/execute` exists on the agent runtime API.
- Execution is content-hash-only; the executor does not know script names, folders, triggers, pipelines, or dashboard business logic.
- Missing hash returns structured `404 script_not_found`.
- Executor does not use `shell=True`.
- Delete-while-running race is covered by fd/fexecve-like or equivalent safe-handle behavior in current implementation/tests.
- Timeout handling, process-group termination, global concurrency, per-hash concurrency, args/env validation, per-run workdir cleanup, workdir quota, and supported resource limits are implemented.
- Stdout/stderr are read concurrently with bounds; stdout overflow fails the result and stderr overflow truncates with a flag.

## Closed By Prompt 11

- Execute `request_id` is required and validated.
- Agent-side request idempotency cache is implemented.
- Same `request_id` with the same logical request replays the cached result.
- Same `request_id` with a different request fingerprint returns `409 request_id_conflict`.
- Request cache TTL and max-entry eviction are implemented.
- Execute body-size guard is implemented for the agent endpoint.

## Closed By Prompt 12

- Agent runtime handler behavior exists for `POST /v1/admin/unpair`.
- Agent runtime handler behavior exists for `POST /v1/admin/uninstall`.
- Admin lifecycle cleanup is constrained to web-xray-owned/whitelisted paths.
- Unpair removes local dashboard trust/cert/key/bootstrap material and pairing state according to current local agent implementation.
- Uninstall performs/schedules cleanup of web-xray-owned artifacts according to current local agent implementation.
- Admin operations are idempotent where safe, do not delete arbitrary filesystem paths, and do not log secrets.
- Only handler/runtime behavior is tested here; transport-level mTLS protection is not tested by Prompt 12.

## Prompt 13 Status

- Backend bootstrap token service is not closed in current compact state.
- `implementation/PROMPT_COVERAGE.md` still marks `MTLS-002` and `MTLS-003` for Prompt 13 as `planned`.
- Do not claim backend token generation, persistence, validation, or secrecy as tested until the backend Prompt 13 implementation and tests exist/pass.

## Closed By Prompt 14

- Agent bootstrap API endpoints exist: `/bootstrap/v1/status`, `/bootstrap/v1/csr`, `/bootstrap/v1/certificate`.
- Bootstrap Authorization behavior is implemented on the agent side with hash comparison.
- CSR generation and certificate installation behavior are implemented in the current agent bootstrap API.
- `csr_ready`, certificate install, paired-state transition, and `410 bootstrap_closed` behavior are covered by current agent tests.
- Bootstrap API does not expose the normal `/v1/*` runtime API.
- Bootstrap API/state tests confirm raw token is not stored in local agent state.

## Still Planned

- Dashboard-side `run_node_script` service.
- Dashboard-side execute -> 404 -> upload -> execute flow.
- Remote execution transaction boundary for backend script execution.
- Dashboard-side `request_id` generation and retry policy for manual run, scheduler, startup runner, and pipeline steps.
- Real mTLS transport for `/v1/*` and `/v1/admin/*`.
- Dashboard CA/certificate signing service.
- Dashboard AgentClient TLS validation, client cert/key use, and active-node peer certificate binding.
- Bootstrap closure semantics tied to successful mTLS probe, not certificate delivery alone.
- Node deletion service flows: online unpair -> local delete, full uninstall -> local delete, offline warning.
- Pipeline/scheduler usage of execute.

## Do Not Mark Tested Yet

- Backend script execution service and transaction-safe remote execution.
- Scheduler, startup runner, pipeline, or backend idempotency behavior.
- `API-004`, `MTLS-001`, `MTLS-005`, `MTLS-006`, `MTLS-007`, `MTLS-008`.
- `DELETE-001`, `DELETE-002`, `DELETE-003`, `DELETE-005`.
- `ONBOARD-001`, `ONBOARD-006`, `ONBOARD-008`.
