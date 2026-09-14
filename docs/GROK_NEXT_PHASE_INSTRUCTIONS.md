# Development Agent 指令：Issue #6 Blender → Generative Video Ground Truth Pipeline V1

> Repo: `netfox-web/blender-autonomous-3d`
> Main baseline before this instruction: `9038e74328dbea3d94a2ad340c36c46ce100bb14`
> Reviewed print CODE: `a8a9def4750135ab38e33499fe1c543ad601aacd`
> Reviewed print DOCS: `f69adf912b183480f98c289211c4840323b70e8f`
> CODE CI: `34825977605` — Ubuntu + Windows SUCCESS, 849 tests each
> DOCS CI: `34828209094` — Ubuntu + Windows SUCCESS
> Print evidence: `de87a0b9-1610-454c-be93-e2dab2f5ea71`
> Re-Gate result: **PR #8 ACCEPT WITH SCOPE**
> Next authorized work: **Issue #6 — Blender → Generative Video Ground Truth Pipeline V1**

## 0. Re-Gate decision and scope boundary

PR #8 correction has satisfied the prior gate:

- the FastAPI / Starlette cross-version route test was fixed at `a8a9def` by inspecting actual OpenAPI paths instead of assuming every `app.routes` entry has `.path`;
- exact CODE CI `34825977605` is green on Ubuntu and Windows, 849 tests each;
- clean real acceptance `de87a0b9-1610-454c-be93-e2dab2f5ea71` is bound to exact CODE `a8a9def`, `workingTreeClean=true`, `developmentOnly=false`;
- THREE_DOOR and FLAT both have Blender 5.2.1 / OptiX evidence, downloaded artifact hashes, `.blend` reopen packed-texture/UV verification and restart persistence;
- separate DOCS `f69adf9` has exact dual-platform CI `34828209094` green;
- the docs correctly keep physical manufacturing and live print readiness false.

Truth classification for the accepted print scope:

### REAL
- user-provided source PDF-compatible AI layout dimensions / page identity as source-file truth;
- Blender 5.2.1 OptiX preview for THREE_DOOR and FLAT;
- reopened `.blend` packed texture / UV evidence;
- persisted artifact bytes + SHA-256 / download / restart verification.

### REAL_LOGIC
- read-only source import boundary;
- version / proof / release invalidation;
- source-size proof logic;
- explicit human release checks;
- no-dispatch / file-handoff-only policy.

### FIXTURE / MOCK
- GitHub Actions use `FOX3D_MOCK_BLENDER=1`; CI proves regression only;
- positive human-release automation uses synthetic data and is not an actual operator production sign-off.

### PARTIAL
- cabinet depth / thickness / gaps and other visualization geometry where no measured manufacturing authority exists;
- inspected NetFox / Illustrator imposition workflows are discovery evidence only until the exact working runtime, template/slot dimensions and physical/color contract are verified.

### BLOCKED / false
- `actualArtworkReleased=false`;
- `physicalPrintValidated=false`;
- native NetFox layout import / live API submission;
- hot-folder dispatch;
- production RIP execution, white/clear ink, jig/hole alignment and physical color approval;
- `liveMachineControl=false`;
- LIVE_CNC / LIVE_LASER / PLC.

Do not auto-merge PR #7 or PR #8. Acceptance is scoped review approval, not merge authorization and not global Production Ready.

## 1. Branch / dependency discipline for Issue #6

Start Issue #6 from **current `main`** unless a human explicitly merges prerequisite PRs first.

PR #7 and PR #8 are still open/stacked. Therefore:

- do not branch Issue #6 from PR #7 or PR #8;
- do not copy/paste the unmerged Golden Product or print-workspace implementations into the video branch;
- use existing `main` generic Product Truth / Cabinet / Render Pack / DAM / Recipe interfaces;
- if a Golden-specific integration point is needed, define a narrow adapter/interface and keep it optional until the prerequisite is merged;
- no architecture rewrite of Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth.

The new Illustrator `bbkers v16 JSX` / CSV / AI-template discovery is **not** part of Issue #6. Keep it read-only/backlog; do not execute Illustrator, change NetFox production services or expand this phase into print integration.

## 2. Provider-neutral `VideoRecipe`

Implement a provider-neutral, deterministic `VideoRecipe` model. At minimum support:

- `HERO_ORBIT_8S`
- `DOOR_OPEN_8S`
- `ARTWORK_DETAIL_6S`
- `SMALL_ROOM_10S`
- `ASSEMBLY_EXPLODE_10S` only when assembly authority exists; otherwise BLOCKED.

Each recipe must bind:

