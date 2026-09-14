# Development Agent 指令：Issue #6 Blender → Generative Video Ground Truth Pipeline V1

> Supervisor Re-Gate checkpoint: 2026-09-15
> Main before this checkpoint: `40e64f343287969712a1d6e6fe0b32b49b77aa96`
> Newly reviewed out-of-band PR: #12 `codex/model-category-tree` (stacked on PR #11, unmerged)
> PR #12 CODE: `052be7f057c24b982b6c6c716c1a9aef094999da`
> PR #12 DOCS/head: `68f64d604bb750c0c48830c0d50516ef5157d296`
> CODE CI: `34866913056` — Ubuntu + Windows SUCCESS, 924 tests/OS
> DOCS CI: `34869377842` — Ubuntu + Windows SUCCESS, 924 tests/OS
> Clean REAL evidence: `0c83109d-1e6c-4ec6-8d34-ec8c14c68851`, `workingTreeClean=true`, `developmentOnly=false`
> Re-Gate result: **PR #12 ACCEPT WITH SCOPE / NO MERGE AUTHORIZATION**
> Next authorized mainline lane: **Issue #6 — Blender → Generative Video Ground Truth Pipeline V1 from current main**

## 0. Re-Gate boundary for PR #12

PR #12 is accepted only for the scoped product-model classification/navigation lane. It does **not** authorize merge, does not validate physical dimensions/structures, and does not make any model family, print workflow, provider, machine path, or the whole system Production Ready.

### REAL
- loopback HTTP path used by the clean acceptance runner;
- Blender 5.2.1 LTS / OptiX base + composition generation with `usedMock=false`;
- BLEND reopen checks;
- preserved downloadable bytes/SHA/size across classification move + restart;
- exact CODE and DOCS CI green on Ubuntu + Windows.

### REAL_LOGIC
- product category tree is navigation/classification metadata, not geometry authority;
- classification has independent revision/history and optimistic concurrency;
- classification moves preserve master bytes/input hash/generation IDs;
- category inference uses explicit model fields/Recipe family, never filenames/artwork as structural truth;
- invalid parent/unknown/family-mismatch categories fail closed;
- empty categories do not create placeholder models;
- new leaf drafts inherit only family/subtype/layers and remain `PENDING` with dimensions/structure unset.

### FIXTURE / MOCK
- clean REAL acceptance input dimensions/material are synthetic fixture truth;
- CI Blender uses `FOX3D_MOCK_BLENDER=1` and is regression evidence only.

### PARTIAL
- local tree currently exposes three generated references and eight drafts;
- category availability is not geometry/model completion;
- existing Recipe-derived masters are references, not physically measured masters.

### BLOCKED / false
- physical dimensions/structure validation for the classified product families;
- rotating cabinet mechanism and unsupported curved/irregular geometry;
- veneer/material library, calibrated grain scale, per-part material assignment;
- physical UV/RIP/white ink/clear ink/jig/origin/color approval/physical print;
- live H3/LTX/Vision/provider calls;
- hot-folder/machine writes, LIVE_CNC/LIVE_LASER/PLC;
- unscoped/global Production Ready.

PR #7/#8/#9/#10/#11/#12 remain unmerged. **Do not auto-merge any of them.**

## 1. Branch / architecture discipline

Issue #6 must start from **current `main` after this instruction commit**. Do not base it on PR #7–#12 and do not copy hidden dependencies from those branches.

Reuse Product Truth / CabinetSpec / Artwork Placement / Product Truth Render Pack / DAM / Recipe / Scheduler / Queue interfaces already on main. Do not rewrite Scheduler, Queue, DAM, Recipe, TwinStore, CabinetSpec, Product Truth or engineering authority.

Generative models are replaceable renderers. Product Truth is not replaceable. Generative pixels must never become millimetre, geometry, articulation or manufacturing authority.

## 2. Deterministic `VideoRecipe`

Implement provider-neutral recipes at minimum:
- `HERO_ORBIT_8S`
- `DOOR_OPEN_8S`
- `ARTWORK_DETAIL_6S`
- `SMALL_ROOM_10S`
- `ASSEMBLY_EXPLODE_10S` only if authoritative assembly data exists; otherwise explicit BLOCKED.

