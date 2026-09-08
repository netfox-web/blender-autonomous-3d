# REAL_E2E_ACCEPTANCE

Scoped readiness (not a global Production Ready flag):
- `coreRenderE2EReady`: **true** — Blender 5.2.1 + T1000 OptiX smoke/preview/360/parametric PNG
- `physicalProductOsPrototypeReady`: **true** — KD/retail/packaging/acrylic prototype E2E with Human Approval Gate
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
