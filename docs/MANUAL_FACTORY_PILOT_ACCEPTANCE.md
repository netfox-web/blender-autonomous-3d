# MANUAL_FACTORY_PILOT_ACCEPTANCE

generatedAt: 2026-09-09T07:15:44.223288+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 481–540 Manual Factory Pilot truth set.

| Check | Status | Evidence |
|---|---|---|
| four-family FIXTURE e2e | FIXTURE | `True` |
| operator/shift isolation | REAL_LOGIC | `disabled/closed/cross-tenant fail closed` |
| shift restart | REAL_LOGIC | `True` |
| traveler releaseHash pin | REAL_LOGIC | `4be1aa5a51d71add3c664067dbaa185e3dff73d4c65a73aef0b9a58a4de99ad6` |
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
| restore no double consume/complete | REAL_LOGIC | `{"ok": true, "stateBefore": "COMPLETED", "stateAfter": "COMPLETED", "consumedBefore": true, "consumedAfter": true, "releaseHash": "4be1aa5a51d71add3c664067dbaa185e3dff73d4c65a73aef0b9a58a4de99ad6", "releaseHashAfter": "4be1aa5a51d71add3c664067dbaa185e3dff73d4c65a73aef0b9a58a4de99ad6", "noDoubleConsume": true, "noDoubleCompletion": true, "journalOk": true, "conserved": true, "liveMachineControl": false}` |
| journal after restore | REAL_LOGIC | `True` |
| cross-tenant restore | REAL_LOGIC | `True` |
| evidenceCodeCommit | REAL_LOGIC | `523b3cb2ed1dc960785fcea43256198425d2e77e` |
| workingTreeClean | REAL_LOGIC | `True` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| REAL blender refresh | REAL | `unchanged render/release path; reuse 4/4 T1000 OptiX CODE 018cc70 generation c878d5f3-a3d2-44cd-8223-7b2b94d84af1` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
