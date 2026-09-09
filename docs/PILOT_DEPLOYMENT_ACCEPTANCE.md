# PILOT_DEPLOYMENT_ACCEPTANCE

generatedAt: 2026-09-09T03:04:22.274035+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 421–480 truth set, not a replacement of the canonical six-file set.

| Check | Status | Evidence |
|---|---|---|
| FIXTURE/CHAOS workOrders | FIXTURE | `n=110` |
| no oversell | REAL | `True` |
| material conservation | REAL | `True` |
| crash all-or-nothing | REAL | `True` |
| stale writer blocked | REAL | `True` |
| station offline/lease/duplicate | REAL | `{"offlineDenied": true, "duplicateAck": true, "duplicateComplete": true, "noDuplicateComplete": true, "leaseExpiry": true, "started": true, "crossTenantDenied": true}` |
| QC fail rework pass | REAL | `{"failed": true, "passed": true, "rework": true}` |
| stale release rejected | REAL | `True` |
| packing mismatch rejected | REAL | `True` |
| journal tamper detected | REAL | `{"restartPreserved": true, "duplicateSuppressed": true, "tenantIsolated": true, "chainOkBefore": true, "tamperDetected": true}` |
| scan tenant isolation | REAL | `True` |
| human approval gate | REAL | `confirm required` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| not factory throughput | FIXTURE | `FIXTURE/CHAOS` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
