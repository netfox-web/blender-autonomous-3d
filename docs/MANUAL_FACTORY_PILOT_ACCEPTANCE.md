# MANUAL_FACTORY_PILOT_ACCEPTANCE

generatedAt: 2026-09-09T10:03:37.649332+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 481–540 Manual Factory Pilot truth set.

| Check | Status | Evidence |
|---|---|---|
| four-family FIXTURE e2e | FIXTURE | `True` |
| operator/shift isolation | REAL_LOGIC | `disabled/closed/cross-tenant fail closed` |
| shift restart | REAL_LOGIC | `True` |
| traveler releaseHash pin | REAL_LOGIC | `099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4` |
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
| restore no double consume/complete | REAL_LOGIC | `{"stateBefore": "COMPLETED", "stateAfter": "COMPLETED", "releaseHash": "099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4", "releaseHashAfter": "099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4", "before": {"state": "COMPLETED", "releaseHash": "099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4", "reservations": [{"reservationId": "man-a:6d8c3955-37b6-4777-89cc-151c48ed1c5d:34dd09c3-8fae-4fa0-b126-89c7c93f8c48:2", "lotId": "34dd09c3-8fae-4fa0-b126-89c7c93f8c48", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"34dd09c3-8fae-4fa0-b126-89c7c93f8c48": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "201ccd07f4b40db59c465f81c0aa5bb439ece86ff0897ebe8b2736931e9b02d2", "journalSequence": 180, "journalOk": true}, "after": {"state": "COMPLETED", "releaseHash": "099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4", "reservations": [{"reservationId": "man-a:6d8c3955-37b6-4777-89cc-151c48ed1c5d:34dd09c3-8fae-4fa0-b126-89c7c93f8c48:2", "lotId": "34dd09c3-8fae-4fa0-b126-89c7c93f8c48", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"34dd09c3-8fae-4fa0-b126-89c7c93f8c48": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "201ccd07f4b40db59c465f81c0aa5bb439ece86ff0897ebe8b2736931e9b02d2", "journalSequence": 180, "journalOk": true}, "noDoubleConsume": true, "noDoubleCompletion": true, "journalOk": true, "liveMachineControl": false, "ok": true}` |
| journal after restore | REAL_LOGIC | `True` |
| restored-root health | REAL_LOGIC | `{"ok": true, "status": "REAL", "label": "REAL", "count": 180, "headHash": "201ccd07f4b40db59c465f81c0aa5bb439ece86ff0897ebe8b2736931e9b02d2", "sequence": 180}` |
| tenant leakage absent | REAL_LOGIC | `{}` |
| tenant required state preserved | REAL_LOGIC | `[]` |
| snapshot path-set bound | REAL_LOGIC | `True` |
| cross-tenant restore | REAL_LOGIC | `True` |
| evidenceCodeCommit | REAL_LOGIC | `1fc86cff1101c8a8e66df59950a8accc7f527d76` |
| workingTreeClean | REAL_LOGIC | `True` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| REAL blender refresh | REAL | `unchanged render/release path; reuse 4/4 T1000 OptiX CODE 018cc70 generation c878d5f3-a3d2-44cd-8223-7b2b94d84af1` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
