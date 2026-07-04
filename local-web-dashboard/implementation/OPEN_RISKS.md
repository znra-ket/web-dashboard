# OPEN_RISKS.md

## Active Risks After Prompt 14

| id | risk | impact | next safe action |
|---|---|---|---|
| R-001 | Backend Prompt 13 bootstrap token service remains planned in current audit state. | Dashboard-side onboarding token generation/validation cannot be claimed tested. | Implement or repair Prompt 13 before relying on backend token service evidence, or keep it explicitly planned. |
| R-002 | Real mTLS runtime remains planned. | `/v1/*` and `/v1/admin/*` transport security is not proven by handler tests. | Prompt 16 must add real listener/socket mTLS enforcement tests. |
| R-003 | Dashboard AgentClient remains planned. | Peer cert binding to an active node is not enforced yet. | Prompt 17 must validate TLS, client cert/key use, and actual peer certificate binding. |
| R-004 | Dashboard CA/certificate signing remains planned. | Prompt 14 agent CSR/certificate API has no dashboard CA service counterpart yet. | Prompt 15 should implement local CA, CSR signing, dashboard client cert/key lifecycle, and cert identity persistence. |
| R-005 | Bootstrap closure depends on successful mTLS probe. | Certificate delivery alone could create fake-success if treated as paired completion. | Keep full bootstrap closure planned until mTLS probe/onboarding evidence exists. |
| R-006 | Admin transport security remains planned. | Prompt 12 tested handler behavior, not real mTLS protection for admin endpoints. | Prompt 16 must protect `/v1/admin/*` with real mTLS. |
| R-007 | Node deletion flows remain planned. | Local deletion, online unpair, full uninstall, and deleted-cert invalidation are not product-tested. | Prompt 33 must implement dashboard deletion service flows after AgentClient/mTLS foundations exist. |
| R-008 | Backend run_node_script remains planned. | Execute/upload retry and transaction-safe remote calls are not tested. | Prompt 25 must implement read transaction -> remote call outside transaction -> update transaction. |
| R-009 | Scheduler/pipeline execute policies remain planned. | Request IDs and execute behavior for scheduled/pipeline runs are not tested. | Implement in scheduler/pipeline prompts, not in Prompt 15. |
| R-010 | Phase gate audit currently reports NO-GO for phase_2 due older foundation/transaction rows. | Later GO claims would be unsafe until due rows are repaired or proven. | Use an emergency repair/control prompt for those rows before claiming phase gate GO. |

## Requirements Not To Close Prematurely

- `API-004`, `MTLS-001`, `MTLS-005`, `MTLS-006`, `MTLS-007`, `MTLS-008`.
- `DELETE-001`, `DELETE-002`, `DELETE-003`, `DELETE-005`.
- `ONBOARD-001`, `ONBOARD-006`, `ONBOARD-008`.
- Backend script execution, scheduler, pipeline, and AgentClient retry/idempotency behavior.
