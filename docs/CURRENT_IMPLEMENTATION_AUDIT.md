# CURRENT_IMPLEMENTATION_AUDIT

Audit of `main` (`7e1d11c` + local gap-fill) against `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`.
Labels follow the instruction: **REAL / PARTIAL / MOCK / STUB / MISSING / BLOCKED**.
Seeing a class, route, or UI table is not enough — status is from the execution path.

This machine (2026-09-08): Blender 5.2.1 LTS at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`, NVIDIA T1000 4GB driver 596.86, Cycles OptiX devices present. No RTX 5090.

## Mock vs Real split

| Path | Status |
|---|---|
| `pytest` (`Platform(mock_blender=True)`) | **MOCK** — allowed for automated tests |
| Production API (`Platform(mock_blender=False)` + `register_detected_workers`) | **REAL** — no mock fallback; missing Blender/OptiX → `BLOCKED_*` |
| Hardcoded `local-mock` / `mock-4.2` / fake 5090 in production | **REAL** (removed from production bootstrap) |

## Phase 1–40 (existing engine)

| Item | Status | Evidence |
|---|---|---|
| FoxStudio/Fleet adapters, no second scheduler | REAL | `src/fox3d/infra.py`, `integrations.py` |
| Scene DSL / studio recipes | REAL | `scene.py`, `studio.py` |
| Digital Twin + DAM | REAL | `twin.py`, `DAM.put/get` writes bytes under `.fox3d-data/dam` |
| Parametric cabinet + rules + BOM + cost | REAL | `parametric.py`; resize 800→1200 changes TOP length 800→1200 and BOM hash |
| NL DesignIntent | REAL | `parse_design_intent`; LLM cannot set manufacturing mm |
| Headless `blender -b --factory-startup -P` | REAL | `scripts/blender_job.py`, `BlenderRuntime._real_render` |
| Mock renderer | MOCK | `BlenderRuntime._mock_render` only when `force_mock=True` |

## Phase 41–50 Real Blender E2E

| Phase | Status | Notes |
|---|---|---|
| 41 Blender discovery | REAL | `find_blender` + `blender -b --version`; missing → `BLOCKED_NO_BLENDER` |
| 42 GPU discovery | PARTIAL→gap fill | Had name/VRAM total/driver via nvidia-smi. **Gap:** UUID, VRAM used/free, `discoverySource` |
| 43 Cycles/OptiX probe | REAL | `blender -b --factory-startup -P blender_job.py -- --probe`; no OptiX → `BLOCKED_NO_OPTIX`; no silent CPU PASS |
| 44 Smoke Cube/Plane/Camera/3pt/Cycles/OptiX/512 PNG | REAL | jobType `REAL_SMOKE_TEST`; PNG `\x89PNG`; **Gap:** GPU UUID / output hash/size on job row |
| 45 Queue lifecycle | PARTIAL→gap fill | QUEUED→RESERVED→RUNNING→RENDERING→UPLOADING→COMPLETED + retry/cancel/timeout/heartbeat/offline. **Gap:** `DISPATCHED` |
| 46 Admin workers | PARTIAL→gap fill | Shows GPU, Blender version, OptiX, realBlender. **Gap:** hostname, OS, VRAM used/free, current job, last heartbeat, REAL/MOCK badge |
| 47 Digital Twin GLB E2E | REAL | `POST /api/digital-twins/upload` → DAM → twin → Blender import → preview PNG |
| 48 WHITE_STUDIO | REAL | `product_e2e` uses WHITE_STUDIO + THREE_POINT + Cycles OptiX |
| 49 PRODUCT_360 | REAL | 36 frames + MP4 (`ftyp`) in DAM |
| 50 REAL_E2E_ACCEPTANCE.md | REAL | `docs/REAL_E2E_ACCEPTANCE.md`; flags include realBlender/GPU/Cycles/OptiX/RenderOutput. **Gap:** explicit `queueIntegrated` / `damIntegrated` |

## Phase 51–65 Parametric

| Phase | Status | Notes |
|---|---|---|
| 51 Engineering SoT | REAL | `CabinetSpec` / `ParametricProduct`; Blender consumes JSON only |
| 52 STORAGE_CABINET V1 | REAL | left/right/top/bottom/back/shelves/doors generated from params |
| 53 BOM | PARTIAL→gap fill | Same engineering hash; **Gap:** `partType` field name |
| 54 Resize 800→1200 | REAL | TOP 800→1200; BOM hash changes; preview re-render |
| 55 Rule engine | REAL | thickness, door, shelf span, collision, max panel |
| 56 WOOD_* materials | PARTIAL→gap fill | generic `wood`/`white_wood`; **Gap:** WOOD_WHITE/OAK/WALNUT/BLACK/CREAM catalog |
| 57 Cost | REAL | Material/Hardware/Processing/Assembly/Packaging/Shipping |
| 58 Door/drawer/hardware | REAL | doors, drawers, hinge/handle placeholders, collision codes |
| 59 Exploded/assembly | PARTIAL | exploded offsets + Blender explode flag; assembly graph exists; MP4 assembly not always produced |
| 60 CABINET_REAL_ACCEPTANCE.md | MISSING→add | |
| 61 NL cabinet | REAL | 120cm/180cm/40cm → 1200/1800/400 mm STORAGE_CABINET |
| 62 Variants | REAL | preview-only generator |
| 63 Vision Judge | MOCK | heuristic scores; not a live vision model (honest) |
| 64 Product R&D Agent | REAL | pipeline + `WAITING_APPROVAL` / `HUMAN_APPROVAL_REQUIRED` |
| 65 CNC/CAM boundary | PARTIAL→gap fill | CAM/CNC/Nesting adapters, `liveMachineControl=False`. **Gap:** `CADAdapter` name |

## Phase 66–70 extensions

| Phase | Status |
|---|---|
| 66 Packaging twin | REAL architecture — same `TwinStore`; BOX/BOTTLE/… metadata on ProductDigitalTwin; preview via existing queue. Render REAL only when production worker (not pytest mock). |
| 67 Blender→AI Video | PARTIAL — Blender START/MID/END + mask via headless worker (REAL in production). AI Video Gateway **MOCK** unless a live adapter is registered. Not hardcoded to H3/LTX. |
| 68 Synthetic data | PARTIAL — RGB REAL; mask REAL (emission pass) in production. depth/normal/segmentation listed as `notProducedThisRun` until compositor AOVs. Manifest stored in DAM. |
| 69 Recipe research | REAL — EXPERIMENTAL→CANDIDATE; cannot overwrite PRODUCTION |
| 70 Hardening | REAL for path traversal guard, script SANDBOX ONLY, cancel, GPU reservation release, temp log cleanup, lineage, cache, lease recovery. Not a full OS sandbox. |

## Blockers

- No RTX 5090 on this host. Worker key is `local-t1000` from real nvidia-smi. **Not BLOCKED** — discovery is honest.
- Vision Judge is heuristic (**MOCK** for the vision-model slice only).
- Live CNC is forbidden this round (**correct**).

## Do not redo

Blender discovery, OptiX probe, smoke render, WHITE_STUDIO, 360, DAM, parametric geometry/BOM/cost/NL, production no-mock-fallback.
