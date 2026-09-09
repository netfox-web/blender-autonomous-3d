# PILOT_BACKUP_RESTORE_ACCEPTANCE

generatedAt: 2026-09-09T10:03:37.649332+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 481–540 Manual Factory Pilot truth set.

| Check | Status | Evidence |
|---|---|---|
| backup checksum | REAL_LOGIC | `True` |
| restore releaseHash | REAL_LOGIC | `True` |
| restore no double consume/complete | REAL_LOGIC | `{"stateBefore": "COMPLETED", "stateAfter": "COMPLETED", "releaseHash": "099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4", "releaseHashAfter": "099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4", "before": {"state": "COMPLETED", "releaseHash": "099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4", "reservations": [{"reservationId": "man-a:6d8c3955-37b6-4777-89cc-151c48ed1c5d:34dd09c3-8fae-4fa0-b126-89c7c93f8c48:2", "lotId": "34dd09c3-8fae-4fa0-b126-89c7c93f8c48", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"34dd09c3-8fae-4fa0-b126-89c7c93f8c48": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "201ccd07f4b40db59c465f81c0aa5bb439ece86ff0897ebe8b2736931e9b02d2", "journalSequence": 180, "journalOk": true}, "after": {"state": "COMPLETED", "releaseHash": "099b54e948d90ce12c3295947c583d4032f2792490bb69f5b5e6e78f773b19a4", "reservations": [{"reservationId": "man-a:6d8c3955-37b6-4777-89cc-151c48ed1c5d:34dd09c3-8fae-4fa0-b126-89c7c93f8c48:2", "lotId": "34dd09c3-8fae-4fa0-b126-89c7c93f8c48", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"34dd09c3-8fae-4fa0-b126-89c7c93f8c48": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "201ccd07f4b40db59c465f81c0aa5bb439ece86ff0897ebe8b2736931e9b02d2", "journalSequence": 180, "journalOk": true}, "noDoubleConsume": true, "noDoubleCompletion": true, "journalOk": true, "liveMachineControl": false, "ok": true}` |
| journal after restore | REAL_LOGIC | `True` |
| restored-root health | REAL_LOGIC | `{"ok": true, "status": "REAL", "label": "REAL", "count": 180, "headHash": "201ccd07f4b40db59c465f81c0aa5bb439ece86ff0897ebe8b2736931e9b02d2", "sequence": 180}` |
| tenant leakage absent | REAL_LOGIC | `{}` |
| tenant required state preserved | REAL_LOGIC | `[]` |
| snapshot path-set bound | REAL_LOGIC | `True` |
| cross-tenant restore | REAL_LOGIC | `True` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
