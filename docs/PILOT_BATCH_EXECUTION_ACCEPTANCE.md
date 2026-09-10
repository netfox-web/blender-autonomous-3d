# PILOT_BATCH_EXECUTION_ACCEPTANCE

generatedAt: 2026-09-10T07:34:14.007760+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 721–780 FIXTURE/REAL_LOGIC pilot-batch truth set. Fixture ≠ physical batch.

| Check | Status | Evidence |
|---|---|---|
| 4 SKU fixture batches | REAL_LOGIC | `[{"batchId": "7b05b427-05cb-4829-ac28-b2836d23842c", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "fa9cfb67-be52-4bab-b890-00b109847d11", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "6fabdf6f-70ad-4726-96e9-088eeecae21d", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "5052e241-6e78-45d1-b891-ec00f06b1ace", "qty": 5, "state": "IN_PROGRESS"}]` |
| unit executions | REAL_LOGIC | `units=20` |
| fixture cannot HUMAN_BATCH_GO | REAL_LOGIC | `WAITING_HUMAN_EVIDENCE` |
| physicalPilotBatchValidated | REAL_LOGIC | `False` |
| tenant backup semantic | REAL_LOGIC | `{"liveA": "de695548270e23d26a122c9db5dd97bb71f42fbd3761bbcc5d1569d82418a65a", "restoredA": "de695548270e23d26a122c9db5dd97bb71f42fbd3761bbcc5d1569d82418a65a", "equal": true}` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c", "cases": 4, "failures": []}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
`physicalPilotBatchValidated=false`. `HUMAN_BATCH_GO` is not issued on fixture evidence.
