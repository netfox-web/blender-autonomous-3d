# SKU_PORTFOLIO_FACTORY_ACCEPTANCE

generatedAt: 2026-09-09T11:36:46.590800+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 541–600 Small-Space KD SKU Portfolio Factory truth set.

| Check | Status | Evidence |
|---|---|---|
| >=24 candidates / >=6 kinds | REAL_LOGIC | `n=28 kinds=['BEDSIDE_CABINET', 'DESK_RISER', 'MOBILE_SIDE_TABLE', 'NARROW_BOOKCASE', 'OPEN_SHELF', 'PET_FURNITURE', 'STORAGE_BENCH', 'STUDENT_DESK']` |
| invalid retained, not in Top 10 | REAL_LOGIC | `rejected=3 invalidInTop=0` |
| Top 10 deterministic | REAL_LOGIC | `a37ef2919e93bd2b44891fcb84a9ee569f003ad64fa62d5063c984e5b787f017` |
| DFM conservation | REAL_LOGIC | `True` |
| cross-SKU planning no consume | REAL_LOGIC | `{"sheetCountDelta": -15, "consumesInventory": false, "doubleAllocation": false}` |
| commercial truth labels | CONFIG_ESTIMATE | `MOCK` |
| MOCK demand not REAL | REAL_LOGIC | `MOCK` |
| tenant isolation | REAL_LOGIC | `True` |
| tenant backup semantic | REAL_LOGIC | `{"liveA": "bd5a9bb260a53ee982aaa9a1f3ea56fd8fcdc3c79a6c5bdfa0d77ac0cf5174c7", "restoredA": "bd5a9bb260a53ee982aaa9a1f3ea56fd8fcdc3c79a6c5bdfa0d77ac0cf5174c7", "equal": true}` |
| manual prototype approval | REAL_LOGIC | `READY_FOR_MANUAL_PROTOTYPE` |
| REAL blender media | REAL | `real=4/4` |
| evidenceCodeCommit | REAL_LOGIC | `655ea994bdd7e5505324b10ea02f0166abefb08e` |
| workingTreeClean | REAL_LOGIC | `True` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
