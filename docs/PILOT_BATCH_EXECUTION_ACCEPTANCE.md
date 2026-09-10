# PILOT_BATCH_EXECUTION_ACCEPTANCE

generatedAt: 2026-09-10T06:08:51.098833+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 721–780 FIXTURE/REAL_LOGIC pilot-batch truth set. Fixture ≠ physical batch.

| Check | Status | Evidence |
|---|---|---|
| 4 SKU fixture batches | REAL_LOGIC | `[{"batchId": "98c13244-2384-49ee-9787-4d1e88ef5715", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "b65c5fe2-c454-41bb-9f79-5b72fd874455", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "bcf4916e-9945-4ef5-9455-6aec51465ab2", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "23b77235-66e4-4f65-98d4-f073262b0ed0", "qty": 5, "state": "IN_PROGRESS"}]` |
| unit executions | REAL_LOGIC | `units=20` |
| fixture cannot HUMAN_BATCH_GO | REAL_LOGIC | `WAITING_HUMAN_EVIDENCE` |
| physicalPilotBatchValidated | REAL_LOGIC | `False` |
| tenant backup semantic | REAL_LOGIC | `{"liveA": "c76e144ceb1a26121968470da6fd5cfa94bd400b219dce0c9c80e04a669973e5", "restoredA": "c76e144ceb1a26121968470da6fd5cfa94bd400b219dce0c9c80e04a669973e5", "equal": true}` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c", "cases": 4, "failures": []}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
`physicalPilotBatchValidated=false`. `HUMAN_BATCH_GO` is not issued on fixture evidence.
