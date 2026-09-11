# CURRENT_IMPLEMENTATION_AUDIT

Audit of `main` (Phase 781–840 Re-Gate Round 9 CODE_EVIDENCE_SHA `e3eddd3`; prior `818dac8` / instruction `157532c`) against `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` @ `157532c`. Historical Phase 1–780 notes below remain. Scheduler/Queue/DAM/Recipe/TwinStore/CabinetSpec were not rewritten.
Labels follow the instruction: **REAL / PARTIAL / MOCK / STUB / MISSING / BLOCKED**.
Seeing a class, route, or UI table is not enough — status is from the execution path.

This machine (2026-09-10): Blender 5.2.1 LTS at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`, NVIDIA T1000 4GB driver 596.86, Cycles OptiX devices present. No RTX 5090.

## Phase 781–840 Artwork Placement / Surface Decoration Engine V1

| Item | Status | Evidence |
|---|---|---|
| PrintableSurface | REAL_LOGIC | derived from CabinetSpec/acrylic/packaging/retail components; surfaceHash |
| Artwork asset | REAL_LOGIC | DAM sha256/size/mime/pixels; tamper fail-closed |
| ArtworkPlacement | REAL_LOGIC | mm SOT; CONTAIN/COVER; STRETCH blocked; hash binds uv/mirror/object/relation |
| mm↔UV | REAL_LOGIC | round-trip 0.001 mm; local unit-square quarter-turn; identity shader |
| Keep-out / DPI | CONFIG / PARTIAL | handle/hinge CONFIG; DPI policy CONFIG 150/72; printPreflight PARTIAL |
| 4-door master | REAL_LOGIC | 2400×1800 / 4×600; exact quarters `0/.25/.5/.75`; MASTER_SPLIT only |
| SINGLE_SURFACE | REAL_LOGIC | CONTAIN full-canvas letterbox; COVER anchor crop; rotation/mirror vs finalUvHash; not sibling quarter |
| Production artwork | REAL_LOGIC / GENERATED | full-panel PNG + canvas/placed/transformHash; not physical print |
| Blender preview | MOCK | live-only path; worker artworkSha256 of loaded bytes; realArtworkPreviewReady=false |
| Blender door mesh | REAL_LOGIC | engineering component face mm; no hidden -0.002 m |
| Production authority | REAL_LOGIC | local UV bounds; landmark oracle; derived masterId in relationHash; required scenarios fail-closed |
| physicalPrintValidated | false | no print/proof evidence |
| 837–840 acceptance | FIXTURE + REAL_LOGIC | generation `fcfca28e-…`; CODE `e3eddd3`; strict serialized types + tamper fail-closed |

## Phase 721–780 Manual Pilot Batch Execution & Commercial Launch Readiness V1

| Item | Status | Evidence |
|---|---|---|
| PilotBatchSpec | REAL_LOGIC | tenant-scoped batch + unitExecutionId; MANUAL requires HUMAN_GO; FIXTURE cannot inherit GO |
| Batch material plan | REAL_LOGIC | WorkOrder reserve/consume; STRICT_STOCK shortage rolls back; FIXTURE_AUTO_SEED labeled FIXTURE |
| MANUAL_STATION execution | REAL_LOGIC | start/consume/labor idempotent; liveMachineControl=false |
| QC sampling / genealogy | REAL_LOGIC / CONFIG | operational sampleEvery; not ISO/AQL; failed QC holds batch |
| Packing / cartons | REAL_LOGIC | unique unit-to-carton; shipment DRAFT; no booked carrier |
| Batch cost | PARTIAL on fixture | four money fields without packaging qty stay PARTIAL |
| Human batch board | REAL_LOGIC | WAITING_HUMAN_EVIDENCE on fixture; HUMAN_BATCH_GO blocked |
| Canonical authority | REAL_LOGIC | exact-set batch/unit/carton/labor/QC/material/cost/decision/workOrder/bom/checklist; carton L/W/H/weight + required source/truthLabel; WO durable reservation/consume snapshot independent of projection; BOM lines hash + checklist identity published |
| HUMAN_BATCH_GO gates | REAL_LOGIC | FINAL QC + pinned qcPlanHash from workOrders; pack requires measurements/execution chain; MANUAL qty/checklist/DAM |
| Crash matrix | REAL_LOGIC | subprocess os._exit after-business-persist and after-outbox-complete on create/release/reserve/start/consume/labor/QC/pack/GO |
| MANUAL checklist identity | REAL_LOGIC | exactly one checklist; exact tenant/unit/hash; bogus ID BLOCK; `_carton_packaging_ok` re-resolves |
| Canonical QC PASS | REAL_LOGIC | sampled FINAL must be PASS + qcId/WO/release/qcPlanHash pinned to workOrders snapshot; coordinated copy tamper fail-closed |
| Board/decision authority | REAL_LOGIC | DERIVED_READINESS WAITING on fixture; blockers recomputed `{fixture_evidence, cost_partial}`; coordinated state/blocker fail-closed |
| Execution completeness | REAL_LOGIC | requested == unit set == start/consume `_qty_ok`/labor/QC/carton; PLANNED skip fail-closed |
| Cost lineage | PARTIAL on fixture | quantityLineage recomputes IDs/minutes/qty from WO + BOM authority + checklist authority; fixture packagingQty MISSING → ok=false; hardware BOM only if unique BOM lines recompute expected and observed exact-match (live fixture observed 4 vs BOM 32/36 → MISSING, not faked) |
| BOM canonical authority | REAL_LOGIC | `bomAuthority` lines hashed with existing `stable_hash`; carton expected from BOM not carton copy; coordinated fake expected/observed fail-closed |
| Packaging checklist canonical | REAL_LOGIC | published Prototype checklist identity/qty/source + PACKAGING DAM sha/size; FIXTURE source stays MISSING; fake id / duplicate / lineage mismatch fail-closed |
| WO nested owner | REAL_LOGIC | reservation/consumed snapshot owner derived from durable parent; blank tenantId/workOrderId fail-closed |
| Backup/restore | REAL_LOGIC | batches/units/cartons/decisions/ncrs/costs in digest; equal `88986645…` |
| 775–780 acceptance | FIXTURE + REAL_LOGIC | generation `4c1fa7ed-…`; CODE `12ef546`; Actions `34481806339` exact CODE SHA Ubuntu+Windows SUCCESS; 4×5 units; `physicalPilotBatchValidated=false` |

## Phase 661–720 Physical Prototype Evidence & Human Launch Governance V1

| Item | Status | Evidence |
|---|---|---|
| Required DAM roles | REAL_LOGIC | AS_BUILT + PACKAGING SHA/size from DAM; zero DAM cannot PASS_AS_BUILT / HUMAN_GO |
| Cost qty + money | REAL_LOGIC / PARTIAL | COMPLETE needs MaterialLot consume + unique durable labor + hardware qty + explicit packagingQty bound to checklist/unit/engineering; four amounts alone PARTIAL |
| Packaging canonical lineage | REAL_LOGIC | published `packagingChecklistAuthority` + `packagingLineage`; COMPLETE/HUMAN_GO resolves exactly one checklist by ID; coordinated bogus IDs / blank tenant fail-closed |
| Labor uniqueness | REAL_LOGIC | published `laborAuthority` durable rows; verifier rebuilds semantic keys/totals; fake unique lineage and duplicate semantic identity fail-closed |
| Journal crash window | REAL_LOGIC | emit PREPARED→persist→journal→after-outbox-complete; labor idem inside persist; finalize/HUMAN_GO/pilot-plan/ECO subprocess `os._exit` |
| PhysicalEvidencePackage | REAL_LOGIC | tenant-scoped lineage + source + finalize/supersede; fixture cannot MANUAL_EVIDENCE |
| Human launch board | REAL_LOGIC | WAITING_HUMAN_EVIDENCE / HOLD_REWORK / READY_FOR_HUMAN_GO_NO_GO / HUMAN_GO / HUMAN_NO_GO |
| Manual pilot plan | REAL_LOGIC | HUMAN_GO only; ManufacturingRelease + WorkOrder MANUAL_STATION; liveMachineControl=false |
| Backup/restore | REAL_LOGIC | packages/launchDecisions/pilotPlans/labor semantic keys + packaging checklist identity/source in tenant digest; equal `a9078fe7…` |
| 719–720 acceptance | FIXTURE + REAL_LOGIC | generation `627491fc-…`; CODE `7060037`; `physicalPrototypeValidated=false`; `launchDecision=WAITING_HUMAN_EVIDENCE` |

## Phase 601–660 Prototype Validation published lineage + intent identity

| Item | Status | Evidence |
|---|---|---|
| Published canonical 1:1 lineage | REAL_LOGIC | selected/units/matrix/selectedBoard publish non-null lineage hashes; post-serialize/post-publish re-validation |
| inventoryIntent identity | REAL_LOGIC | pointer reuse requires tenant/unit/WO/qty/material/thickness/grain/size; duplicate HOLD |
| Pre-intent reservation crash | REAL_LOGIC | PREPARED intent before allocate; restart binds existing MaterialLot RESERVED/CONSUMED |
| Packaging variance completeness | FIXTURE + REAL_LOGIC | L/W/H/weight + assembly must be complete+ok; `packagingPolicyHash` fail-closed |
| 655–660 acceptance | FIXTURE + REAL_LOGIC | generation `10207d34-…`; CODE `e66ca9d`; tenant digest equal `cd6cb783…`; `physicalPrototypeValidated=false` |

## Phase 541–600 Small-Space KD SKU Portfolio Factory V1

| Item | Status | Evidence |
|---|---|---|
| 541–546 PortfolioIntent | REAL_LOGIC | all envelope fields finite >0; thickness policy list; explicit invalid not persisted |
| 547–552 candidates | REAL_LOGIC | 28 / 8 KD kinds; REJECTED_DFM retained; duplicate canonical hash blocked |
| 553–558 DFM scorecard | REAL_LOGIC | independent conservation recompute; missing nest fields fail; ranking/prototype gated |
| 559–564 cross-SKU plan | REAL_LOGIC / PLANNING | material+thickness+grain groups; candidate vs used remnant IDs; no consume; no double remnant |
| 565–570 commercial | CONFIG_ESTIMATE | labeled components; stale snapshot fail-closed |
| 571–576 ranking | REAL_LOGIC | rankingPolicyHash; Top 10 exact lineage; conservationOk required; MOCK demand not REAL |
| 577–582 approval pack | REAL_LOGIC | WAITING_PRODUCT_APPROVAL / APPROVED_FOR_PROTOTYPE ≠ LIVE_CNC |
| 583–588 media | REAL | 4/4 T1000 OptiX usedMock=false SHA/size/job/GPU bound on `7a87ea5` generation `0b76b09e-…` |
| 589–594 prototype pack | REAL_LOGIC | MANUAL_STATION traveler; READY only after human approval; conservation fail-closed |
| 595–600 acceptance | FIXTURE + REAL | generation `0b76b09e-…`; six-file atomic; runner requires `ok`; CI `34351349710`; tenant digest equal |

## Phase 481–540 Manual Factory Pilot V1 / Operational Control & Recovery

| Item | Status | Evidence |
|---|---|---|
| 481–488 operator/shift | REAL_LOGIC / MANUAL_IDENTITY | persist identity.json; disabled/closed/cross-tenant fail closed; restart preserves OPEN shift; not IAM |
| 489–496 traveler | REAL_LOGIC / PARTIAL hardware | releaseHash pin; DAM HTML; scan token does not authorize; barcode hardware PARTIAL |
| 497–504 cycle count | REAL_LOGIC / MANUAL | WAITING_HUMAN_APPROVAL; consumed/reserved unchanged; conserved after apply |
| 505–512 labor | REAL_LOGIC / MANUAL | append-only segments/corrections; CONFIG_ESTIMATE vs MANUAL; accounting NOT_IMPLEMENTED |
| 513–520 hold/rework/scrap | REAL_LOGIC | blocking hold prevents complete; reworkHistory; remnant path not silent scrap |
| 521–528 packing/handoff | REAL_LOGIC / MANUAL | checklist pinned; mismatch no auto-override; handoff not booked/not delivery |
| 529–536 backup/restore | REAL_LOGIC | malformed MIXED_SPEC/idem/packets fail-closed; tenant_state_digest exact IDs+lineage; snapshot path-set+hash; restored-root health; exact-set verifier; durable consume/complete counters |
| 537–540 acceptance | FIXTURE + REAL_LOGIC | generation `2d0cc206-…`; runner-bound `11c79d1`; tenantStateDigest.equal; identityMismatch=[]; atomic 8-file publish; CI `34342453890`; REAL blender reused `018cc70` |

## Phase 421–480 Pilot Deployment Hardening / Operator Control Plane

| Item | Status | Evidence |
|---|---|---|
| 421–428 event journal | REAL_LOGIC | PREPARED outbox then COMMITTED journal; open tx → BLOCKED_EVIDENCE; tamper still fail-closed |
| 429–436 cross-process stock | REAL_LOGIC | FileLock + CAS; unique-SKU subprocess race; `os._exit` after-staging/after-business |
| 437–444 MANUAL_STATION | REAL_LOGIC | durable WO/release/lease snapshots; recreate Platform recovers ACK/COMPLETE; orphan currentLease cleared |
| 445–452 operator/scan | FIXTURE / PARTIAL | mock-platform operator view FIXTURE; barcode hardware PARTIAL |
| 453–460 exceptions | REAL | catalog + inbox; fail-closed; journaled |
| 461–468 contracts | REAL logic / IMPORTED | schema-versioned import; rejected rows listed; adjustment WAITING_HUMAN_APPROVAL |
| 469–474 health | FIXTURE | `/api/pilot/health` tenant-safe on mock platform; LIVE_CNC/LASER BLOCKED |
| 475–480 chaos + REAL | FIXTURE + REAL | 110 WO FIXTURE/CHAOS; hermetic scratch tamper; runner-bound HEAD `018cc70`; shared journal health REAL after; 4/4 T1000 OptiX `018cc70` usedMock=false release-bound |

## Phase 301–360 Manufacturing Release & Pilot Operations

| Item | Status | Evidence |
|---|---|---|
| 301–304 canonical six-file reader | REAL | `read_canonical_truth_set` rejects mixed generation/commit, missing, malformed; runner success checks all six |
| 305–312 ManufacturingRelease packets | REAL | KD/retail/packaging/acrylic; checksum SHA-256+size; tamper fails; APPROVED_FOR_MANUAL_RELEASE ≠ LIVE_CNC |
| 313–320 supplier RFQ/compare | REAL logic / IMPORTED data | ≥3 snapshots; FX MANUAL; stale on releaseHash/qty/FX; no LIVE_PROVIDER |
| 321–328 WorkOrder traveler | REAL (manual) | lot `reserve_sheets` (not allocate-on-reserve); cancel restores unconsumed; consume once; tenant isolation; not a MES |
| 329–336 QC + traceability | REAL | authoritative `required_final_ok`; `qc_ok=True` cannot bypass missing/failed FINAL; rework loop; DAM refs |
| 337–344 logistics boundary | REAL planning | carton expected≠measured; conservation; pallet PLANNING; carrier IMPORTED; barcode PARTIAL |
| 345–352 unit economics | REAL freeze | frozen history; variance; scrap vs remnant vs recovered credit; demand observation MOCK |
| 353–356 four-family E2E | REAL (manual sim) | all COMPLETED with verified packets |
| 357 REAL Blender refresh | REAL | 4/4 T1000 OptiX `commitSha=414847d` `usedMock=false` hash/size PASS; non-null `releaseHash` bound to accepted ManufacturingRelease |
| 358 batch stress | FIXTURE | 20 releases, ≥100 ops; `noDoubleConsume` observed (not `or True`); material conservation; negative regression |
| 359 readiness | REAL flags | missing evidence → false/UNVERIFIED; `liveFactoryExecutionReady=false`; `fullAutonomousFactoryReady=false` |
| 360 acceptance docs | REAL | `docs/MANUFACTURING_RELEASE_REAL_ACCEPTANCE.md` + `PILOT_OPERATIONS_ACCEPTANCE.md` + `QC_TRACEABILITY_ACCEPTANCE.md` |

## Phase 361–420 Pilot Reliability / Manufacturing Control Boundary

| Item | Status | Evidence |
|---|---|---|
| 361–368 STRICT_STOCK | REAL | atomic `allocate_requirement`; partial shortage rollback; SKU/thickness/length/width/grain match; leftover durable lots cannot satisfy a unique-SKU shortage; no phantom lots |
| 369–376 WO transitions | REAL | TRANSITIONS table; ops require reserve; complete needs ops+QC+packing |
| 377–384 QC plan pin | REAL | release-pinned qcPlanHash; rework append-only |
| 385–392 supersession | REAL | superseded cannot open WO; approval exact-hash |
| 393–400 receipts | REAL logic / IMPORTED data | tenant-scoped idempotent; persist length/width/grain; expected mismatch quarantined; no PO |
| 401–408 shipment draft | REAL logic | SHIPMENT_DRAFT not booked; pack shortage/duplicate fail; carton vs shipment idem namespaces |
| 409–414 console/API | REAL | X-Tenant-Id authoritative; WO/release/carton keys `{tenant}::{kind}::{raw}` |
| 415–420 fixture stress + REAL | FIXTURE + REAL | no fabricated stress fallback; reliability_gate in required_ok; 4/4 T1000 OptiX `997db34`; partialShortageRollback/materialCompatibility/tenantIsolation |

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
| 68 Synthetic data | PARTIAL at Phase 68 (RGB/mask REAL in production; depth/normal/segmentation were `notProducedThisRun` until compositor AOVs). **Current:** Phase 71–120 added REAL Cycles AOV depth/normal/seg via Blender 5 compositing_node_group. Manifest still in DAM. |
| 69 Recipe research | REAL — EXPERIMENTAL→CANDIDATE; cannot overwrite PRODUCTION |
| 70 Hardening | REAL for path traversal guard, script SANDBOX ONLY, cancel, GPU reservation release, temp log cleanup, lineage, cache, lease recovery. Not a full OS sandbox. |

## Blockers

- No RTX 5090 on this host. Worker key is `local-t1000` from real nvidia-smi. **Not BLOCKED** — discovery is honest.
- Vision Judge is heuristic (**MOCK** for the vision-model slice only).
- Live CNC is forbidden this round (**correct**).

## Phase 71–120 Autonomous Furniture Factory (this round)

| Phase | Status | Notes |
|---|---|---|
| 71 Product type registry | REAL | 8 types + geometry/BOM tests |
| 72–78 Modules | REAL | partitions, open/closed, hinged/double/drawer/open bay, toe-kick/legs/plinth, fillers |
| 79–80 MultiCabinet + hash | REAL | factory 2-cabinet assembly; hash lineage |
| 81–85 Space schema | REAL manual JSON; photogrammetry MOCK | walls origin/direction, keep-outs |
| 86–89 Solver | REAL | 3 legal layouts; door/window/column reject |
| 90 Space preview | REAL | Blender 5.2.1 OptiX job completed |
| 91–95 Rules + hardware | REAL | placeholders not structural cert; vendor-neutral IDs |
| 96–100 Manifests + gate | REAL / LIVE_CNC BLOCKED | WAITING_APPROVAL |
| 101–107 Nesting | REAL | guillotine, grain, kerf/trim, SVG/DXF interface |
| 108–110 Quote | REAL | stale on hash change |
| 111–114 NL / variants | REAL | DISPLAY_CABINET; UNKNOWN/NEEDS_INPUT |
| 115–116 Vision | MOCK | Provider interface; engineering veto |
| 117–119 Factory API | REAL | `/api/factory/*` on existing Admin |
| 120 Acceptance | REAL | `docs/FURNITURE_FACTORY_REAL_ACCEPTANCE.md` |
| Assembly MP4 | REAL | ffmpeg mux |
| Cycles AOV | REAL | Blender 5 compositing_node_group |
| AI Video | MOCK | no live adapter |
| OS sandbox | PARTIAL | not a full OS jail |

## Phase 121–180 review fix (`704d058` CHANGES REQUIRED)

Local pytest 77 passed after: multipart runtime dep, OS-agnostic path guard, remnant ownership, paired saved sheets, 8-kind REAL Blender previews. **GitHub CI @ 2aea774 FAILED 3 tests.** **GitHub CI @ e7d911d run 34245840051 GREEN** (ubuntu-latest + windows-latest, MOCK suite). Cost model scope=`CONFIG_ESTIMATE_ONLY`. Phase 130: 8/8 REAL KD previews. OS sandbox still PARTIAL.

## Phase 121–180 KD / Flat-Pack (this round)

| Phase | Status | Notes |
|---|---|---|
| 121–130 product family | REAL | 12 types with geometry+BOM |
| 131–140 packing/logistics | REAL (prices ESTIMATED) | carton from panels; oversize gate CONFIG |
| 141–145 waste/remnants | REAL | conservation err=0; consume-once |
| 146–150 batch/cross-SKU | REAL | lineage on placements |
| 151–160 landed cost | ESTIMATED/CONFIG | remnant credit; quantity breaks non-linear |
| 166 demand | MOCK | UNAVAILABLE |
| 167–170 R&D + approval | REAL deterministic / MOCK demand-vision | prototype only |
| 171–176 e-com/AR | REAL queue, AR PARTIAL | same TwinStore |
| 177 CI | REAL workflow file | check after push |
| 178 readiness | REAL computed | `fullAutonomousFactoryReady=false` |
| 179–180 KD acceptance | REAL | `docs/KD_FACTORY_REAL_ACCEPTANCE.md` |
| LIVE_CNC | BLOCKED | |
| Vision/Video | MOCK | |

## Do not redo

Blender discovery, OptiX probe, smoke render, WHITE_STUDIO, 360, DAM, parametric geometry/BOM/cost/NL, production no-mock-fallback.

## Phase 181–240 Physical Product OS (`fb8cae6` 旨令)

Hygiene: KD scoped-readiness `ciEvidenceReady=true` synced; Progress Report duplicate REAL_PROVIDER line removed. Scheduler/Queue/DAM/Recipe/TwinStore/CabinetSpec not rewritten.

| Phase | Status | Notes |
|---|---|---|
| 181–184 RemnantStore durable + lease/TTL | REAL | `.fox3d-data/remnants` JSON; restart + stale version + tenant isolation tests |
| 185 Material lots | REAL | CONFIG cost snapshot; placement `materialLotId` |
| 186–187 quality + grain | REAL | damaged/quarantined excluded; grain blocks illegal rotate |
| 188 valuation | ESTIMATED/CONFIG | not accounting cost |
| 189 inventory manifest | REAL | reconciliation hash on production batch |
| 190 remnant acceptance | REAL | `docs/MATERIAL_REMNANT_REAL_ACCEPTANCE.md` |
| 191–194 Nesting V3 | REAL | baseline kept; BFD; multi-start; multi-objective; fallback |
| 195–198 window/cut/defects/offcut | REAL | sku/bom lineage; saw-friendly sequence; defect keep-out |
| 199–200 benchmark + acceptance | REAL | 10 fixtures; this host 2 wins / 0 losses; `docs/NESTING_V3_ACCEPTANCE.md` |
| 201–210 KD DFA | REAL | connector versions; 10-candidate board; Demand MOCK |
| 211–217 retail families + planogram + same pipeline | REAL | 6 families; load CONFIG_ESTIMATE; electrical BLOCKED |
| 218 retail Blender | REAL | 6/6 T1000 OptiX `usedMock=false` |
| 219–220 packing + acceptance | REAL | `docs/RETAIL_FIXTURE_REAL_ACCEPTANCE.md` |
| 221–227 packaging structure | REAL geometry / PARTIAL strength+preflight | 5 families; dieline SVG/DXF-friendly |
| 228 fold preview | REAL | Blender flat+folded |
| 229–230 bundle + acceptance | REAL | `docs/PACKAGING_STRUCTURE_REAL_ACCEPTANCE.md` |
| 231–235 acrylic | REAL previews / CONFIG cost / BLOCKED live laser | 3/3 REAL Blender |
| 236–238 registry + reverse R&D + API | REAL adapters | MARKET_UNVERIFIED; existing Admin |
| 239 OS acceptance | REAL | `docs/PHYSICAL_PRODUCT_OS_REAL_ACCEPTANCE.md` three E2E paths |
| 240 readiness | REAL computed | `fullAutonomousFactoryReady=false` |
| Vision/Video/Demand | MOCK | |
| LIVE_CNC/LASER | BLOCKED | |
| OS sandbox | PARTIAL | |

## Phase 241–300 Commercialization Hardening (`b9e7861` 旨令)

Hygiene: unscoped `productionReady` removed from REAL_E2E; Phase 68 AOV current status synced; domain acceptance files now have unique machine-verifiable rows.

| Phase | Status | Notes |
|---|---|---|
| 241 scoped readiness | REAL | `globalProductionReady=false`; full factory false |
| 242–243 EvidenceBundle+verifier | REAL | 5/5 T1000 OptiX artifacts hash/size/usedMock=false |
| 244 truth labels | REAL | regression forbids MOCK→REAL, CONFIG→LIVE_PROVIDER |
| 245–247 approval/stale/RC | REAL | APPROVED_FOR_EXPORT ≠ LIVE_CNC |
| 248–249 sandbox/policy | PARTIAL | PATH_GUARD_ONLY; network not host-enforced |
| 250 release-gate acceptance | REAL | `docs/RELEASE_GATE_REAL_ACCEPTANCE.md` |
| 251–259 provider snapshots | REAL import / BLOCKED live | MANUAL/IMPORTED; mixed MIXED cost |
| 260 commercial cost acceptance | REAL | `docs/COMMERCIAL_COST_ACCEPTANCE.md`; liveProviderReady=false |
| 261–269 packaging V2 | REAL geometry / PARTIAL strength | 20/20 fit; McKee estimate |
| 270 packaging V2 acceptance | REAL | `docs/PACKAGING_V2_ACCEPTANCE.md` |
| 271–279 safety | REAL estimate / notCertified | dangerous cases veto |
| 281–289 publication | REAL packages / PARTIAL AR | no fake USDZ |
| 291–299 R&D loop | MOCK demand / FIXTURE outcomes | MARKET_UNVERIFIED |
| 300 OS V2 acceptance | REAL | `docs/PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.md` |
| fullAutonomousFactoryReady | false | |
