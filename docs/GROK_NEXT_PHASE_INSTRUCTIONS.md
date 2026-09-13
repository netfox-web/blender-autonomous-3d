# Development Agent 修正指令：Phase 901–960 Re-Gate Round 1 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Legacy watcher filename: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`
> Reviewed CODE: `2fcac7eacf79e868f0392d41e8d9f8dd70979ffd`
> Reviewed docs/head: `73da1a555627ee3acc1428b0ebb5ee5eba14f0d0`
> Acceptance generation: `14eac4b8-0217-40e8-968d-fc7ca7a6de4e`
> CODE Actions: `34733898962` — SUCCESS on exact CODE SHA
> docs/head Actions: `34734842881` — SUCCESS on exact docs SHA
> Full pytest reported: **628 passed**
> Re-Gate result: **CHANGES REQUIRED — Phase 961+ HOLD.**

## 0. What is accepted in this round

Keep the existing architecture and accepted work. Do **not** rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth / Artwork authorities.

Accepted within scope:

- `src/fox3d/content_factory.py` exists and produces the canonical 6-role content-pack shape.
- Fresh REAL Blender 5.2.1 LTS + NVIDIA T1000 OptiX acceptance was produced with `usedMock=false`.
- Required view roles exist: `WHITE_BACKGROUND_HERO`, `HERO_45`, `FRONT_CLOSED`, `FRONT_OPEN`, `DETAIL_ARTWORK`, `DIMENSION_FRONT`.
- lifestyle briefs remain derivative; live H3 MAX / LTX 2.5 remain BLOCKED.
- Vision remains MOCK/BLOCKED; physical print remains false; LIVE_CNC/LASER/PLC remain BLOCKED.
- `commercialAssetProductionReady=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false` remain correct.

This round is correction-only. Do not start Phase 961+.

## 1. Blocker A — bind REAL manifest state to observed Blender worker evidence, not a recomputed expectation

Current REAL path reads `workerViews`, but then constructs manifest `articulatedState` with `build_articulated_state(engineering, ...)` instead of publishing and validating the **observed** worker state from `workerViews`.

That means a broken Blender worker could render `FRONT_OPEN` without actually articulating the doors while the manifest still contains a freshly recomputed expected OPEN state and the QA gate could pass.

### Required correction

For every REAL Blender commerce view:

1. Require an exact `workerViews[role]` record from the completed Blender job. Missing worker record = FAIL.
2. Publish the observed worker record/provenance into the content-pack view, including at minimum:
   - exact role/view id
   - rendered source path
   - `blenderJobId`
   - observed CameraRecipe hash
   - observed SceneRecipe hash where available
   - observed product state
   - observed articulation angle
   - observed component transform set / hinge pivots / rotations for `FRONT_OPEN`
   - Blender version
   - device / OptiX evidence
   - worker identity if exposed by the existing worker result
   - `usedMock=false` / REAL execution evidence
3. Independently derive canonical expected state from Engineering + recipe, then compare **observed worker evidence ↔ canonical expected**. Do not replace observed evidence with the expected structure.
4. `FRONT_OPEN` must fail if observed state is CLOSED, angle is zero/wrong, transform set is missing, component IDs differ, pivot/rotation differs, or the worker evidence belongs to another view/job.
5. `FRONT_CLOSED` must fail if observed articulation is non-zero.
6. Preserve existing worker output; extend/bind it, do not create a second geometry or articulation source of truth.

### Required official-runner negative cases

Add fail-closed cases through `scripts/run_product_content_e2e.py` for:

- worker reports CLOSED for `FRONT_OPEN` while manifest expected state is still OPEN;
- wrong OPEN angle;
- missing transform(s) / wrong component ID / wrong hinge pivot;
- missing `workerViews[FRONT_OPEN]`;
- worker view belongs to wrong `blenderJobId` or wrong role;
- missing required REAL worker/device evidence;
- manifest recomputed expected state is correct but observed worker state is wrong — acceptance must still fail.

## 2. Blocker B — REAL asset path / DAM provenance is not fully fail-closed

Current REAL branch can fall through from a missing worker path to `data=b""` and fallback dimensions. QA also validates required provenance using conditional checks such as `if metadata.sourcePath ...`, which does not reject a missing required field.

Required commerce evidence must never pass because a required field is absent.

### Required correction

For each required REAL view before DAM publication and again in QA:

- source file must exist;
- file must be a valid PNG;
- bytes must be non-empty;
- stored DAM bytes must exactly match manifest SHA-256 and size;
- pixel dimensions must be read from the actual PNG and equal recipe dimensions;
- MIME must be explicit (`image/png`) and verified;
- DAM metadata must contain and exactly match:
  - tenantId
  - skuId
  - productVersion
  - contentPackId
  - commerce role / view role
  - source Product Truth renderPackId
  - source Product Truth acceptance generation id
  - sourcePath
  - sourceJobId / Blender job id
  - required worker/device provenance for REAL views
