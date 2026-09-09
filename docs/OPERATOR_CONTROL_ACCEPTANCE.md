# OPERATOR_CONTROL_ACCEPTANCE

generatedAt: 2026-09-09T04:01:31.178860+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 421–480 truth set, not a replacement of the canonical six-file set.

| Check | Status | Evidence |
|---|---|---|
| operator view tenant scoped | FIXTURE | `chaos-a` |
| barcode hardware | PARTIAL | `scan token only` |
| LIVE_CNC badge | BLOCKED | `BLOCKED` |
| LIVE_LASER badge | BLOCKED | `BLOCKED` |
| health notFactorySla | FIXTURE | `True` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
