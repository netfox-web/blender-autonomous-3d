# Development Agent 指令：Issue #6 Blender → Generative Video Ground Truth Pipeline V1

> Supervisor Re-Gate checkpoint: 2026-09-14
> Main before this checkpoint: `bab3a1a2b4631e0c6f40c5c93e33441a72c74dd0`
> Reviewed out-of-band PR: #10 `codex/nas-product-model-library` (still stacked on PR #9, unmerged)
> Reviewed correction CODE: `3fd0a30008ae8b19cc4bf3d5ba636f30ef73610c`
> Reviewed correction DOCS/head: `b479544853d635959820a3b23345485feed33867`
> CODE CI: `34851148775` — Ubuntu + Windows SUCCESS, 904 tests/OS
> DOCS CI: `34853958669` — Ubuntu + Windows SUCCESS, 904 tests/OS
> Clean REAL evidence: `5a13d16e-c19d-4d90-846b-49ebbc618bc7`, `workingTreeClean=true`, `developmentOnly=false`
> Re-Gate result: **PR #10 correction ACCEPT WITH SCOPE / NO MERGE AUTHORIZATION**
> Next authorized lane: **Issue #6 — Blender → Generative Video Ground Truth Pipeline V1 from current main**

## 0. Re-Gate boundary for the PR #10 correction

The latest PR #10 correction is accepted only for its scoped local model/material-library behavior. This does **not** authorize merge and does not turn synthetic inputs, local operator classification, mocked CI Blender, physical printing, or live machine/provider paths into Production Ready.

Accepted scoped truth:

### REAL
- actual HTTP + Blender 5.2.1 LTS OptiX generation for the supported synthetic `OPEN_CABINET`, `HINGED_CABINET`, and `RECTANGLE` fixtures;
- saved `.blend` reopen/component-bound checks and PNG/BLEND/GLB/geometry artifact byte/hash evidence;
- clean exact-CODE acceptance after exact CODE dual-platform CI.

### REAL_LOGIC
- product templates and historical NAS materials are separate views;
- browsing a NAS source does not implicitly create or mutate a product template/draft;
- imported/legacy assets default deny until explicitly classified;
- only operator-reviewed `ARTWORK` is selectable by model/print backend gates;
- changing an asset away from `ARTWORK` invalidates subsequent model/print use and blocks affected old downloads;
- classification revision/history survives restart and original bytes are preserved.

### FIXTURE / MOCK
- formal render dimensions, SKU, artwork, and CI Blender are fixture/mock evidence;
- CI `FOX3D_MOCK_BLENDER=1` is regression evidence only.

### PARTIAL
- local imported-material review is incomplete: 17 inspected, 15 references, 1 mixed sheet unclassified, 1 six-page artwork source reviewed;
- full NAS inventory is not classified;
- company snapshot remains 8 drafts, 0 generated company models, 0 physically validated masters;
- operator classification is local judgment, not production tenant authentication or print authorization.

### BLOCKED / false
- automatic artwork application to those new product models;
- unsupported curved/special geometry;
- calibrated UV/RIP, white/clear ink, jig/origin/color approval;
- physical print and hot-folder/machine dispatch;
- scene generation from this PR;
- LIVE_CNC / LIVE_LASER / PLC / machine control;
- global Production Ready.

PR #7/#8/#9/#10 remain unmerged. **Do not auto-merge them. Stop the PR #10 lane unless a human explicitly reauthorizes it.**

## 1. Branch and architecture discipline

Issue #6 must branch from the **current `main` after this instruction commit**, not from PR #7/#8/#9/#10.

Rules:
- no copy/paste dependency on unmerged branches;
- no PrintFox/NAS-library dependency for Video Ground Truth;
- use existing Product Truth / Cabinet / Render Pack / DAM / Recipe / Scheduler / Queue interfaces on main;
- do not rewrite Scheduler, Queue, DAM, Recipe, TwinStore, CabinetSpec, Product Truth, or existing engineering authority;
- generative models may be replaceable; Product Truth is not replaceable;
- no rendered or generative pixels may become millimetre/engineering authority.

