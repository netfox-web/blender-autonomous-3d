# PORTFOLIO_DFM_ACCEPTANCE

generatedAt: 2026-09-09T12:33:24.774560+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 541–600 Small-Space KD SKU Portfolio Factory truth set.

| Check | Status | Evidence |
|---|---|---|
| invalid retained, not in Top 10 | REAL_LOGIC | `rejected=3 invalidInTop=0` |
| DFM conservation | REAL_LOGIC | `{"conservationOk": true, "toleranceMm2": 2.0}` |
| cross-SKU planning no consume | REAL_LOGIC | `{"sheetCountDelta": -15, "consumesInventory": false, "doubleAllocation": false}` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
