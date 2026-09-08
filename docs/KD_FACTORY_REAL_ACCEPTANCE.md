# KD_FACTORY_REAL_ACCEPTANCE

generatedAt: 2026-09-08T15:35:53.392646+00:00
productionReady (scope=`coreFactoryE2E`): **True**
kdDfMReady: **True** · estimatedCostModelReady: **True** · realProviderCostReady: **False** · ciEvidenceReady: **True** (GitHub run `34245840051` on `e7d911d`, ubuntu+windows GREEN, MOCK suite) · fullAutonomousFactoryReady: **False**
Phase 130 eight-kind REAL Blender preview: **REAL**

pytest mock PASS is **not** production ready. Demand/Vision/Video remain MOCK.

| Check | Status | Evidence |
|---|---|---|
| Blender | REAL | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| OptiX | REAL | `NVIDIA T1000` |
| 3 KD SKU families | REAL | `BEDSIDE_CABINET,OPEN_SHELF,STUDENT_DESK` |
| quantity batch nesting | REAL | `q=10 sheets=5 util=0.7098` |
| cross-SKU nesting | REAL | `sheets=8 waste=0.0792` |
| waste V2 conservation | REAL | `err=0.0 trueWaste=0.0375 remnant=0.6112` |
| remnants extract+consume | REAL | `extracted=7 savedSheets=1 consumed=480720.0` |
| pack/weight/assembly | REAL | `carton=424.0x424.0x180.0 kg=12.699 score=0.5947` |
| landed cost lineage | REAL | `cost=1448.69 hashes=['engineeringHash', 'bomHash', 'nestingHash', 'packagingHash']` |
| Phase 130 eight KD Blender previews | REAL | `real=8/8` |
| WAITING_PRODUCT_APPROVAL | REAL | `WAITING_PRODUCT_APPROVAL` |
| Vision Judge | MOCK | `no live provider` |
| AI Video | MOCK | `no ProviderAdapter` |
| Demand | MOCK | `DemandSignalProvider UNAVAILABLE` |
| OS sandbox | PARTIAL | `path guard only` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| small-space catalog | REAL | `n=24 kinds=['APPLIANCE_RACK', 'BEDSIDE_CABINET', 'DESK_RISER', 'GARMENT_RACK', 'MOBILE_SIDE_TABLE', 'NARROW_BOOKCASE', 'OPEN_SHELF', 'PET_FURNITURE', 'RETAIL_DISPLAY', 'STORAGE_BENCH', 'STUDENT_DESK',` |
| CI evidence | REAL (MOCK suite) | `run 34245840051 success ubuntu+windows @ e7d911d` |
| scoped readiness | REAL | `{"coreFactoryE2EReady": true, "kdDfMReady": true, "estimatedCostModelReady": true, "realProviderCostReady": false, "commercialQuoteReady": false, "ciEvidenceReady": false, "fullAutonomousFactoryReady"` |

LIVE_CNC remains **BLOCKED**. Approval stops at WAITING_PRODUCT_APPROVAL / APPROVED_FOR_PROTOTYPE.
