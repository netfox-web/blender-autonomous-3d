# Development Agent 指令：Issue #6 Round 3 — Authoritative DOOR_OPEN Video Ground Truth / Re-Gate

> Supervisor checkpoint: 2026-09-15
> Current main before this instruction: `6f68f7e59f490495c35f22f4d4aaeb266fd37d96`
> Reviewed PR: #13 `codex/video-ground-truth` — OPEN / unmerged
> Accepted Round 2 CODE: `a5b368a3d907950c5165f4b1a0058853ace617fc`
> Accepted Round 2 DOCS: `3c57849f2a765451a3c03c564bbe6346e26ea9cd`
> Exact CODE CI: `34900852044` — Ubuntu + Windows SUCCESS, 901 tests/OS
> Exact DOCS CI: `34906622356` — Ubuntu + Windows SUCCESS, 901 tests/OS
> Clean REAL generation: `d320a651-c2a4-403e-9322-a37630fcea6e`
> Supervisor result: **ACCEPT WITH SCOPE**
> Merge authorization: **NO**

## 0. Accepted Round 2 baseline — do not re-implement it

Round 2 is accepted only within its documented scope.

### REAL
- exact-CODE clean Blender 5.2.1 LTS / OptiX, `usedMock=false`;
- `HERO_ORBIT_8S` 96 frames;
- `ARTWORK_DETAIL_6S` 72 frames;
- `SMALL_ROOM_10S` 120 frames;
- 288 total frames, 1728 Product Truth control artifacts + 120 independent room-context masks;
- actual bytes/SHA/size, camera/product matrices, masks, finite EXR checks, first/middle/last `.blend` reopen, DAM/job lineage and persisted reload.

### REAL_LOGIC
- durable attempt exact-set/index verification;
- every prior journal verified before retry, idempotent replay or publication;
- missing/renamed/duplicate/foreign/corrupt history fails closed;
- candidate artifact bytes and DAM tenant/job/frame/role lineage are rebound;
- prior PASS blocks later retry;
- corruption blocks preview/final publication and creates no new DAM writes;
- SMALL_ROOM context geometry/mask is isolated from Product Truth;
- render cache is bound to video authority/recipe identity.

### FIXTURE / MOCK
- synthetic explicit 800×295×900 four-door cabinet;
- generated asymmetric artwork;
- CI Blender path is MOCK;
- copied candidate pixels are `FIXTURE_COPY` and are not live H3/LTX output.

### PARTIAL
- 128×128 is a control/evidence preview, not final commerce quality;
- deterministic Product Lock QA is not semantic Vision;
- local persistence is not an OS trust boundary;
- total rewriting/deletion of all journals + index anchors + local DAM is outside the proven integrity boundary;
- historical V1 journal sets without the durable index fail closed and have no automatic repair/migration.

### BLOCKED / false
- `DOOR_OPEN_REAL=false`;
- independent video articulation/assembly authority not yet proven;
- `visionQaReady=false`;
- `liveH3MaxProviderReady=false`;
- `liveLtx25ProviderReady=false`;
- `liveProviderReady=false`;
- Final Commerce Video;
- physical UV/RIP/print/hot-folder/machines;
- LIVE_CNC / LIVE_LASER / PLC;
- Supervisor LIVE prerequisites;
- `globalProductionReady=false`;
- `fullAutonomousFactoryReady=false`.

The excluded formal run `d5d7140b-4b9a-420b-a75d-2c3be56ac3d3` remains an excluded failed attempt with undetermined root cause. Do not rewrite history to make it PASS. The later clean PASS on unchanged CODE is accepted; investigate the watchdog only if the failure recurs.

## 1. Round 3 objective

Continue **only on existing PR #13**. Do not open a stacked PR and do not auto-merge PR #7–#13.

The next objective is:

**Build a narrow authoritative bridge from an independently resolved current-main door articulation authority into the existing Issue #6 video pipeline, then produce a clean REAL `DOOR_OPEN_8S` ground-truth acceptance.**

Do not rewrite Scheduler, Queue, DAM, Recipe, TwinStore, CabinetSpec, Product Truth, Artwork Placement, Product Truth Render Pack, Product Content Factory, Blender geometry interpretation, or the accepted Round 2 video pipeline.

Current main already contains Product Content Factory/front-open logic and worker-observed articulation evidence. Treat that only as a candidate independent authority source. Before enabling `DOOR_OPEN_8S`, resolve an exact durable authority from current main. If an exact authority cannot be resolved, STOP as `BLOCKED_ARTICULATION_AUTHORITY`; do not infer or fabricate it.

Important: existing convenience/default behavior such as a fallback `75.0` angle must **not** become Video Ground Truth authority. No default angle, guessed hinge, mesh inference, Vision inference, or generated pixel may authorize motion.

