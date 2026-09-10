# PILOT_BATCH_EXECUTION_ACCEPTANCE

generatedAt: 2026-09-10T13:33:40.891103+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 721–780 FIXTURE/REAL_LOGIC pilot-batch truth set. Fixture ≠ physical batch.

| Check | Status | Evidence |
|---|---|---|
| 4 SKU fixture batches | REAL_LOGIC | `[{"batchId": "dc260e1c-28d3-4ae0-bdc7-5cb4a23eab19", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "2787a0c7-4a6c-4092-8268-4a6e48c67c41", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "24585b29-bb85-49be-87dd-e65323946506", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "849b91d2-e500-42ae-b7e0-7694f4883e09", "qty": 5, "state": "IN_PROGRESS"}]` |
| unit executions | REAL_LOGIC | `units=20` |
| fixture cannot HUMAN_BATCH_GO | REAL_LOGIC | `WAITING_HUMAN_EVIDENCE` |
| physicalPilotBatchValidated | REAL_LOGIC | `False` |
| tenant backup semantic | REAL_LOGIC | `{"liveA": "889866450a2141b0e1201598478d3aaab3406449d60f59d5c87e934f747f2213", "restoredA": "889866450a2141b0e1201598478d3aaab3406449d60f59d5c87e934f747f2213", "equal": true}` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c", "cases": 4, "failures": []}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
`physicalPilotBatchValidated=false`. `HUMAN_BATCH_GO` is not issued on fixture evidence.
