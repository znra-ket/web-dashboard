# PROMPT_COVERAGE.md

Document origin: Prompt 00A
Last updated through: Prompt 14
Scope: requirement to prompt to test mapping.

Current status reflects implementation progress through Prompt 14. Executor RED CONTRACT tests have been implemented and passed. Prompt 13 backend token service remains planned; future prompts remain planned unless explicitly marked tested with evidence.

| requirement_id | prompt_id | test_id/test_file | phase gate | current status |
|---|---|---|---|---|
| CORE-001 | Prompt 01 | `backend/tests/test_architecture_manifest.py` | foundation | planned |
| CORE-002 | Prompt 03 | `backend/tests/test_migrations.py` | foundation_schema | tested |
| CORE-003 | Prompt 16 | `agent/tests/test_mtls_runtime.py`; `backend/tests/test_agent_client.py` | mtls_runtime | planned |
| CORE-004 | Prompt 01 | frontend smoke tests | foundation | planned |
| CORE-005 | Prompt 01 | `backend/tests/test_health.py` | foundation | tested |
| API-001 | Prompt 08/10 | `agent/tests/test_agent_api.py`; `agent/tests/test_agent_execute_endpoint.py`; `agent/tests/test_executor_contract.py` | agent_api | tested |
| API-002 | Prompt 12 | `agent/tests/test_agent_admin.py` | lifecycle | tested |
| API-003 | Prompt 14 | `agent/tests/test_bootstrap_api.py` | onboarding_security | tested |
| API-004 | Prompt 16 | `agent/tests/test_mtls_runtime.py` | mtls_runtime | planned |
| API-005 | Prompt 36 | `backend/tests/test_api_routes.py` | api_contracts | planned |
| API-006 | Prompt 35 | `backend/tests/test_app_startup.py` | background_workers | planned |
| MTLS-001 | Prompt 16 | `agent/tests/test_mtls_runtime.py` | mtls_runtime | planned |
| MTLS-002 | Prompt 13 | `backend/tests/test_bootstrap_token_service.py` | onboarding_security | planned |
| MTLS-003 | Prompt 13 | `backend/tests/test_bootstrap_token_service.py` | onboarding_security | planned |
| MTLS-004 | Prompt 14 | `agent/tests/test_bootstrap_api.py` | onboarding_security | planned |
| MTLS-005 | Prompt 17 | `backend/tests/test_agent_client.py` | mtls_runtime | planned |
| MTLS-006 | Prompt 17 | `backend/tests/test_agent_client.py` | mtls_runtime | planned |
| MTLS-007 | Prompt 15 | `backend/tests/test_certificate_authority.py`; `backend/tests/test_mtls_onboarding_stage2.py` | onboarding_security | planned |
| MTLS-008 | Prompt 16 | `agent/tests/test_mtls_socket_runtime.py` | mtls_runtime | planned |
| ONBOARD-001 | Prompt 20 | `backend/tests/test_onboarding_stage_flow.py` | onboarding | planned |
| ONBOARD-002 | Prompt 19 | `backend/tests/test_onboarding_stage1.py` | onboarding_security | planned |
| ONBOARD-003 | Prompt 19 | `backend/tests/test_onboarding_stage1.py` | onboarding_security | planned |
| ONBOARD-004 | Prompt 03 | `backend/tests/test_migrations.py` | foundation_schema | tested |
| ONBOARD-005 | Prompt 21 | `backend/tests/test_metrics_onboarding_stage3.py` | onboarding | planned |
| ONBOARD-006 | Prompt 20 | `backend/tests/test_mtls_onboarding_stage2.py` | onboarding | planned |
| ONBOARD-007 | Prompt 19 | `backend/tests/test_onboarding_stage1.py` | onboarding_security | planned |
| ONBOARD-008 | Prompt 21 | `backend/tests/test_metrics_onboarding_stage3.py` | onboarding | planned |
| AGENT-001 | Prompt 06 | `agent/tests/test_agent_contract.py` | agent_foundation | planned |
| AGENT-013 | Prompt 06 | `agent/tests/test_config_state.py`; `agent/tests/test_runtime_guardrails.py`; `agent/tests/test_bootstrap.py` | agent_foundation | tested |
| AGENT-002 | Prompt 07 | `agent/tests/test_script_storage.py` | agent_storage | tested |
| AGENT-003 | Prompt 08 | `agent/tests/test_agent_api.py`; `agent/tests/test_script_storage.py` | agent_api | tested |
| AGENT-004 | Prompt 10 | `agent/tests/test_agent_execute_endpoint.py`; `agent/tests/test_executor_contract.py` | executor | tested |
| AGENT-005 | Prompt 11 | `agent/tests/test_agent_execute_endpoint.py` | executor | tested |
| AGENT-006 | Prompt 10 | `agent/tests/test_executor_contract.py` | executor | tested |
| AGENT-007 | Prompt 10/11 | `agent/tests/test_executor_limits.py`; `agent/tests/test_executor_safety.py`; `agent/tests/test_agent_execute_endpoint.py` | executor | tested |
| AGENT-008 | Prompt 10 | `agent/tests/test_executor_limits.py` | executor | tested |
| AGENT-009 | Prompt 10 | `agent/tests/test_executor_safety.py` | executor | tested |
| AGENT-010 | Prompt 08 | `agent/tests/test_agent_api.py`; `agent/tests/test_script_storage.py` | agent_api | tested |
| AGENT-011 | Prompt 08 | `agent/tests/test_agent_api.py`; `agent/tests/test_runtime_guardrails.py` | agent_api | tested |
| TX-001 | Prompt 05 | `backend/tests/test_transaction_boundaries.py` | transaction_boundaries | implemented |
| TX-002 | Prompt 05 | `backend/tests/test_transaction_boundaries.py` | transaction_boundaries | implemented |
| TX-003 | Prompt 23 | `backend/tests/test_script_service.py`; `backend/tests/test_transaction_boundaries.py` | transaction_boundaries | planned |
| TX-004 | Prompt 26 | `backend/tests/test_folder_links.py` | transaction_boundaries | planned |
| TX-005 | Prompt 25 | `backend/tests/test_script_execution_service.py` | transaction_boundaries | planned |
| TX-006 | Prompt 33 | `backend/tests/test_node_deletion_service.py` | lifecycle | planned |
| FOLDER-001 | Prompt 03 | `backend/tests/test_migrations.py` | foundation_schema | tested |
| FOLDER-002 | Prompt 03 | `backend/tests/test_migrations.py` | foundation_schema | tested |
| FOLDER-003 | Prompt 04 | `backend/tests/test_migrations.py`; `backend/tests/test_folder_triggers.py` | schema_triggers | tested |
| FOLDER-004 | Prompt 26 | `backend/tests/test_folder_api.py`; `backend/tests/test_folder_links.py` | folder_service | planned |
| FOLDER-005 | Prompt 03 | `backend/tests/test_migrations.py` | foundation_schema | tested |
| FOLDER-006 | Prompt 26 | `backend/tests/test_folder_api.py` | folder_service | planned |
| TRIGGER-001 | Prompt 27 | `backend/tests/test_migrations.py` | triggers | tested |
| TRIGGER-002 | Prompt 03 | `backend/tests/test_migrations.py` | foundation_schema | tested |
| TRIGGER-003 | Prompt 27 | `backend/tests/test_triggers.py` | triggers | planned |
| TRIGGER-004 | Prompt 04 | `backend/tests/test_migrations.py`; `backend/tests/test_folder_triggers.py` | schema_triggers | tested |
| TRIGGER-005 | Prompt 28 | `backend/tests/test_scheduler_triggers.py` | scheduler | planned |
| TRIGGER-006 | Prompt 28 | `backend/tests/test_scheduler_triggers.py` | scheduler | planned |
| TRIGGER-007 | Prompt 03 | `backend/tests/test_migrations.py` | foundation_schema | tested |
| PIPE-001 | Prompt 31 | `backend/tests/test_pipeline_run_service.py` | pipeline | planned |
| PIPE-002 | Prompt 29 | `backend/tests/test_pipeline_service.py` | pipeline | planned |
| PIPE-003 | Prompt 30 | `backend/tests/test_pipeline_service.py` | pipeline | planned |
| PIPE-004 | Prompt 29 | `backend/tests/test_pipeline_service.py` | pipeline | planned |
| PIPE-005 | Prompt 31 | `backend/tests/test_pipeline_run_service.py` | pipeline | planned |
| PIPE-006 | Prompt 31 | `backend/tests/test_pipeline_run_service.py` | pipeline | planned |
| PIPE-007 | Prompt 29 | `backend/tests/test_pipeline_service.py` | pipeline | planned |
| PIPE-008 | Prompt 30 | `backend/tests/test_pipeline_service.py` | pipeline | planned |
| DELETE-001 | Prompt 33 | `backend/tests/test_node_deletion_service.py` | lifecycle | planned |
| DELETE-002 | Prompt 33 | `backend/tests/test_node_deletion_service.py` | lifecycle | planned |
| DELETE-003 | Prompt 33 | `backend/tests/test_node_deletion_service.py`; `agent/tests/test_agent_admin.py` | lifecycle | planned |
| DELETE-004 | Prompt 12 | `agent/tests/test_agent_admin.py` | lifecycle | tested |
| DELETE-005 | Prompt 17 | `backend/tests/test_agent_client.py` | mtls_runtime | planned |
| DELETE-006 | Prompt 22 | `backend/tests/test_onboarding_api.py` | onboarding | planned |
| TX-007 | Prompt 34 | `backend/tests/test_node_hash_gc.py` | reconciliation | planned |
| TX-008 | Prompt 34 | `backend/tests/test_node_hash_gc.py` | reconciliation | planned |
| TX-009 | Prompt 34 | `backend/tests/test_node_hash_gc.py`; `backend/tests/test_node_deletion_service.py` | reconciliation | planned |
| AGENT-012 | Prompt 08 | `agent/tests/test_agent_api.py`; `agent/tests/test_script_storage.py` | agent_api | tested |
| CORE-009 | Prompt 02 | `backend/tests/test_architecture_constants.py` | foundation | tested |
| CORE-006 | Prompt 41 | release audit | release_readiness | deferred_after_mvp |
| CORE-007 | Prompt 41 | release audit | release_readiness | deferred_after_mvp |
| CORE-008 | Prompt 41 | release audit | release_readiness | deferred_after_mvp |