## 2. Required `ArticulationAuthority` contract

Add the smallest adapter/contract necessary. Reuse existing engineering/product identity structures where possible.

For every moving door, the frozen authority must include or resolve exactly:
- `tenantId`;
- `productId` / `sku`;
- `productVersion`;
- `engineeringHash`;
- Product Truth generation/hash identity;
- `componentId` and exact Blender/object identity;
- component role proving it is an authorized door;
- hinge pivot as finite 3-vector in a declared coordinate space;
- normalized hinge axis as finite 3-vector;
- authorized CLOSED angle;
- authorized OPEN angle or explicit min/max range;
- rotation convention/order and parent transform identity;
- closed transform and expected open transform, or enough independent authority to derive both deterministically;
- authority revision/source identity;
- canonical authority hash/seal.

The verifier must independently recompute the authority hash and fail closed on:
- missing/blank fields;
- bool-as-number, NaN, Inf or non-finite coordinates;
- zero/non-normalizable axis;
- pivot/axis/range outside declared schema;
- duplicate component authority;
- non-door component;
- wrong tenant/product/version/engineering/Product Truth identity;
- stale authority revision/hash;
- mismatched parent/object identity;
- supplied open transform contradicting canonical pivot/axis/angle;
- cross-product or cross-tenant authority substitution.

No VideoRecipe may silently substitute a hard-coded `75.0` when authority is absent.

## 3. `DOOR_OPEN_8S` deterministic ground-truth recipe

Implement `DOOR_OPEN_8S` inside the existing video recipe/pipeline, not as a second pipeline.

Control acceptance target:
- duration: 8 seconds;
- FPS: 12;
- 96 frames;
- 128×128 evidence/control resolution only;
- same frozen synthetic reference product/artwork identity used by Round 2 unless an explicitly documented equivalent fixture is necessary;
- no room-context dependency unless the recipe explicitly declares it.

Motion requirements:
- frame 0 must match canonical CLOSED state;
- final authorized open segment must match the exact authority-defined OPEN state;
- interpolation/easing may be deterministic, but every frame angle must remain within the authorized range;
- per-frame expected angle/transform must be derived from frozen authority + recipe time, not from worker output;
- worker-observed object matrix / hinge angle must be recorded and compared back to canonical expectation;
- all non-authorized moving components must remain invariant;
- cabinet body/Product Truth geometry may not drift because a door is animated;
- artwork/placement/UV identity must stay frozen; if artwork is attached to an opening door, its transform must follow the authorized door object without becoming a new Product Truth source.

For each frame keep the accepted control bundle:
- Beauty;
- Depth;
- Normal;
- ProductMask;
- ArtworkMask;
- Alpha;
- camera matrix/intrinsics;
- product matrix;
- authorized door component matrix/angle;
- authority hash, manifest, receipt and job lineage.

First/middle/last `.blend` reopen must observe the actual door transform and verify it against authority. The final acceptance must verify actual artifact bytes/SHA/size and DAM metadata, not only manifest declarations.

## 4. Fail-closed adversarial matrix

Add focused tests without weakening existing 901 regressions. At minimum cover:
- no articulation authority;
- blank/missing component ID;
- non-door component ID;
- duplicate door authority;
- wrong tenant/product/version/engineeringHash/Product Truth generation;
- stale authority revision/hash;
- zero/invalid axis;
- pivot tamper;
- axis tamper;
- closed/open angle/range tamper;
- hard-coded/default 75° attempting to bypass missing authority;
- forged expected open transform;
- worker-observed angle mismatch;
- worker-observed matrix mismatch even if reported scalar angle matches;
- unexpected movement of cabinet body or another door/component;
- authority hash changed while cache key is reused;
- cross-recipe cache reuse from HERO/DETAIL/ROOM;
- manifest/receipt/authority seal tamper;
- reopen observation mismatch;
- retry/publication after authority or prior-attempt corruption.

Invalid authority/evidence must produce no unauthorized new attempt, accepted preview, final publication, or new authoritative DAM output.

Keep the accepted Round 2 durable candidate lineage tests unchanged unless a narrow compatibility fix is required.

## 5. Tests and evidence gate

### A. CODE gate

After implementation:
1. run full local `pytest -q`;
2. run focused video/articulation tests;
3. push one frozen final CODE SHA on existing PR #13;
4. obtain exact CODE SHA Ubuntu + Windows GitHub Actions SUCCESS;
5. CI Mock Blender remains regression evidence only.

If any unrelated architecture rewrite appears in the diff, stop and remove it before Re-Gate.

### B. Clean REAL Blender acceptance

On the exact final CODE SHA from a clean working tree, run a dedicated Round 3 E2E using actual Blender 5.2.1 LTS / OptiX with `usedMock=false`.

