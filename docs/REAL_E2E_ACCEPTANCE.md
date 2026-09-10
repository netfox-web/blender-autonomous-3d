# REAL_E2E_ACCEPTANCE

Scoped readiness (not a global Production Ready flag):
- `coreRenderE2EReady`: **true** — Blender 5.2.1 + T1000 OptiX smoke/preview/360/parametric PNG
- `physicalProductOsPrototypeReady`: **true** — KD/retail/packaging/acrylic prototype E2E with Human Approval Gate
- `manufacturingReleasePackageReady`: **true** — see `docs/MANUFACTURING_RELEASE_REAL_ACCEPTANCE.md` (CODE `018cc70`, 4/4 T1000 OptiX, release-bound)
- `manualPilotOpsReady`: **true** — see `docs/PILOT_OPERATIONS_ACCEPTANCE.md` (manual execution, not live factory)
- `pilotReliabilityReady`: **FIXTURE** — see `docs/PILOT_RELIABILITY_ACCEPTANCE.md` (50 WO stress, not factory throughput)
- `pilotDeploymentReady`: **FIXTURE** — see `docs/PILOT_DEPLOYMENT_ACCEPTANCE.md` (110 WO FIXTURE/CHAOS, not factory throughput)
- `operatorControlReady`: **true** (scoped) — see `docs/OPERATOR_CONTROL_ACCEPTANCE.md` (scan/dispatch/health; barcode hardware PARTIAL)
- `qcTraceabilityReady`: **true** — see `docs/QC_TRACEABILITY_ACCEPTANCE.md`
- `manualFactoryPilotReady`: **FIXTURE / REAL_LOGIC** (scoped, not Production Ready) — see `docs/MANUAL_FACTORY_PILOT_ACCEPTANCE.md` (CODE `11c79d1`, generation `2d0cc206-ed80-4c32-a82f-491ae8842220`; REAL blender reused `018cc70`)
- `skuPortfolioFactoryReady`: **FIXTURE / REAL_LOGIC** (scoped, not Production Ready) — see `docs/SKU_PORTFOLIO_FACTORY_ACCEPTANCE.md` (CODE `7a87ea5`, generation `0b76b09e-02a8-45a6-b4fd-bf34849dd76c`; 4/4 T1000 OptiX media with per-case SHA/size/job/GPU)
- `prototypeValidationReady`: **FIXTURE / REAL_LOGIC** (scoped, not Production Ready) — see `docs/PROTOTYPE_VALIDATION_ACCEPTANCE.md` (CODE `7060037`, generation `627491fc-5853-4c4d-8325-71d0eb406d5c`; `physicalPrototypeValidated=false`; `launchDecision=WAITING_HUMAN_EVIDENCE`; packaging/labor canonical authority binding fail-closed; prior REAL blender verified `7a87ea5` 4/4 T1000 OptiX)
- `pilotBatchExecutionReady`: **FIXTURE / REAL_LOGIC** (scoped, not Production Ready) — see `docs/PILOT_BATCH_EXECUTION_ACCEPTANCE.md` (CODE `12ef546`, generation `4c1fa7ed-…`)
- `surfaceDecorationLogicReady`: **REAL_LOGIC** — see `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md` (CODE `7d99b37`, generation `97e76079-0527-4313-ad37-6b1bd050a268`; preview artifact/device/final UV identity; SINGLE_SURFACE crop re-derive; MASTER relation authority; Mock preview; `physicalPrintValidated=false`)
- `productionArtworkFileReady`: **REAL_LOGIC / GENERATED** (file package + hash, not physical print)
- `realArtworkPreviewReady`: **false / MOCK** this round (`FOX3D_MOCK_BLENDER=1` / Platform mock)
- `physicalPrintValidated`: **false**
- `commercialLaunchGovernanceReady`: **FIXTURE / REAL_LOGIC** (scoped, not Production Ready) — see `docs/COMMERCIAL_LAUNCH_READINESS_ACCEPTANCE.md` (`HUMAN_BATCH_GO` not issued on fixture; live flags false)
- `physicalPrototypeEvidenceReady`: **FIXTURE / REAL_LOGIC** (scoped, not Production Ready) — see `docs/PHYSICAL_PROTOTYPE_EVIDENCE_ACCEPTANCE.md` (software gates only; not physical REAL)
- `humanLaunchGateReady`: **FIXTURE / REAL_LOGIC** (scoped, not Production Ready) — see `docs/HUMAN_LAUNCH_GATE_ACCEPTANCE.md` (`WAITING_HUMAN_EVIDENCE`; no HUMAN_GO on fixture)
- `operatorShiftReady`: **REAL_LOGIC / MANUAL_IDENTITY** — see `docs/OPERATOR_SHIFT_ACCEPTANCE.md`
- `inventoryReconciliationReady`: **REAL_LOGIC / MANUAL** — see `docs/INVENTORY_RECONCILIATION_ACCEPTANCE.md`
- `pilotBackupRestoreReady`: **REAL_LOGIC** (local operational, not cloud HA/DR) — see `docs/PILOT_BACKUP_RESTORE_ACCEPTANCE.md`
- `liveFactoryExecutionReady`: **false**
- `globalProductionReady`: **false** — Vision/Demand/live provider cost/OS jail/LIVE_CNC are not REAL
- `fullAutonomousFactoryReady`: **false**

`productionReady` without a scope is forbidden. Mock pytest is not production evidence.

