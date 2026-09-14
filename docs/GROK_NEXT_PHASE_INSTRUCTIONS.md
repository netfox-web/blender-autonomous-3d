# Development Agent 指令：Issue #6 Blender → Generative Video Ground Truth Pipeline V1

> Repo: `netfox-web/blender-autonomous-3d`
> Current main before this instruction: `e05295f7834327403ffb102bbc497124550b0258`
> Reviewed PrintFox PR: #9
> Reviewed CODE: `6ac129750624ed48530f5f5988a0b5f6606c8ce0`
> Reviewed DOCS: `e0ea11fc33e5a336b2739ac7282688ff364bdaba`
> CODE CI: `34833832340` — Ubuntu + Windows SUCCESS, 870 tests each
> DOCS CI: `34835768990` — Ubuntu + Windows SUCCESS, 870 tests each
> Clean formal evidence: `e7ee0d4c-8858-40ae-b8da-80bc3073a4e9`
> Re-Gate result: **PR #9 ACCEPT WITH SCOPE**
> Next authorized work: **Issue #6 — Blender → Generative Video Ground Truth Pipeline V1**

## 0. Re-Gate decision for PR #9

PR #9 is accepted only for the scoped **PrintFox digital bridge**. Do not interpret this as production PrintFox/UV-print readiness and do not auto-merge PR #7/#8/#9.

Accepted evidence:

### REAL
- actual committed PrintFox app HTTP path was exercised from committed PrintFox code `1c774d6691b931fa82b8ed7ee4ae5b4de4e83f2a` in isolated loopback services;
- original design bytes were imported and SHA-256 lineage preserved;
- enqueue/cancel/restart/reconciliation path was exercised and replay produced zero duplicate remote jobs;
- REAL Blender 5.2.1 / OptiX preview was generated and the `.blend` reopen / packed texture / UV evidence passed;
- exact CODE `6ac1297` and DOCS `e0ea11f` both have Ubuntu + Windows Actions SUCCESS, 870 tests each.

### REAL_LOGIC
- fixed configured origin; UI cannot supply an arbitrary temporary remote URL;
- in-memory expiring Token session, tenant/origin binding, HttpOnly + SameSite=Strict cookie, no Token in persisted JSON;
- bounded single generation request (1–4 images, no continuous generation);
- request journal written before POST; uncertain submission is not automatically re-POSTed;
- own-task cancel checks exact remote job type/params before cancellation;
- imported art retains provenance and remains subject to existing mm/proof/human release gates.

### FIXTURE / MOCK
- artwork and Token in acceptance are synthetic fixtures;
- no production AI worker/provider executed;
- CI Blender uses `FOX3D_MOCK_BLENDER=1` and is regression evidence only;
- transport failure/redirect cases use MockTransport.

### PARTIAL
- production PrintFox health/config discovery only;
- actual cabinet manufacturing dimensions remain incomplete where not measured;
- native Illustrator slot / jig / origin calibration remains incomplete.

### BLOCKED / false
- `productionPrintfoxAuthenticated=false`;
- `realAiGenerationVerified=false`;
- native Illustrator / NetFox imposition and live job submission;
- physical UV print, RIP, white/clear ink, jig alignment and color approval;
- hot-folder dispatch;
- LIVE_CNC / LIVE_LASER / PLC / machine control;
- `physicalPrintValidated=false`;
- `globalProductionReady=false`.

The earlier superseded CODE `0675360` and failed run `34833598699` are not green evidence.

## 1. Branch and dependency discipline

Issue #6 must start from **current `main`**, unless a human explicitly merges a prerequisite first.

PR #7, #8 and #9 are still review branches. Therefore:

- do not branch Issue #6 from PR #7/#8/#9;
- do not copy/paste Golden Product, print-workspace or PrintFox code from unmerged branches;
- do not make Video Ground Truth depend on PrintFox;
- use existing `main` Product Truth / Cabinet / Render Pack / DAM / Recipe interfaces;
- if a future Golden or PrintFox integration point is needed, define an optional narrow adapter only;
- do not rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth.

The PrintFox bridge is accepted separately and does **not** replace the previously authorized Issue #6 work.

## 2. Provider-neutral `VideoRecipe`

Implement deterministic `VideoRecipe` models for at least:

- `HERO_ORBIT_8S`
- `DOOR_OPEN_8S`
- `ARTWORK_DETAIL_6S`
- `SMALL_ROOM_10S`
- `ASSEMBLY_EXPLODE_10S` only when assembly authority exists; otherwise BLOCKED.

