# PILOT_BATCH_EXECUTION_ACCEPTANCE

generatedAt: 2026-09-10T08:36:38.775459+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 721–780 FIXTURE/REAL_LOGIC pilot-batch truth set. Fixture ≠ physical batch.

| Check | Status | Evidence |
|---|---|---|
| 4 SKU fixture batches | REAL_LOGIC | `[{"batchId": "01d49a76-4dcf-4062-9724-9d6723ec8bc3", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "30ad290d-76d1-4007-992e-63dd848bb809", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "dd3c3613-8036-47e5-a651-2cd2020dde24", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "74d559b3-3330-4624-aa1c-be1ea201b02e", "qty": 5, "state": "IN_PROGRESS"}]` |
| unit executions | REAL_LOGIC | `units=20` |
| fixture cannot HUMAN_BATCH_GO | REAL_LOGIC | `WAITING_HUMAN_EVIDENCE` |
| physicalPilotBatchValidated | REAL_LOGIC | `False` |
| tenant backup semantic | REAL_LOGIC | `{"liveA": "6fa15cd1ed5ac1d827d29533a8d4e107ceb4ddd8e127e4449a03eec90f2b5dc2", "restoredA": "6fa15cd1ed5ac1d827d29533a8d4e107ceb4ddd8e127e4449a03eec90f2b5dc2", "equal": true}` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c", "cases": 4, "failures": []}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
`physicalPilotBatchValidated=false`. `HUMAN_BATCH_GO` is not issued on fixture evidence.
