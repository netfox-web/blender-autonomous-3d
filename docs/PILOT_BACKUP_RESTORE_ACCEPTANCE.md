# PILOT_BACKUP_RESTORE_ACCEPTANCE

generatedAt: 2026-09-09T10:54:46.854124+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 481–540 Manual Factory Pilot truth set.

| Check | Status | Evidence |
|---|---|---|
| backup checksum | REAL_LOGIC | `True` |
| restore releaseHash | REAL_LOGIC | `True` |
| restore no double consume/complete | REAL_LOGIC | `{"stateBefore": "COMPLETED", "stateAfter": "COMPLETED", "releaseHash": "09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48", "releaseHashAfter": "09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48", "before": {"state": "COMPLETED", "releaseHash": "09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48", "reservations": [{"reservationId": "man-a:0beea259-df39-4772-8547-5b34fa494fcb:c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4:2", "lotId": "c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "4cb7007e98b0390c4667fb3cf992dad1d47099495e34aee430dbe6fd994a1255", "journalSequence": 180, "journalOk": true}, "after": {"state": "COMPLETED", "releaseHash": "09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48", "reservations": [{"reservationId": "man-a:0beea259-df39-4772-8547-5b34fa494fcb:c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4:2", "lotId": "c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "4cb7007e98b0390c4667fb3cf992dad1d47099495e34aee430dbe6fd994a1255", "journalSequence": 180, "journalOk": true}, "noDoubleConsume": true, "noDoubleCompletion": true, "journalOk": true, "liveMachineControl": false, "ok": true}` |
| journal after restore | REAL_LOGIC | `True` |
| restored-root health | REAL_LOGIC | `{"ok": true, "status": "REAL", "label": "REAL", "count": 180, "headHash": "4cb7007e98b0390c4667fb3cf992dad1d47099495e34aee430dbe6fd994a1255", "sequence": 180}` |
| tenant leakage absent | REAL_LOGIC | `{}` |
| tenant required state preserved | REAL_LOGIC | `[]` |
| snapshot path-set bound | REAL_LOGIC | `True` |
| cross-tenant restore | REAL_LOGIC | `True` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
