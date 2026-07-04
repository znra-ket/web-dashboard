# NEXT_PROMPT.md

Next coding prompt: Prompt 15 - Dashboard CA and cert signing service.

## Scope

Implement only Prompt 15 from `webxray_prompt_pack_v3_4_local_layout.md`.

Prompt 15 must focus on the local dashboard CA service:

- local single-installation dashboard CA ownership;
- CA private key storage with protected file/directory permissions;
- signing agent CSRs;
- creating or loading dashboard client certificate/private key for outbound AgentClient use;
- storing certificate identity material needed for future active-node binding: fingerprint, serial, and/or public-key fingerprint;
- certificate identity policy without disabling TLS validation;
- no `verify=False`;
- no logging of private keys or secret material.

## Required Context From Prior Prompts

- Prompt 14 already provides an agent-side CSR/certificate bootstrap API.
- Prompt 13 backend token service is still planned in current audit state; do not rely on it as tested.
- Bootstrap must not be considered fully closed merely because a certificate was delivered.
- Full bootstrap closure remains dependent on a successful mTLS probe in later prompts.

## Explicit Non-Scope

- Do not implement Prompt 16 real agent mTLS serving.
- Do not implement Prompt 17 Dashboard AgentClient peer binding.
- Do not implement Prompt 18 mTLS probe/health.
- Do not implement Prompt 20+ onboarding orchestration.
- Do not implement node deletion flows.
- Do not mark mTLS runtime, AgentClient binding, onboarding, or deletion requirements as `tested`.

## Expected Tests

- CA creation/loading tests.
- CA private key and dashboard client private key permission tests where supported by platform.
- Agent CSR signing tests.
- Dashboard client certificate/key creation or loading tests.
- Certificate identity/fingerprint/serial persistence tests.
- Negative tests for secret logging or unsafe TLS-disable patterns if the implementation introduces those surfaces.

## Completion Rules

- Update compact control files after Prompt 15.
- Update targeted audit rows only if Prompt 15 actually changes their status with passing tests.
- Leave future mTLS runtime requirements planned until Prompt 16/17 evidence exists.