Required REAL acceptance:
- `DOOR_OPEN_8S` 96 frames with frozen independent articulation authority;
- one static/control recipe (`HERO_ORBIT_8S` is preferred) proving unchanged Product Truth identity and no cross-recipe/cache contamination;
- actual first/middle/last visual inspection and `.blend` reopen;
- actual matrices/angles/bytes/SHA/size/masks/EXR/DAM/job lineage;
- clean working tree and exact CODE SHA;
- explicit `doorOpenReal=true` only if all authority + worker-observation checks pass.

Do not needlessly rerender ARTWORK_DETAIL/SMALL_ROOM if their implementation is untouched; preserve their accepted Round 2 evidence and run targeted regressions instead. If shared code changes could invalidate them, rerun the affected REAL sequences.

If the current-main authority cannot provide exact pivot/axis/range/transform semantics, the correct result is `DOOR_OPEN_REAL=false` / `BLOCKED_ARTICULATION_AUTHORITY`. Do not manufacture an authority to make the test pass.

## 6. Truth matrix for Round 3

Until clean REAL acceptance succeeds:

### REAL
- Round 2 HERO/ARTWORK_DETAIL/SMALL_ROOM accepted evidence only.

### REAL_LOGIC
- accepted Round 2 durable lineage/context isolation;
- new articulation authority resolution/verification only after its independent binding tests pass.

### FIXTURE / MOCK
- synthetic reference cabinet/artwork;
- CI Blender;
- provider candidate copies.

### PARTIAL
- 128×128 control quality;
- deterministic non-Vision QA;
- `DOOR_OPEN_8S` while authority or REAL evidence is incomplete.

### BLOCKED
- assembly/exploded-video authority unless independently proven;
- live H3/LTX/Vision/provider;
- Final Commerce Video;
- physical print/machines;
- Supervisor LIVE/global/full-autonomous readiness.

Only after exact authority + exact-CODE clean REAL evidence passes may `DOOR_OPEN_REAL=true` and `doorOpenGroundTruthReady=true` be reported for this scoped synthetic reference acceptance. That does **not** imply Final Commerce Video or global Production Ready.

## 7. Required docs

After frozen CODE + REAL run:
- create/update `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ROUND3_ACCEPTANCE.md`;
- create/update `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ROUND3_ACCEPTANCE.json`;
- update `docs/GROK_PROGRESS_REPORT.md`;
- update `docs/CURRENT_IMPLEMENTATION_AUDIT.md`;
- update `docs/REAL_E2E_ACCEPTANCE.md` only with scoped video readiness facts that actually changed.

Do not modify `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet engineering truth itself changes. This phase should bridge an existing authority, not redefine cabinet engineering.

Commit evidence/docs separately as a DOCS SHA and require exact DOCS SHA Ubuntu + Windows CI SUCCESS.

## 8. Final handoff and STOP

Only after CODE CI + clean REAL acceptance + DOCS CI are complete, post `READY_FOR_RE_GATE` to Issue #1 and Issue #6 with at least:
- `INSTRUCTION_SHA`;
- `ISSUE=6`;
- `PR=13`;
- `ROUND=3`;
- `CODE_SHA`;
- `DOCS_SHA`;
- `CODE_CI_RUN_ID`;
- `DOCS_CI_RUN_ID`;
- test counts;
- `EVIDENCE_GENERATION_ID`;
- `WORKING_TREE_CLEAN=true`;
- `REAL_BLENDER=true|false`;
- `USED_MOCK=true|false`;
- `ARTICULATION_AUTHORITY_READY=true|false`;
- `DOOR_OPEN_REAL=true|false`;
- `DOOR_OPEN_GROUND_TRUTH_READY=true|false`;
- `HERO_ORBIT_REAL=true|false`;
- `VISION_QA_READY=false`;
- `LIVE_H3_PROVIDER_READY=false`;
- `LIVE_LTX_PROVIDER_READY=false`;
- `LIVE_PROVIDER_READY=false`;
- `GLOBAL_PRODUCTION_READY=false`;
- `MERGE_AUTHORIZED=false`.

List REAL / REAL_LOGIC / FIXTURE / MOCK / PARTIAL / BLOCKED separately and then **STOP for external Re-Gate**.

## 9. Forbidden

- no auto-merge PR #7–#13;
- no stacked PR;
- no architecture rewrite;
- no dependency on unmerged PR #7–#12;
- no guessed/default hinge pivot, axis, angle or range;
- no default `75.0` as authority;
- no mesh/Vision/generative inference as engineering authority;
- no Mock/FIXTURE/REFERENCE → REAL promotion;
- no CI Mock Blender → REAL Blender promotion;
- no provider candidate pixel → Product Truth promotion;
- no live provider/Vision readiness claim without real network evidence;
- no Final Commerce Video claim from control previews;
- no physical print/machine write;
- no unscoped Production Ready claim.
