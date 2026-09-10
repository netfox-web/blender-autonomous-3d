# PILOT_BATCH_EXECUTION_ACCEPTANCE

generatedAt: 2026-09-10T10:17:55.492451+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 721–780 FIXTURE/REAL_LOGIC pilot-batch truth set. Fixture ≠ physical batch.

| Check | Status | Evidence |
|---|---|---|
| 4 SKU fixture batches | REAL_LOGIC | `[{"batchId": "d643936f-4b1e-408a-9312-6e7335f912dc", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "32f7745b-6fa4-441c-978b-f30920375439", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "8ccac910-401b-4c4d-8ee5-72da36e929e9", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "6a92ed68-d379-4583-a22a-b73c0b3b22e8", "qty": 5, "state": "IN_PROGRESS"}]` |
| unit executions | REAL_LOGIC | `units=20` |
| fixture cannot HUMAN_BATCH_GO | REAL_LOGIC | `WAITING_HUMAN_EVIDENCE` |
| physicalPilotBatchValidated | REAL_LOGIC | `False` |
| tenant backup semantic | REAL_LOGIC | `{"liveA": "09a21bd3e65e6d5ac4a2aa1d472795787e04193d5aa2367b259e5316abc92c06", "restoredA": "09a21bd3e65e6d5ac4a2aa1d472795787e04193d5aa2367b259e5316abc92c06", "equal": true}` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c", "cases": 4, "failures": []}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
`physicalPilotBatchValidated=false`. `HUMAN_BATCH_GO` is not issued on fixture evidence.