Each recipe must deterministically bind:
- recipe ID/version, duration, fps, resolution, exact frame count;
- `VideoRecipeHash`, `CameraRecipeHash`, `SceneRecipeHash`;
- focal length/sensor/clipping/look-at semantics;
- camera keyframes + interpolation;
- product/object transform timeline;
- articulation timeline;
- tenant/SKU/product version;
- Engineering/Product Truth identity;
- ArtworkHash/ArtworkVersion/PlacementHash/finalUvHash when artwork exists.

Authority schemas must use strict finite numeric validation. Reject bool/string/NaN/Inf coercion.

## 3. Frame-level REAL Blender Ground Truth

Build one reusable Blender execution path that emits per frame:
- RGB / Beauty;
- Depth;
- Normal;
- ProductMask;
- ArtworkMask;
- Alpha where applicable;
- camera intrinsics/extrinsics or matrix;
- product/object matrix;
- articulation state;
- exact frame index and timestamp.

Every frame/artifact must bind tenant, SKU/product version, Engineering/Product Truth identity, artwork identities where applicable, Scene/Camera/Video recipe hashes, Blender job ID, artifact SHA-256, byte size and path/DAM lineage.

Do not alias ProductMask to ArtworkMask. ArtworkMask must come from the actual mapped printable-surface scene authority when artwork exists.

## 4. Required REAL gate — `HERO_ORBIT_8S`

On a clean tree at exact final CODE SHA:
- run REAL Blender with `usedMock=false`;
- keep geometry and artwork identity fixed;
- execute deterministic smooth orbit/dolly motion;
- emit exact required frame set and AOV/masks;
- verify actual bytes/SHA/size/order/timestamps/matrices;
- record Blender version/device/backend/job ID;
- validate persisted outputs and lineage fail closed.

Only after this passes may scoped `VIDEO_GROUND_TRUTH_READY=true` and `HERO_ORBIT_REAL=true` be declared.

## 5. `DOOR_OPEN_8S` articulation authority must fail closed

`DOOR_OPEN_REAL=true` is allowed only if existing Product Truth independently supplies exact door/component identity, hinge pivot + axis, allowed range, canonical closed/open transforms and worker-observed transforms at required keyframes.

Negative tests must include wrong/swapped door, wrong pivot/axis/range/transform, wrong Blender job/SKU/product version and artwork bound to wrong moving component.

If authority is incomplete, report:
- `DOOR_OPEN_REAL=false`
- `doorOpenGroundTruthReady=false`
- `BLOCKED_ARTICULATION_AUTHORITY`

Never invent hinge authority for a demonstration.

## 6. Canonical `VIDEO_GROUND_TRUTH_MANIFEST`

Create deterministic machine-readable manifest with:
- instruction SHA, CODE SHA, evidence generation ID;
- recipe/product/artwork/engineering identities;
- every frame index/timestamp;
- every artifact path/ref/SHA/size;
- camera/object matrices;
- articulation state;
- Blender worker/job lineage;
- deterministic manifest SHA-256.

Validator must independently re-derive expected identities from frozen pre-worker authority. Worker output or final manifest cannot validate itself.

Fail closed on missing/duplicate/reordered frames, timestamp drift, non-finite matrices, artifact bytes/hash/size mismatch, mask swap/tamper, wrong Product/Artwork/Placement/finalUv/Camera/Scene/Video hash, cross-SKU/cross-video injection and wrong job/path/DAM lineage.

## 7. Provider-neutral H3/LTX gateway only

Implement/extend narrow contracts for `H3MaxAdapter`, `LTX25Adapter` and future providers. Request packages may consume RGB/keyframes, Depth, Normal, ProductMask, ArtworkMask, camera metadata, style brief and product-lock constraints.

Until real provider network/runtime evidence exists:
- `liveH3MaxProviderReady=false`
- `liveLtx25ProviderReady=false`
- `liveProviderReady=false`
- fixture/mock outputs remain MOCK/FIXTURE
- generative output never becomes Product Truth.

Never commit credentials/tokens.

## 8. Product Lock QA V1 + retry/DAM lineage

Before any live Vision dependency, implement deterministic REAL_LOGIC checks for silhouette/shape consistency proxy, panel/door topology, mask geometry/IoU or equivalent, artwork position/scale/rotation, camera motion vs recipe, temporal identity/flicker signals and publication guard.

Allowed results: `PASS`, `RETRY`, `REJECT`. A rejected candidate cannot publish as final. If Vision is not live, `visionQaReady=false`; deterministic checks must not be called REAL Vision.

Persist:
`Ground Truth -> Provider Candidate -> QA -> PASS/RETRY/REJECT -> DAM`