Every recipe must bind:

- recipe ID/version;
- duration, fps, resolution, exact frame count;
- `CameraRecipeHash`, `SceneRecipeHash`, deterministic `VideoRecipeHash`;
- focal length, sensor, clipping and look-at semantics;
- camera path keyframes/interpolation;
- product/object transform timeline;
- articulation timeline;
- scene/lighting reference;
- tenant / SKU / product version;
- engineering / Product Truth lineage;
- ArtworkHash / PlacementHash / finalUvHash when artwork exists.

No provider may redefine geometry, artwork identity or authoritative camera truth.

## 3. Frame-level Blender Ground Truth

Create a reusable Blender path that emits per frame, where applicable:

- RGB / Beauty;
- Depth;
- Normal;
- ProductMask;
- ArtworkMask;
- Alpha;
- camera matrix / intrinsics;
- product/object matrix;
- articulation state;
- exact frame index + timestamp.

Each frame must bind to:

- tenant / SKU / product version;
- engineeringHash / Product Truth identity;
- ArtworkHash / ArtworkVersion;
- PlacementHash / finalUvHash;
- SceneRecipeHash / CameraRecipeHash / VideoRecipeHash;
- Blender job ID;
- artifact SHA-256 and byte size.

Do not infer authoritative dimensions from rendered or generative pixels.

## 4. Required REAL acceptance: `HERO_ORBIT_8S`

On the final CODE SHA and a clean working tree:

- use REAL Blender, not Mock;
- product geometry and artwork identity remain fixed;
- camera performs deterministic smooth orbit/dolly;
- emit and verify the exact frame set and all required AOV/mask artifacts;
- record Blender version/device/GPU backend;
- verify actual bytes, SHA-256, sizes, ordering, timestamps and matrices;
- prove ProductMask / ArtworkMask / AOV outputs are not aliased placeholders.

This is the minimum gate for `VIDEO_GROUND_TRUTH_READY=true`.

## 5. `DOOR_OPEN_8S` must fail closed on articulation authority

Mark `DOOR_OPEN_8S` REAL only when Product Truth supplies authoritative:

- exact door/component identity;
- hinge pivot and axis;
- allowed articulation range;
- closed/open transforms;
- worker-observed transforms at required key frames.

Negative checks must include wrong door, swapped door, wrong pivot/axis, wrong job/SKU and artwork bound to the wrong moving component.

If authority is incomplete:

- `DOOR_OPEN_REAL=false`;
- `doorOpenGroundTruthReady=false`;
- state = `BLOCKED_ARTICULATION_AUTHORITY`;
- do not fabricate hinge authority for a demo.

## 6. Deterministic `VIDEO_GROUND_TRUTH_MANIFEST`

Create a machine-readable canonical manifest with:

- exact CODE SHA and evidence generation ID;
- every frame index/timestamp;
- every artifact ref/SHA/size;
- camera/object matrices;
- articulation state;
- masks/AOV lineage;
- Product/Artwork/Scene/Camera/Video recipe hashes;
- deterministic manifest SHA-256.

Fail closed on:

- missing/duplicate/reordered frames;
- bad timestamp sequence;
- artifact byte/SHA/size mismatch;
- camera/object matrix tamper or non-finite values;
- mask swap/tamper;
- cross-video or cross-SKU injection;
- wrong engineering/artwork/placement/finalUv hashes;
- wrong Blender job lineage.

## 7. Provider-neutral H3 / LTX contract only

Implement/extend adapters for:

- `H3MaxAdapter`
- `LTX25Adapter`
- future providers.

Provider request packages may consume RGB/keyframes, Depth, Normal, ProductMask, ArtworkMask, camera metadata, prompt/style brief and product-lock constraints.

Until a real configured provider network call is independently verified:

- `liveH3MaxProviderReady=false`;
- `liveLtx25ProviderReady=false`;
- `liveProviderReady=false` for this scope;
- fixtures/mocks stay MOCK/FIXTURE;
- generative output can never become Product Truth.

Do not add secrets to repo, evidence or logs.

## 8. Product Lock QA V1

Implement deterministic QA before any live Vision dependency. At minimum check:

- product silhouette/shape consistency proxy;
- panel/door topology identity;
- mask IoU or deterministic mask-bound geometry checks;
- artwork region position/scale/rotation;
- camera motion against recipe;
- temporal identity/flicker signals;
- publication guard: REJECT cannot become final.

