# MANUAL_FACTORY_PILOT_ACCEPTANCE

generatedAt: 2026-09-09T08:25:56.293044+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 481–540 Manual Factory Pilot truth set.

| Check | Status | Evidence |
|---|---|---|
| four-family FIXTURE e2e | FIXTURE | `True` |
| operator/shift isolation | REAL_LOGIC | `disabled/closed/cross-tenant fail closed` |
| shift restart | REAL_LOGIC | `True` |
| traveler releaseHash pin | REAL_LOGIC | `ed32d284a39541e6ed70be50f0f4c9a15fb5add326eb38c84bff1497213fb92f` |
| scan token tenant-safe | REAL_LOGIC | `authorizesOperation=false` |
| cycle-count approval | REAL_LOGIC | `WAITING_HUMAN_APPROVAL` |
| inventory conserved | REAL_LOGIC | `consumed/reserved unchanged` |
| labor append-only | REAL_LOGIC | `CONFIG_ESTIMATE vs MANUAL; accounting NOT_IMPLEMENTED` |
| blocking hold | REAL_LOGIC | `True` |
| rework lineage | REAL_LOGIC | `True` |
| packing pin | REAL_LOGIC | `True` |
| manual shipment | REAL_LOGIC | `MANUAL/IMPORTED, no provider` |
| backup checksum | REAL_LOGIC | `True` |
| restore releaseHash | REAL_LOGIC | `True` |
| restore no double consume/complete | REAL_LOGIC | `{"stateBefore": "COMPLETED", "stateAfter": "COMPLETED", "releaseHash": "ed32d284a39541e6ed70be50f0f4c9a15fb5add326eb38c84bff1497213fb92f", "releaseHashAfter": "ed32d284a39541e6ed70be50f0f4c9a15fb5add326eb38c84bff1497213fb92f", "before": {"state": "COMPLETED", "releaseHash": "ed32d284a39541e6ed70be50f0f4c9a15fb5add326eb38c84bff1497213fb92f", "reservations": [{"reservationId": "man-a:d4bfb32b-70f9-400f-8117-43adc3509040:75682b21-dbec-4bd7-baff-67fc0909c9be:2", "lotId": "75682b21-dbec-4bd7-baff-67fc0909c9be", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"75682b21-dbec-4bd7-baff-67fc0909c9be": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "e4187428fc29911ef339ea3626e8b9d40bb37bd89c636f804f33569f4d3505a4", "journalSequence": 179, "journalOk": true}, "after": {"state": "COMPLETED", "releaseHash": "ed32d284a39541e6ed70be50f0f4c9a15fb5add326eb38c84bff1497213fb92f", "reservations": [{"reservationId": "man-a:d4bfb32b-70f9-400f-8117-43adc3509040:75682b21-dbec-4bd7-baff-67fc0909c9be:2", "lotId": "75682b21-dbec-4bd7-baff-67fc0909c9be", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"75682b21-dbec-4bd7-baff-67fc0909c9be": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "e4187428fc29911ef339ea3626e8b9d40bb37bd89c636f804f33569f4d3505a4", "journalSequence": 179, "journalOk": true}, "noDoubleConsume": true, "noDoubleCompletion": true, "journalOk": true, "liveMachineControl": false, "ok": true}` |
| journal after restore | REAL_LOGIC | `True` |
| cross-tenant restore | REAL_LOGIC | `True` |
| evidenceCodeCommit | REAL_LOGIC | `ff285a2f9ef82500b0c0f01caacd18bc1186113f` |
| workingTreeClean | REAL_LOGIC | `True` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| REAL blender refresh | REAL | `unchanged render/release path; reuse 4/4 T1000 OptiX CODE 018cc70 generation c878d5f3-a3d2-44cd-8223-7b2b94d84af1` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
