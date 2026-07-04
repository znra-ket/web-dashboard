# TRANSACTION_CONTRACT_PLAN.md

Prompt ID: Prompt 05
Source: `Transactional service boundaries.md`

This file maps future service operations that must use `backend.app.services.transaction.SQLiteUnitOfWork` and must guard all agent-facing calls with the remote-after-commit marker.

Prompt 05 intentionally adds infrastructure and dummy contract tests only. It does not add failing tests for services that do not exist yet.

## Contract

- Local desired-state writes happen inside `SQLiteUnitOfWork`.
- Agent calls happen after the unit-of-work commits.
- Tests should use `TransactionGuardedFakeAgentClient` or the same `assert_remote_call_allowed()` check to fail if a remote call happens while `current_transaction_marker().active` is true.
- Operation-specific tests must be added in the prompt that implements the corresponding operation.

## Future Operations

| prompt_id | operation | required local transaction | required post-commit remote work | future test file |
|---|---|---|---|---|
| Prompt 23 | `update_script_content` | update `script.content/current_hash`, recompute affected desired-state, create any needed `node_hash_gc` rows | best-effort upload and later GC reconciliation only after commit | `backend/tests/test_script_service.py`; `backend/tests/test_transaction_boundaries.py` |
| Prompt 23 | `delete_script` | delete local `script`, let FK/cleanup triggers update local rows, create any needed `node_hash_gc` rows | best-effort hash cleanup only after commit | `backend/tests/test_script_service.py`; `backend/tests/test_transaction_boundaries.py` |
| Prompt 25 | `run_node_script` | read active node/script binding before remote, update minimal last-run fields after remote in a separate transaction | execute, upload-on-404, execute retry only outside active transaction | `backend/tests/test_script_execution_service.py` |
| Prompt 26 | folder membership operations | insert/delete `folder_node` and `folder_script`, rely on SQL fan-out/revoke, clone trigger templates in the same local transaction | optional upload after commit only | `backend/tests/test_folder_links.py`; `backend/tests/test_folder_api.py` |
| Prompt 33 | `delete_node_local` | remove local node and related rows after successful remote precondition when required | `unpair` before local delete for online dashboard-only deletion | `backend/tests/test_node_deletion_service.py` |
| Prompt 33 | `delete_node_full` | delete local node only after remote uninstall confirmation | `uninstall` before local delete | `backend/tests/test_node_deletion_service.py` |
| Prompt 34 | GC reconciliation | update `node_hash_gc` status/attempts in local transactions | `DELETE /v1/scripts/{hash}` only after desired-hash recheck and outside active transaction | `backend/tests/test_node_hash_gc.py` |

## Current Status

- Infrastructure exists: `backend/app/services/transaction.py`.
- Reusable test fake exists: `backend/tests/helpers/transaction_contract.py`.
- Dummy tests prove the guard catches a bad service and allows a good post-commit service.
- Real operation-specific requirements remain future work until their implementation prompts.
