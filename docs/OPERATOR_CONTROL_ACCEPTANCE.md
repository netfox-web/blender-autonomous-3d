# OPERATOR_CONTROL_ACCEPTANCE

generatedAt: 2026-09-09T05:21:51.977026+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 421–480 truth set, not a replacement of the canonical six-file set.

| Check | Status | Evidence |
|---|---|---|
| operator view tenant scoped | FIXTURE | `chaos-a` |
| barcode hardware | PARTIAL | `scan token only` |
| LIVE_CNC badge | BLOCKED | `BLOCKED` |
| LIVE_LASER badge | BLOCKED | `BLOCKED` |
| health notFactorySla | FIXTURE | `True` |
| shared journal health | REAL_LOGIC | `{"ok": true, "status": "REAL", "label": "REAL", "count": 545, "headHash": "49c218a9fd3c15e154c86b79ecb4a9eed77122b75f33b4e7bcf74a2e774b3da7", "sequence": 545}` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