- missing required metadata must be a failure, not skipped by a truthy conditional.
- remove any REAL-path fallback that can turn a missing render artifact into zero bytes + synthetic width/height evidence.

The content pack must explicitly bind the **source Product Truth acceptance generation** in addition to the renderPackId. The current QA comment says “generation and render pack lineage” but only compares renderPackId; close this gap.

### Required official-runner negative cases

- worker source path missing;
- empty/zero-byte asset;
- malformed/non-PNG bytes;
- DAM `sourcePath` missing;
- DAM `sourceJobId` missing;
- wrong/missing MIME;
- wrong/missing tenant/SKU/version/contentPack/view-role metadata;
- wrong Product Truth acceptance generation with otherwise-correct renderPackId;
- foreign DAM object with valid identical bytes but wrong provenance.

## 3. Blocker C — DIMENSION_FRONT does not yet prove that the visible numeric labels are in the image

Current `generate_dimension_overlay()` draws guide lines and a dark badge, then stores strings such as `"2400 mm"` only in metadata (`renderedLabels`). The PNG itself is not shown to contain those numeric glyphs.

Therefore the current “renderedLabels” evidence proves metadata values, not a real dimension image with visible Engineering-driven labels. Coordinated pixel/metadata authority is not yet closed.

### Required correction

Create a deterministic visual dimension-label layer driven only from Engineering mm. No OCR is required.

Recommended minimal approach:

1. Rasterize canonical glyphs/text for width / height / depth + unit into a deterministic label layer using a repository-controlled renderer/bitmap font or another deterministic local implementation.
2. Composite that layer into `DIMENSION_FRONT`.
3. Preserve an independently reproducible `dimensionLabelLayerHash` / label-layer bytes manifest derived from frozen Engineering authority.
4. In QA, independently recompute expected label-layer bytes/hash from Engineering and compare exact-match before accepting the final dimension asset.
5. Bind unit and raw numeric values separately; do not round away non-integer Engineering values if the canonical Engineering type permits decimals.
6. The final dimension asset and its label-layer provenance must be DAM-bound to the same tenant/SKU/version/engineeringHash/contentPack.

Do not infer dimensions from pixels and do not use a live Vision model as authority.

### Required negative cases

- visible width glyph layer altered while metadata remains correct;
- metadata + visible label layer coordinated to a wrong width/height/depth;
- unit glyph changed (`mm` → another unit);
- label layer from another SKU/version reused;
- stale engineeringHash with otherwise matching image bytes;
- missing label layer/hash.

## 4. Keep the existing strict recipe and Product Truth protections

Do not weaken:

- Phase 841–900 frozen Camera/Scene/View semantic authority;
- ProductMask / ArtworkMask lineage;
- existing content recipe canonical hash comparison;
- existing 18-case matrix;
- clean-tree exact-CODE acceptance rules.

Add the corrections above on top of the current implementation.

## 5. Evidence process for Re-Gate Round 1

Follow the existing two-phase process exactly:

1. CODE + tests only.
2. Run full `pytest -q`; report exact count. Mock/FIXTURE tests are not Production Ready.
3. Commit/push exact CODE SHA.
4. Wait for Ubuntu + Windows SUCCESS on that exact CODE SHA and record run/job IDs.
5. On a clean tree at that exact CODE SHA run fresh REAL Blender 5.2.1 LTS + NVIDIA T1000 OptiX Product Content acceptance with `usedMock=false`.
6. The fresh acceptance must prove observed worker articulation/provenance, strict REAL asset presence/DAM lineage, source Product Truth acceptance-generation binding, and real visible dimension-label authority.
7. Commit evidence docs separately.
8. Wait for Ubuntu + Windows SUCCESS on the exact docs/head SHA.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, and `docs/PRODUCT_CONTENT_FACTORY_ACCEPTANCE.{md,json}` only as required. Leave `docs/CABINET_REAL_ACCEPTANCE.md` unchanged unless cabinet truth actually changes.
10. Update Issue #1 with CODE SHA, docs SHA, pytest count, CODE/docs CI, new acceptance generation, and REAL/MOCK/PARTIAL/BLOCKED summary.
11. STOP for ChatGPT Re-Gate. **Phase 961+ remains HOLD.**

## 6. Truth boundaries remain fixed

Until independent new REAL evidence exists:

- live H3 MAX / LTX 2.5 = BLOCKED;
- Vision Judge = MOCK/BLOCKED;
- physical print = false/BLOCKED;
- LIVE_CNC / LIVE_LASER / PLC = BLOCKED;
- `commercialAssetProductionReady=false`;
- `globalProductionReady=false`;
- `fullAutonomousFactoryReady=false`;
- `liveFactoryExecutionReady=false`.

Do not label Mock, fixture, metadata-only evidence, or recomputed expected state as observed Production/REAL execution evidence.