- `recipeId` / version;
- duration, fps, resolution and exact frame count;
- CameraRecipe hash / SceneRecipe hash;
- focal length, sensor, clipping and look-at/target semantics;
- camera path keyframes / interpolation;
- object/product transform timeline;
- articulation timeline;
- lighting / scene reference;
- SKU / tenant / product version;
- engineeringHash / Product Truth lineage;
- ArtworkHash / PlacementHash / finalUvHash when artwork exists;
- deterministic `videoRecipeHash`.

No generative provider may redefine product geometry, artwork identity or camera truth.

## 3. Blender frame-level Ground Truth sequence

Create a reusable Blender ground-truth render path that emits per frame, as applicable:

- RGB / Beauty;
- Depth;
- Normal;
- ProductMask;
- ArtworkMask;
- Alpha;
- camera matrix / intrinsics;
- object/product matrix;
- articulation state;
- frame index + timestamp.

Every frame must bind back to:

- SKU / tenant;
- engineeringHash / ProductTruthHash or acceptance-generation identity;
- ArtworkHash / ArtworkVersion;
- PlacementHash / finalUvHash;
- SceneRecipeHash / CameraRecipeHash / VideoRecipeHash;
- Blender job ID;
- artifact SHA-256 + byte size.

Do not infer authoritative product dimensions from generated video pixels.

## 4. Required REAL sequence: `HERO_ORBIT_8S`

Produce at least one clean-tree REAL Blender sequence on the final CODE SHA:

- product geometry is fixed;
- camera performs deterministic smooth orbit/dolly;
- product/artwork identity remains unchanged across frames;
- no Mock Blender;
- record Blender version, render device and GPU backend;
- verify frame count, ordering, hashes and matrices from actual output bytes;
- verify masks and AOVs are not aliased placeholders.

This is the minimum REAL gate for `VIDEO_GROUND_TRUTH_READY=true`.

## 5. `DOOR_OPEN_8S` articulation authority must fail closed

`DOOR_OPEN_8S` may be marked REAL only if existing Product Truth provides authoritative door/component identity, hinge pivot/axis and allowed articulation, and the Blender worker emits observed transform evidence.

Required checks:

- expected door/component exact-set;
- hinge pivot / axis identity;
- closed/open transform semantics;
- worker-observed transform per key frame;
- cross-door swap / wrong hinge / wrong job / wrong SKU fail closed;
- artwork remains bound to the correct moving door.

If authority is incomplete:

- `doorOpenGroundTruthReady=false`;
- status `BLOCKED_ARTICULATION_AUTHORITY`;
- do not synthesize fake hinge authority to make the demo look complete.

## 6. Deterministic frame manifest

Create a machine-readable `VIDEO_GROUND_TRUTH_MANIFEST.json` (or equivalent canonical model) containing every frame and every required lineage field.

Manifest requirements:

- canonical/deterministic serialization;
- manifest SHA-256;
- exact frame index set: no missing / duplicate frames;
- monotonically correct timestamps;
- artifact hashes/sizes verified from bytes;
- camera/object matrices verified as finite numeric values;
- linkage to exact `CODE_SHA` and evidence generation ID;
- no cross-video or cross-SKU artifact reuse unless explicitly content-addressed and semantically identical.

Add fail-closed negative tests for:

- reordered frames;
- missing frame;
- duplicate frame;
- wrong frame timestamp;
- artifact byte/SHA mismatch;
- camera matrix tamper;
- object matrix tamper;
- mask swap;
- cross-SKU frame injection;
- engineeringHash / ArtworkHash / PlacementHash mismatch.

## 7. Provider-neutral H3 / LTX gateway contract only

Implement or extend adapter contracts for:

- `H3MaxAdapter`
- `LTX25Adapter`
- future provider adapters.

The provider request package may consume:

- RGB/keyframes;
- Depth;
- Normal;
- ProductMask;
- ArtworkMask;
- camera metadata;
- prompt / style brief;
- product-lock constraints.

Until a real configured provider network call is executed and independently verified:

- `liveH3MaxProviderReady=false`;
- `liveLtx25ProviderReady=false`;
- `liveProviderReady=false` for this scope;
- Mock / fixture adapters remain MOCK/FIXTURE;
- generated output must never be promoted to Product Truth.

Do not add secrets to repo or logs.

## 8. Product Lock QA V1

Build deterministic QA first; Vision AI may remain MOCK/BLOCKED.

At minimum validate:

- product silhouette consistency proxy;
- panel / door count and topology identity;
- expected mask IoU or mask-bound geometry checks where deterministic;
- artwork region position / scale / rotation consistency;
- camera motion consistency against recipe;
- frame continuity / identity drift signals;
- rejected candidate cannot be published as final.

