# MANUAL_FACTORY_PILOT_ACCEPTANCE

generatedAt: 2026-09-09T10:54:46.854124+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 481–540 Manual Factory Pilot truth set.

| Check | Status | Evidence |
|---|---|---|
| four-family FIXTURE e2e | FIXTURE | `True` |
| operator/shift isolation | REAL_LOGIC | `disabled/closed/cross-tenant fail closed` |
| shift restart | REAL_LOGIC | `True` |
| traveler releaseHash pin | REAL_LOGIC | `09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48` |
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
| restore no double consume/complete | REAL_LOGIC | `{"stateBefore": "COMPLETED", "stateAfter": "COMPLETED", "releaseHash": "09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48", "releaseHashAfter": "09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48", "before": {"state": "COMPLETED", "releaseHash": "09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48", "reservations": [{"reservationId": "man-a:0beea259-df39-4772-8547-5b34fa494fcb:c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4:2", "lotId": "c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "4cb7007e98b0390c4667fb3cf992dad1d47099495e34aee430dbe6fd994a1255", "journalSequence": 180, "journalOk": true}, "after": {"state": "COMPLETED", "releaseHash": "09736ccddf8f0dc2afdbbc2520ad67312268d90eb014eac23e6fcab6ab952a48", "reservations": [{"reservationId": "man-a:0beea259-df39-4772-8547-5b34fa494fcb:c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4:2", "lotId": "c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4", "quantity": 2, "state": "CONSUMED"}, {"reservationId": null, "lotId": null, "quantity": 0, "state": null}], "consumedQty": 2, "lotConsumed": {"c87a98cc-00ca-4ce0-9e8e-46441c3ae6c4": 2}, "consumeEventCount": 2, "completeEventCount": 1, "journalHead": "4cb7007e98b0390c4667fb3cf992dad1d47099495e34aee430dbe6fd994a1255", "journalSequence": 180, "journalOk": true}, "noDoubleConsume": true, "noDoubleCompletion": true, "journalOk": true, "liveMachineControl": false, "ok": true}` |
| journal after restore | REAL_LOGIC | `True` |
| restored-root health | REAL_LOGIC | `{"ok": true, "status": "REAL", "label": "REAL", "count": 180, "headHash": "4cb7007e98b0390c4667fb3cf992dad1d47099495e34aee430dbe6fd994a1255", "sequence": 180}` |
| tenant leakage absent | REAL_LOGIC | `{}` |
| tenant required state preserved | REAL_LOGIC | `[]` |
| snapshot path-set bound | REAL_LOGIC | `True` |
| cross-tenant restore | REAL_LOGIC | `True` |
| evidenceCodeCommit | REAL_LOGIC | `11c79d12d06c4c6f355fd0d2dc8058f0fef2f825` |
| workingTreeClean | REAL_LOGIC | `True` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| REAL blender refresh | REAL | `unchanged render/release path; reuse 4/4 T1000 OptiX CODE 018cc70 generation c878d5f3-a3d2-44cd-8223-7b2b94d84af1` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