| Check | Status | Evidence |
|---|---|---|
| Blender executable | REAL | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| blender --version | REAL | `5.2.1` |
| NVIDIA GPU / VRAM | REAL | `NVIDIA T1000 4.0GB driver=596.86` |
| Cycles devices | REAL | `[{"name": "NVIDIA T1000", "type": "CUDA", "kind": "OPTIX"}, {"name": "Intel Core i9-14900K", "type": "CPU", "kind": "OPTIX"}, {"name": "NVIDIA T1000", "type": "OPTIX", "kind": "OPTIX"}, {"name": "NVIDIA T1000", "type": "CUDA", "kind": "CUDA"}, {"name": "Intel Core i9-14900K", "type": "CPU", "kind": "CUDA"}, {"name": "NVIDIA T1000", "type": "OPTIX", "kind": "CUDA"}, {"name": "NVIDIA T1000", "type":` |
| OptiX | REAL | `realOptix=true` |
| REAL_SMOKE_TEST (cube/plane/camera/3-point/Cycles/OptiX/512 PNG) | REAL | `status=completed error=None blender=5.2.1 LTS device=OPTIX mock=False` |
| PRODUCT_E2E WHITE_STUDIO | REAL | `status=completed error=None preview=43f015d5-030c-4012-afa6-e0937b68a235` |
| PRODUCT_360_E2E 36 frames | REAL | `status=completed frames={'frames': ['bb1b0915-b80e-4268-a67a-f8ff12875950', '661d31d3-7bf7-4e7e-b572-b26d0b485bcd', 'b3c196e0-d53d-4e15-b868-576ec3cf53d2', '1d287a8d-cb4d-4a27-863e-c908326b148d', '10554b84-a528-4787-9c8a-1f961b1676d7', '0618024f-3eb2-412a-bb7f-8c55e2eadb4f', 'e699ed5e-65a3-4c50-a78d-2d2c1b4c20ca', '4de0fc1b-968b-4568-8f57-233295f7302e', '33620412-0928-4751-a872-5e9a7a692194', 'ec2` |
| PARAMETRIC STORAGE_CABINET 800x1800x400 | REAL | `hash=c1edaa908b44aa1656158a279bd4dead92bf71f826adbf72a932546db2b78074 job=completed` |
| Cabinet resize 800→1200 geometry+BOM sync | REAL | `top800={'partId': 'top', 'partName': 'TOP', 'length': 800.0, 'width': 400.0, 'thickness': 18.0, 'quantity': 1, 'role': 'top', 'edgeBanding': True} top1200={'partId': 'top', 'partName': 'TOP', 'length': 1200.0, 'width': 400.0, 'thickness': 18.0, 'quantity': 1, 'role': 'top', 'edgeBanding': True} bomHashChanged=True` |
| Cabinet resize rebuild render | REAL | `status=completed` |
| Exploded view / assembly placeholders | REAL | `status=completed` |
| NL furniture → DesignIntent → validate → BOM → cost | REAL | `kind=STORAGE_CABINET width=1200.0 llmDirectManufacturing=false` |

## Flags
- realBlender: True
- realGPU: True
- realCycles: True
- realOptix: True
- realRenderOutput: True
- queueIntegrated: True
- damIntegrated: True
- blocked: []

Worker on this host is `local-t1000` (real nvidia-smi). There is no RTX 5090; `local-5090` / `mock-4.2` are not registered in production.

Mock Worker 僅供 `pytest`。Production acceptance 不得把 mock-4.2 寫成 PASS。

Furniture factory Phase 71–120 evidence: `docs/FURNITURE_FACTORY_REAL_ACCEPTANCE.md` (`productionReady` scope = `coreFactoryE2E` only).

KD / flat-pack Phase 121–180 evidence: `docs/KD_FACTORY_REAL_ACCEPTANCE.md`. Waste V2 splits reusable remnant vs true scrap. Vision Judge, AI Video, and demand remain **MOCK**. LIVE_CNC remains **BLOCKED**. `fullAutonomousFactoryReady=false`. `ciEvidenceReady` is **true** for MOCK-suite GitHub Actions run `34245840051` on `e7d911d` (ubuntu+windows GREEN). That is not REAL Blender production. Cost model is `CONFIG_ESTIMATE_ONLY`.

Physical Product OS Phase 181–240 evidence: `docs/PHYSICAL_PRODUCT_OS_REAL_ACCEPTANCE.md` (+ material/nesting/retail/packaging JSON). Scope is prototype / Human Approval Gate only. Retail 6/6 and acrylic 3/3 REAL T1000 OptiX previews. Packaging strength and print preflight stay **PARTIAL**. LIVE_LASER/CNC **BLOCKED**.

Phase 241–300 evidence: `docs/PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.md` (+ release/cost/packaging V2 JSON). REAL Blender EvidenceBundles bind to **CODE_EVIDENCE_SHA** `513ae9d` on a clean tree (`workingTreeClean=true`); runner is fail-closed and publishes canonical files atomically (shared `acceptanceGenerationId`). `globalProductionReady=false`. `fullAutonomousFactoryReady=false`. CI GREEN is MOCK-suite only.

Phase 361–420 final integrity (`1129ae6`) clean-tree REAL: CODE_EVIDENCE_SHA `997db345183367709597738c12c65bbf6800ae4c`; generation `1cb61fad-63ba-4158-bf2e-4abfd3663d36`; 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX EvidenceBundles, `usedMock=false`, verifier PASS, exact `commitSha=997db34`, non-null matching ManufacturingRelease `releaseHash`. Reliability stress is actual FIXTURE (50 WO / 652 ops), not a fabricated fallback. `liveFactoryExecutionReady=false`. `fullAutonomousFactoryReady=false`. `globalProductionReady=false`.
