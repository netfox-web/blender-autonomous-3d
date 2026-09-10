# PILOT_BATCH_EXECUTION_ACCEPTANCE

generatedAt: 2026-09-10T11:26:38.820263+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 721–780 FIXTURE/REAL_LOGIC pilot-batch truth set. Fixture ≠ physical batch.

| Check | Status | Evidence |
|---|---|---|
| 4 SKU fixture batches | REAL_LOGIC | `[{"batchId": "f1baa6d2-858f-4648-9101-2e2de1353668", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "a0d6adb2-e872-41cb-ae88-d7709847e700", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "c7e98311-a6de-4ba5-94b9-6f08178c8e2a", "qty": 5, "state": "IN_PROGRESS"}, {"batchId": "72f14587-3e2b-4476-a725-7124391db217", "qty": 5, "state": "IN_PROGRESS"}]` |
| unit executions | REAL_LOGIC | `units=20` |
| fixture cannot HUMAN_BATCH_GO | REAL_LOGIC | `WAITING_HUMAN_EVIDENCE` |
| physicalPilotBatchValidated | REAL_LOGIC | `False` |
| tenant backup semantic | REAL_LOGIC | `{"liveA": "c966a9d318cbd5edb6f985dd05a8d7503dab6cf63bfa5cee2f14e90bb35b988e", "restoredA": "c966a9d318cbd5edb6f985dd05a8d7503dab6cf63bfa5cee2f14e90bb35b988e", "equal": true}` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c", "cases": 4, "failures": []}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
`physicalPilotBatchValidated=false`. `HUMAN_BATCH_GO` is not issued on fixture evidence.
