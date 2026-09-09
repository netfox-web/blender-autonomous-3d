# OPERATOR_CONTROL_ACCEPTANCE

generatedAt: 2026-09-09T03:04:22.274035+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 421–480 truth set, not a replacement of the canonical six-file set.

| Check | Status | Evidence |
|---|---|---|
| operator view tenant scoped | REAL | `chaos-a` |
| barcode hardware | PARTIAL | `scan token only` |
| LIVE_CNC badge | BLOCKED | `BLOCKED` |
| LIVE_LASER badge | BLOCKED | `BLOCKED` |
| health notFactorySla | REAL | `True` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
