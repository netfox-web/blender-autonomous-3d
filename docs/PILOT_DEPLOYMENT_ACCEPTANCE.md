# PILOT_DEPLOYMENT_ACCEPTANCE

generatedAt: 2026-09-09T04:01:31.178860+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 421–480 truth set, not a replacement of the canonical six-file set.

| Check | Status | Evidence |
|---|---|---|
| FIXTURE/CHAOS workOrders | FIXTURE | `n=110` |
| no oversell | REAL_LOGIC | `subprocess/persistence scope=True` |
| material conservation | REAL_LOGIC | `True` |
| crash all-or-nothing | REAL_LOGIC | `in-process CrashInjected + subprocess after-staging` |
| stale writer blocked | REAL_LOGIC | `True` |
| station offline/lease/duplicate | FIXTURE | `{"offlineDenied": true, "duplicateAck": true, "duplicateComplete": true, "noDuplicateComplete": true, "leaseExpiry": true, "started": true, "crossTenantDenied": true}` |
| QC fail rework pass | FIXTURE | `{"failed": true, "passed": true, "rework": true}` |
| stale release rejected | FIXTURE | `True` |
| packing mismatch rejected | FIXTURE | `True` |
| journal tamper detected | REAL_LOGIC | `{"restartPreserved": true, "duplicateSuppressed": true, "tenantIsolated": true, "chainOkBefore": false, "tamperDetected": true}` |
| scan tenant isolation | FIXTURE | `True` |
| human approval gate | FIXTURE | `confirm required` |
| journalBusinessCommitConsistent | REAL_LOGIC | `True` |
| processRestartRecovery | REAL_LOGIC | `True` |
| noDoubleCompletionAfterRestart | REAL_LOGIC | `True` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| not factory throughput | FIXTURE | `FIXTURE/CHAOS` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