## 2. Implement deterministic `VideoRecipe`

Provide provider-neutral recipes at minimum:
- `HERO_ORBIT_8S`
- `DOOR_OPEN_8S`
- `ARTWORK_DETAIL_6S`
- `SMALL_ROOM_10S`
- `ASSEMBLY_EXPLODE_10S` only where assembly authority exists; otherwise explicit BLOCKED.

Every recipe must deterministically bind:
- recipe ID/version, duration, fps, resolution, exact frame count;
- `VideoRecipeHash`, `CameraRecipeHash`, `SceneRecipeHash`;
- focal length/sensor/clipping/look-at semantics;
- camera keyframes + interpolation;
- product/object transform timeline;
- articulation timeline;
- tenant/SKU/product version;
- Engineering/Product Truth identity;
- ArtworkHash/ArtworkVersion/PlacementHash/finalUvHash when artwork exists.

Strict finite numeric schemas only. Reject bool/string/NaN/Inf coercion in authority fields.

## 3. Frame-level REAL Blender Ground Truth

Create one reusable Blender execution path that can emit per frame:
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

Each emitted artifact/frame must be bound to:
- tenant/SKU/product version;
- EngineeringHash/Product Truth identity;
- ArtworkHash/PlacementHash/finalUvHash where applicable;
- SceneRecipeHash/CameraRecipeHash/VideoRecipeHash;
- Blender job ID;
- artifact SHA-256 + byte size + path/DAM lineage.

No silent ProductMask→ArtworkMask alias. Printable-surface ArtworkMask must be independently derived from actual Blender scene/mapping authority when artwork exists.

## 4. Required REAL gate: `HERO_ORBIT_8S`

On a clean working tree at the exact final CODE SHA:
- run REAL Blender, `usedMock=false`;
- keep product geometry/artwork identity fixed;
- execute a deterministic smooth orbit/dolly;
- emit the exact frame set and required AOV/masks;
- verify actual bytes/SHA/size/order/timestamps/matrices;
- record Blender version/device/backend/job ID;
- reopen/validate outputs where the current architecture supports it;
- fail closed on any lineage or artifact mismatch.

Only after this passes may scoped `VIDEO_GROUND_TRUTH_READY=true` and `HERO_ORBIT_REAL=true` be declared.

## 5. `DOOR_OPEN_8S` articulation authority must fail closed

`DOOR_OPEN_REAL=true` is allowed only if existing Product Truth supplies authoritative:
- exact door/component identity;
- hinge pivot + axis;
- allowed articulation range;
- canonical closed/open transforms;
- worker-observed transforms at required keyframes.

Required negative cases include wrong/swapped door, wrong pivot/axis, wrong transform, wrong Blender job/SKU/product version, and artwork bound to wrong moving component.

If authority is incomplete, declare:
- `DOOR_OPEN_REAL=false`
- `doorOpenGroundTruthReady=false`
- `BLOCKED_ARTICULATION_AUTHORITY`

Do not fabricate hinge authority for a demo.

## 6. Canonical `VIDEO_GROUND_TRUTH_MANIFEST`

Create a machine-readable deterministic manifest containing:
- instruction/CODE SHA + evidence generation ID;
- recipe/product/artwork/engineering identities;
- every frame index/timestamp;
- every artifact ref/path/SHA/size;
- camera/object matrices;
- articulation state;
- worker Blender job lineage;
- deterministic manifest SHA-256.

Validator must independently re-derive canonical expected identities from frozen pre-worker authority. Do not use final manifest/worker output as its own authority.

Fail closed on missing/duplicate/reordered frames, timestamp drift, non-finite matrices, artifact bytes/hash/size mismatch, mask swap/tamper, wrong Product/Artwork/Placement/finalUv/Camera/Scene/Video hash, cross-SKU/cross-video injection, wrong job/path/DAM lineage, or coordinated expected+observed tamper.

## 7. Provider-neutral H3/LTX gateway only

Implement/extend narrow adapters/contracts for:
- `H3MaxAdapter`
- `LTX25Adapter`
- future providers.