Persist provider/model/version/seed/config, manifest hash, attempts/retry reason, QA evidence, artifact SHA/bytes and final publish state. Retries must be idempotent and must not silently overwrite accepted lineage.

## 9. Required adversarial tests

At minimum test fail-closed behavior for:
- wrong tenant/SKU/product version/EngineeringHash;
- ArtworkHash/PlacementHash/finalUvHash mismatch;
- Scene/Camera/Video recipe hash mismatch and semantic-body/hash contradiction;
- frame reorder/missing/duplicate/cross-video mix;
- camera/object matrix tamper and non-finite values;
- ProductMask/ArtworkMask swap or alias;
- artifact path/SHA/size mismatch and wrong DAM/job lineage;
- absent/incorrect articulation authority;
- rejected candidate publish;
- Mock provider attempting `liveProviderReady=true`;
- Mock Vision attempting `visionQaReady=true`.

## 10. Acceptance artifacts

Create/update:
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ARCHITECTURE.md`
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ACCEPTANCE.md`
- machine-readable acceptance JSON.

Truth Matrix must separate `REAL`, `REAL_LOGIC`, `FIXTURE`, `MOCK`, `PARTIAL`, `BLOCKED`.

Do not rewrite `docs/REAL_E2E_ACCEPTANCE.md`, `docs/CABINET_REAL_ACCEPTANCE.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md` or historical reports merely for narrative consistency. Change them only when fresh evidence genuinely changes scoped truth.

## 11. Evidence sequence

1. Implement code + tests.
2. Full local `pytest -q`.
3. Commit/push one final CODE SHA.
4. Exact CODE SHA Actions: Ubuntu + Windows both SUCCESS.
5. Verify clean tree on exact CODE SHA.
6. Run REAL Blender Video Ground Truth acceptance.
7. Verify actual bytes/hashes/matrices/manifests/job/DAM lineage.
8. Commit evidence/docs separately as DOCS SHA.
9. Exact DOCS SHA Actions: Ubuntu + Windows both SUCCESS.
10. Post one `READY_FOR_RE_GATE` handoff to Issue #1.
11. STOP. Do not enter next major phase.

`FOX3D_MOCK_BLENDER=1` CI is regression evidence only, never REAL Blender or Production Ready evidence.

## 12. `READY_FOR_RE_GATE` minimum contract

Report:
- `INSTRUCTION_SHA`
- `ISSUE=6`
- `CODE_SHA`
- `DOCS_SHA`
- `CODE_CI_RUN_ID`
- `DOCS_CI_RUN_ID`
- `TEST_COUNT`
- `EVIDENCE_GENERATION_ID`
- `WORKING_TREE_CLEAN=true`
- `REAL_BLENDER=true|false`
- `USED_MOCK=true|false`
- `VIDEO_GROUND_TRUTH_READY=true|false`
- `HERO_ORBIT_REAL=true|false`
- `DOOR_OPEN_REAL=true|false`
- `VISION_QA_READY=true|false`
- `LIVE_H3_PROVIDER_READY=true|false`
- `LIVE_LTX_PROVIDER_READY=true|false`
- `GLOBAL_PRODUCTION_READY=false`

Then list REAL / REAL_LOGIC / FIXTURE / MOCK / PARTIAL / BLOCKED separately.

## 13. Existing global blockers remain unchanged

Keep false/BLOCKED unless independently verified with fresh evidence:
- public HTTPS webhook/live Supervisor E2E;
- webhook secret and live supervisor provider/model credentials;
- supervisor admin key;
- `webhookRealE2e=false`;
- Supervisor `liveProviderReady=false`;
- `eventDrivenSupervisorReady=false`;
- physical UV/RIP/machine/hot-folder execution;
- LIVE_CNC / LIVE_LASER / PLC;
- unscoped `globalProductionReady` / `fullAutonomousFactoryReady`.

## 14. Forbidden

- no architecture rewrite;
- no auto-merge of PR #7/#8/#9/#10/#11/#12;
- no dependency on unmerged PR branches;
- no Mock/FIXTURE/REFERENCE -> REAL promotion;
- no generative output -> Product Truth promotion;
- no fabricated articulation authority;
- no licensed artwork upload to GitHub;
- no production PrintFox/AI-provider claim without separate live evidence;
- no physical print/machine write;
- no unscoped Production Ready claim;
- stop after Issue #6 `READY_FOR_RE_GATE`.
