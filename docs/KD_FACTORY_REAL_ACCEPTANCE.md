# KD_FACTORY_REAL_ACCEPTANCE

generatedAt: 2026-09-08T14:40:57.418501+00:00
productionReady (scope=`coreFactoryE2E`): **True**
kdDfMReady: **True** · commercialCostModelReady: **True** · fullAutonomousFactoryReady: **False**

pytest mock PASS is **not** production ready. Demand/Vision/Video remain MOCK.

| Check | Status | Evidence |
|---|---|---|
| Blender | REAL | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| OptiX | REAL | `NVIDIA T1000` |
| 3 KD SKU families | REAL | `BEDSIDE_CABINET,OPEN_SHELF,STUDENT_DESK` |
| quantity batch nesting | REAL | `q=10 sheets=5 util=0.7098` |
| cross-SKU nesting | REAL | `sheets=7 waste=0.1026` |
| waste V2 conservation | REAL | `err=0.0 trueWaste=0.053 remnant=0.2601` |
| remnants extract+consume | REAL | `extracted=4 savedSheets=1 consumed=480720.0` |
| pack/weight/assembly | REAL | `carton=424.0x424.0x180.0 kg=12.699 score=0.5947` |
| landed cost lineage | REAL | `cost=1448.69 hashes=['engineeringHash', 'bomHash', 'nestingHash', 'packagingHash']` |
| Blender KD product preview | REAL | `status=completed job=c132b8fc-eb70-46f1-a26d-238d4f46fb65` |
| WAITING_PRODUCT_APPROVAL | REAL | `WAITING_PRODUCT_APPROVAL` |
| Vision Judge | MOCK | `no live provider` |
| AI Video | MOCK | `no ProviderAdapter` |
| Demand | MOCK | `DemandSignalProvider UNAVAILABLE` |
| OS sandbox | PARTIAL | `path guard only` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| small-space catalog | REAL | `n=24 kinds=['APPLIANCE_RACK', 'BEDSIDE_CABINET', 'DESK_RISER', 'GARMENT_RACK', 'MOBILE_SIDE_TABLE', 'NARROW_BOOKCASE', 'OPEN_SHELF', 'PET_FURNITURE', 'RETAIL_DISPLAY', 'STORAGE_BENCH', 'STUDENT_DESK',` |
| scoped readiness | REAL | `{"coreFactoryE2EReady": true, "kdDfMReady": true, "commercialCostModelReady": true, "liveVisionReady": false, "liveVideoReady": false, "osSandboxReady": false, "liveMachineControlReady": false, "ciEvi` |

LIVE_CNC remains **BLOCKED**. Approval stops at WAITING_PRODUCT_APPROVAL / APPROVED_FOR_PROTOTYPE.