Return only bounded states such as:

- `PASS`
- `RETRY`
- `REJECT`

If live Vision Judge is not configured, keep `visionQaReady=false`; deterministic QA may be REAL_LOGIC but must not be labeled REAL Vision.

## 9. Retry, candidate lineage and DAM

Implement:

`Ground Truth -> Provider Candidate -> QA -> PASS / RETRY / REJECT -> DAM`

Persist:

- candidate ID;
- provider/model/version;
- seed/config when supplied;
- source ground-truth manifest hash;
- attempt number;
- retry reason;
- QA decision / evidence;
- artifact SHA-256 / bytes;
- final publish status.

Rules:

- idempotent retry semantics;
- a rejected candidate cannot become `Final Commerce Video` without a new accepted QA record;
- DAM must distinguish Blender Ground Truth, Provider Candidate, QA Accepted, QA Rejected and Final Commerce Video;
- no silent overwrite of accepted lineage.

## 10. Golden product integration boundary

Issue #4 / PR #7 is accepted with scope but not merged. For this phase:

- use a product already available through `main` Product Truth interfaces for canonical development and REAL acceptance;
- add an optional integration test/adapter point for the 424×295×900 Golden three-door product only if it can be done without importing/copying unmerged code;
- after a future human merge of PR #7, the same VideoRecipe pipeline should consume it without reimplementation.

Do not block the whole Video Ground Truth architecture on PR #7 merge.

## 11. Required tests / adversarial matrix

At minimum cover:

- wrong tenant / SKU / product version;
- wrong engineeringHash;
- wrong ArtworkHash / PlacementHash / finalUvHash;
- wrong SceneRecipeHash / CameraRecipeHash / VideoRecipeHash;
- frame reorder / missing / duplicate;
- cross-video frame mix;
- camera/object transform tamper;
- ProductMask / ArtworkMask swap or tamper;
- artifact SHA / size mismatch;
- wrong Blender job lineage;
- invalid/non-finite matrices;
- articulation authority absent;
- wrong door/pivot/axis if articulation is enabled;
- rejected candidate publish attempt;
- Mock provider attempting `liveProviderReady=true`;
- Mock Vision attempting `visionQaReady=true`.

All authority mismatches must fail closed.

## 12. Acceptance docs

Create/update:

- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ARCHITECTURE.md`
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ACCEPTANCE.md`
- machine-readable acceptance JSON.

Truth matrix must clearly distinguish:

- REAL;
- REAL_LOGIC;
- FIXTURE;
- MOCK;
- PARTIAL;
- BLOCKED.

Do not rewrite `docs/REAL_E2E_ACCEPTANCE.md` or `docs/CABINET_REAL_ACCEPTANCE.md` merely for narrative consistency. Change them only if the new evidence actually changes their scoped truth.

## 13. CODE / DOCS evidence sequence

Use strict split evidence:

1. implement code/tests;
2. run full local `pytest -q`;
3. push final CODE SHA;
4. require exact CODE SHA Ubuntu + Windows Actions SUCCESS;
5. from a clean tree on exact CODE SHA run REAL Blender Video Ground Truth acceptance;
6. verify actual output bytes/hashes/matrices/manifests;
7. commit acceptance docs/evidence separately as DOCS SHA;
8. require exact DOCS SHA Ubuntu + Windows Actions SUCCESS;
9. post one `READY_FOR_RE_GATE` handoff;
10. STOP for external Re-Gate.

`FOX3D_MOCK_BLENDER=1` CI remains regression evidence only and cannot replace the clean REAL Blender run.

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

Event-Driven Supervisor LIVE external prerequisites remain blocked unless independently changed:

- public HTTPS webhook ingress missing;
- webhook secret missing;
- live supervisor provider/model credentials/config missing;
- admin key missing.

Keep:

- `webhookRealE2e=false`;
- Supervisor `liveProviderReady=false`;
- `eventDrivenSupervisorReady=false`.

Also keep LIVE_CNC / LIVE_LASER / PLC / physical machine control BLOCKED.

## 16. Forbidden

- no architecture rewrite;
- no auto-merge of PR #7 or PR #8;
- no branch dependency on unmerged PR #7/#8 code;
- no Mock/FIXTURE → REAL promotion;
- no generative output → Product Truth promotion;
- no fabricated articulation authority;
- no licensed artwork upload to GitHub;
- no Illustrator execution / NetFox live mutation in this video phase;
- no live print submission / hot-folder / machine write;
- no unscoped `productionReady=true`;
- no next major phase after Issue #6; stop for Re-Gate.
