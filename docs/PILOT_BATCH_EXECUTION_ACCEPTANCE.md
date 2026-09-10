# PILOT_BATCH_EXECUTION_ACCEPTANCE

generatedAt: 2026-09-10T12:45:47.845693+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 721–780 FIXTURE/REAL_LOGIC pilot-batch truth set. Fixture ≠ physical batch.

| Check | Status | Evidence |
|---|---|---|
| 4 SKU fixture batches | REAL_LOGIC | `[{"batchId": "7fb46912-6d57-42ea-995b-4e16217a5225", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "f349b8b9-6a33-4eea-b3a6-6789050e1e92", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "4ae49eb6-51f4-417e-a0dc-fcd666a0fa99", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "e8d2f699-7c43-4305-86f9-5617ccaf8c74", "qty": 5, "state": "IN_PROGRESS"}]` |
| unit executions | REAL_LOGIC | `units=20` |
| fixture cannot HUMAN_BATCH_GO | REAL_LOGIC | `WAITING_HUMAN_EVIDENCE` |
| physicalPilotBatchValidated | REAL_LOGIC | `False` |
| tenant backup semantic | REAL_LOGIC | `{"liveA": "a7d6e46ccf93bfe0bdd891f105fad77ab377fa393cdf9a812f2aa772dda3dbdf", "restoredA": "a7d6e46ccf93bfe0bdd891f105fad77ab377fa393cdf9a812f2aa772dda3dbdf", "equal": true}` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c", "cases": 4, "failures": []}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
`physicalPilotBatchValidated=false`. `HUMAN_BATCH_GO` is not issued on fixture evidence.