Allowed bounded outcomes: `PASS`, `RETRY`, `REJECT`.

If live Vision is not configured, `visionQaReady=false`. Deterministic checks can be REAL_LOGIC, not REAL Vision.

## 9. Retry and DAM lineage

Implement:

`Ground Truth -> Provider Candidate -> QA -> PASS / RETRY / REJECT -> DAM`

Persist candidate ID, provider/model/version, seed/config, ground-truth manifest hash, attempt, retry reason, QA evidence, artifact SHA/bytes and final publish state.

Rules:

- retries are idempotent;
- rejected candidate cannot become Final Commerce Video without a new accepted QA record;
- DAM distinguishes Blender Ground Truth / Provider Candidate / QA Accepted / QA Rejected / Final Commerce Video;
- no silent overwrite of accepted lineage.

## 10. Golden Product integration boundary

Because PR #7 remains unmerged:

- use a product already on `main` for canonical development/REAL acceptance;
- optional Golden integration is allowed only through a narrow interface that does not import unmerged code;
- after a future human merge, the same VideoRecipe pipeline must consume the Golden Product without reimplementation.

Do not block Issue #6 on PR #7/#8/#9 merge.

## 11. Required adversarial tests

Cover at least:

- wrong tenant/SKU/product version;
- engineeringHash mismatch;
- ArtworkHash / PlacementHash / finalUvHash mismatch;
- SceneRecipeHash / CameraRecipeHash / VideoRecipeHash mismatch;
- frame reorder/missing/duplicate/cross-video mix;
- camera/object transform tamper;
- ProductMask / ArtworkMask swap or tamper;
- artifact SHA/size mismatch;
- wrong Blender job lineage;
- non-finite matrices;
- articulation authority absent;
- wrong door/pivot/axis;
- rejected candidate publish attempt;
- Mock provider attempting `liveProviderReady=true`;
- Mock Vision attempting `visionQaReady=true`.

All authority mismatches fail closed.

## 12. Acceptance docs

Create/update:

- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ARCHITECTURE.md`
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ACCEPTANCE.md`
- machine-readable acceptance JSON.

Truth matrix must explicitly separate REAL / REAL_LOGIC / FIXTURE / MOCK / PARTIAL / BLOCKED.

Do not rewrite `docs/REAL_E2E_ACCEPTANCE.md`, `docs/CABINET_REAL_ACCEPTANCE.md`, or historic Grok reports merely for narrative consistency. Change them only if new evidence actually changes scoped truth.

## 13. CODE / DOCS evidence sequence

1. implement code/tests;
2. run full local `pytest -q`;
3. push final CODE SHA;
4. exact CODE SHA Ubuntu + Windows Actions must SUCCESS;
5. on a clean tree at exact CODE SHA, run REAL Blender Video Ground Truth acceptance;
6. verify actual output bytes/hashes/matrices/manifests;
7. commit evidence/docs separately as DOCS SHA;
8. exact DOCS SHA Ubuntu + Windows Actions must SUCCESS;
9. post one `READY_FOR_RE_GATE` handoff;
10. STOP.

`FOX3D_MOCK_BLENDER=1` CI is regression evidence only.

## 14. `READY_FOR_RE_GATE` contract

Report at minimum:

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

## 15. Existing global blockers remain unchanged

Keep fail-closed unless independently verified:

- Event-Driven Supervisor public HTTPS webhook ingress;
- GitHub webhook secret;
- live supervisor provider/model credentials/config;
- supervisor admin key;
- `webhookRealE2e=false`;
- Supervisor `liveProviderReady=false`;
- `eventDrivenSupervisorReady=false`;
- LIVE_CNC / LIVE_LASER / PLC / physical machine control BLOCKED.

## 16. Forbidden

- no architecture rewrite;
- no auto-merge of PR #7/#8/#9;
- no Issue #6 dependency on unmerged PR #7/#8/#9;
- no Mock/FIXTURE → REAL promotion;
- no generative output → Product Truth promotion;
- no fabricated articulation authority;
- no licensed artwork upload to GitHub;
- no production PrintFox Token, AI worker or cloud generation claim unless separately evidenced;
- no Illustrator execution / native NetFox live mutation in this video phase;
- no print hot-folder / physical machine write;
- no unscoped `productionReady=true`;
- no next major phase after Issue #6; stop for Re-Gate.
