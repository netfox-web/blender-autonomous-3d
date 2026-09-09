# PILOT_BACKUP_RESTORE_ACCEPTANCE

generatedAt: 2026-09-09T07:15:44.223288+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 481–540 Manual Factory Pilot truth set.

| Check | Status | Evidence |
|---|---|---|
| backup checksum | REAL_LOGIC | `True` |
| restore releaseHash | REAL_LOGIC | `True` |
| restore no double consume/complete | REAL_LOGIC | `{"ok": true, "stateBefore": "COMPLETED", "stateAfter": "COMPLETED", "consumedBefore": true, "consumedAfter": true, "releaseHash": "4be1aa5a51d71add3c664067dbaa185e3dff73d4c65a73aef0b9a58a4de99ad6", "releaseHashAfter": "4be1aa5a51d71add3c664067dbaa185e3dff73d4c65a73aef0b9a58a4de99ad6", "noDoubleConsume": true, "noDoubleCompletion": true, "journalOk": true, "conserved": true, "liveMachineControl": false}` |
| journal after restore | REAL_LOGIC | `True` |
| cross-tenant restore | REAL_LOGIC | `True` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