Request packages may consume RGB/keyframes, Depth, Normal, ProductMask, ArtworkMask, camera metadata, style brief, and product-lock constraints.

Until a real provider network call/runtime is independently verified:
- `liveH3MaxProviderReady=false`
- `liveLtx25ProviderReady=false`
- `liveProviderReady=false`
- fixture/mock output stays MOCK/FIXTURE
- generative output never becomes Product Truth.

Never commit credentials/tokens.

## 8. Product Lock QA V1 + retry/DAM lineage

Before any live Vision dependency, implement deterministic REAL_LOGIC checks for:
- silhouette/shape consistency proxy;
- panel/door topology identity;
- ProductMask/ArtworkMask geometry/IoU or equivalent deterministic checks;
- artwork region position/scale/rotation;
- camera motion vs recipe;
- temporal identity/flicker signals;
- publication guard: rejected candidate cannot become final.

Allowed outcomes: `PASS`, `RETRY`, `REJECT`.

If Vision is not live, `visionQaReady=false`; do not relabel deterministic checks as REAL Vision.

Persist the chain:
`Ground Truth -> Provider Candidate -> QA -> PASS/RETRY/REJECT -> DAM`

Persist candidate/provider/model/version/seed/config, ground-truth manifest hash, attempt/retry reason, QA evidence, artifact SHA/bytes, and final publish state. Retries must be idempotent; no silent accepted-lineage overwrite.

## 9. Required adversarial tests

At minimum test fail-closed behavior for:
- wrong tenant/SKU/product version/EngineeringHash;
- ArtworkHash/PlacementHash/finalUvHash mismatch;
- Scene/Camera/Video recipe hash mismatch and semantic-body/hash contradiction;
- frame reorder/missing/duplicate/cross-video mix;
- camera/object matrix tamper/non-finite values;
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

Truth matrix must explicitly separate `REAL`, `REAL_LOGIC`, `FIXTURE`, `MOCK`, `PARTIAL`, `BLOCKED`.

Do not rewrite `docs/REAL_E2E_ACCEPTANCE.md`, `docs/CABINET_REAL_ACCEPTANCE.md`, or historical reports merely for narrative consistency. Update them only if fresh evidence truly changes scoped truth.

## 11. Ordered CODE / REAL / DOCS evidence sequence

1. Implement code + tests.
2. Run full local `pytest -q`.
3. Commit/push one final CODE SHA.
4. Exact CODE SHA GitHub Actions Ubuntu + Windows must both SUCCESS.
5. Checkout/verify clean tree on exact CODE SHA.
6. Run REAL Blender Video Ground Truth acceptance.
7. Verify actual bytes/hashes/matrices/manifests/job/DAM lineage.
8. Commit evidence/docs separately as DOCS SHA.
9. Exact DOCS SHA GitHub Actions Ubuntu + Windows must both SUCCESS.
10. Post one `READY_FOR_RE_GATE` handoff to Issue #1.
11. STOP. Do not enter the next major phase.

`FOX3D_MOCK_BLENDER=1` CI remains MOCK regression evidence only.

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
- Event-Driven Supervisor public HTTPS webhook/live E2E;
- GitHub webhook secret and live supervisor provider/model credentials;
- supervisor admin key;
- `webhookRealE2e=false`;
- Supervisor `liveProviderReady=false`;
- `eventDrivenSupervisorReady=false`;
- physical UV/RIP/machine/hot-folder execution;
- LIVE_CNC / LIVE_LASER / PLC / physical machine control;
- unscoped `globalProductionReady` / `fullAutonomousFactoryReady`.

## 14. Forbidden

- no architecture rewrite;
- no auto-merge of PR #7/#8/#9/#10;
- no dependency on unmerged PR branches;
- no Mock/FIXTURE → REAL promotion;
- no generative output → Product Truth promotion;
- no fabricated articulation authority;
- no licensed artwork upload to GitHub;
- no production PrintFox/AI-provider claim without separate live evidence;
- no physical print/machine write;
- no unscoped Production Ready claim;
- stop after Issue #6 READY_FOR_RE_GATE.
