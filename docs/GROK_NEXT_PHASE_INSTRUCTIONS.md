# Development Agent 修正指令：Phase 901–960 Re-Gate Round 2 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Legacy watcher filename: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`
> Reviewed CODE: `4406119cbf5bc62dcb43d0dd1ec6fc041353dd28`
> Reviewed docs/head: `aac040c292d07289ec358171af11d12c65b7fb33`
> Product Content acceptance generation: `57f72869-a017-415f-bf66-7df55824d486`
> CODE Actions: `34740940584` — SUCCESS on exact CODE SHA
> docs/head Actions: `34741953464` — still IN_PROGRESS at Re-Gate time; do not count it as completed evidence
> Full pytest reported: **628 passed**
> Re-Gate result: **CHANGES REQUIRED — Phase 961+ HOLD.**

## 0. Accepted work — preserve it

Do not rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth / Artwork authorities. This is correction-only.

Accepted within scope:

- REAL commerce render artifacts now fail closed on missing worker record/path, missing file, zero bytes, malformed PNG, and wrong dimensions.
- `FRONT_OPEN` / `FRONT_CLOSED` now publish observed `workerViews` articulation evidence and compare observed transforms/angle/state against independently derived Engineering expectations.
- required DAM identity/source metadata is materially stricter than Round 1.
- `DIMENSION_FRONT` now rasterizes deterministic visible W/H/D numeric labels with repository-controlled `FONT_5X7`, and QA independently recomputes `dimensionLabelLayerHash`.
- Ground/AOV isolation regression was corrected in CODE `4406119`; keep baseline `_add_box` half-scale authority intact.
- Fresh clean-tree REAL Blender 5.2.1 LTS + NVIDIA T1000 OptiX evidence exists with `usedMock=false`.
- Truth boundaries remain correct: live H3 MAX/LTX 2.5 BLOCKED, Vision MOCK/BLOCKED, physical print false, LIVE CNC/LASER/PLC BLOCKED, and all commercial/global/full/live readiness flags false.

Do not continue unrelated UI/control-plane refactors in this correction round.

## 1. Blocker A — Product Truth acceptance-generation lineage is currently synthetic/fail-open

The current runner can mint a fallback acceptance id:

```python
f"pt_acc_{upstream_pack.get('renderPackId')}"
```

when the current Product Truth render pack does not match a real `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json` generation. The current Product Content acceptance demonstrates this problem: it binds `sourceRenderPackId=c2d620ab-...` to `sourceAcceptanceGenerationId=pt_acc_c2d620ab-...`, while the actual committed Product Truth acceptance file still identifies generation `78ef13b7-...` / renderPack `784df4d3-...` / CODE `cb045af`.

This is not an externally established acceptance generation. It is a self-created label derived from the renderPackId, so the current lineage can be internally consistent while not pointing to a real accepted Product Truth bundle.

### Required correction

1. Remove every fallback that fabricates a Product Truth acceptance generation from `renderPackId` or another current payload field.
2. Product Content must consume a **real Product Truth acceptance authority** produced/published before Product Content publication.
3. If the newly generated Product Truth render pack does not have a matching acceptance authority, fail closed or first execute/publish the existing Product Truth acceptance step; do not manufacture an id in Product Content.
4. The consumed Product Truth acceptance authority must bind at minimum:
   - acceptanceGenerationId
   - exact Product Truth renderPackId
   - exact Product Truth evidenceCodeCommit
   - tenantId
   - product/SKU id + version
   - engineeringHash
   - placementHash + finalUvHash
   - ProductMask / ArtworkMask DAM refs + SHA
   - `usedMock=false` for REAL path
   - clean-tree evidence where the existing acceptance process requires it
5. Product Content `sourceAcceptanceGenerationId` must exact-match that externally published authority.
6. QA must independently load/receive that authority; do not mutate `upstream_pack` to make expected and observed values match before validation.

### Required negative cases

- missing Product Truth acceptance generation;
- synthetic `pt_acc_<renderPackId>` value;
- stale generation belonging to another renderPackId;
- right renderPackId but wrong Product Truth CODE SHA;
- generation copied from another tenant/SKU/version;
- generation with wrong engineeringHash / placementHash / finalUvHash / mask refs.

## 2. Blocker B — observed Camera/Scene authority is not validated; current REAL acceptance already shows a passing mismatch

The current Product Content acceptance is `ok=true`, but `WHITE_BACKGROUND_HERO` contains a concrete contradiction:

- canonical commerce recipe `cameraRecipeHash = 3c95d2afedf4...`
- observed `workerEvidence.cameraRecipeHash = 4b8d92f7601...`
- observed `workerEvidence.sceneRecipeHash = null`

QA currently validates role/job/device/articulation, but does not require observed worker camera/scene hashes to exact-match the canonical commerce recipe. Therefore a worker may render the wrong camera/scene while the manifest recipe remains correct and acceptance can still pass.

### Required correction

1. Include canonical `cameraRecipeHash` and `sceneRecipeHash` explicitly in each commerce Blender view payload.
2. In the Blender worker, publish the **observed/applied** camera and scene semantic hashes after applying the view, not a blind copy of expected payload fields.
3. For every REAL rendered commerce role, QA must require:
   - worker `cameraRecipeHash` present and exact-match canonical recipe hash;
   - worker `sceneRecipeHash` present and exact-match canonical recipe hash;
   - role/view id and job id exact;
   - observed camera semantic fields (location/lookAt/focal/sensor/safe margin/resolution) consistent with the canonical recipe or independently rehashed to the same hash.
4. Missing/null camera or scene hash = FAIL.
5. Wrong camera with a correct manifest recipe = FAIL.
6. Cross-view worker camera/scene evidence = FAIL.
7. Preserve Phase 841–900 Camera/Scene semantic-authority rules; reuse them instead of creating a second hashing scheme.

### DIMENSION_FRONT derivation

`DIMENSION_FRONT` is derived from `FRONT_CLOSED`; do not imply that it is an independently Blender-rendered worker view.

Publish explicit derivation lineage such as:

- `derivedFromViewRole=FRONT_CLOSED`
- source DAM ref / SHA
- source Blender job id
- source worker-evidence hash or equivalent stable lineage

QA must exact-match this derivation lineage and separately validate the deterministic dimension overlay authority.

### Required negative cases

- observed camera hash differs but manifest recipe remains canonical;
- missing observed scene hash;
- cross-swapped camera evidence between HERO_45 and FRONT_OPEN;
- wrong location/focal/safeMargin with forged/copied hash;
- DIMENSION_FRONT points to another view/DAM/job;
- correct dimension pixels but stale/foreign FRONT_CLOSED derivation source.

## 3. Blocker C — remaining asset/mask integrity checks are still conditional instead of required

Round 1 improved DAM metadata checks, but several authority fields still use truthy-condition validation. Missing evidence can therefore skip comparison.

### Required correction

1. `productMaskRef` and `artworkMaskRef` must each require non-empty `damRef` and `sha256`; exact-match upstream Product Truth. Missing fields = FAIL.
2. Every required commerce view must require non-empty:
   - `sha256`
   - positive `size`
   - width / height
   - `format=PNG`
   - DAM ref
   - source path
   - job/derivation lineage
3. DAM bytes/path SHA and size checks must be unconditional after the field is required. Do not use `if v_data.get("sha256") ...` or `if v_data.get("size") ...` as a way to skip missing authority.
4. For REAL rendered views, DAM `blenderVersion`, `device`, and `usedMock=false` must exact-match observed worker evidence, not merely be present.
5. For derived DIMENSION_FRONT, provenance must exact-match the validated FRONT_CLOSED source plus deterministic overlay lineage.
6. Add fail-closed tests for missing mask refs/SHA, missing view SHA/size, altered version/device, foreign DAM with identical bytes, and missing derivation lineage.

## 4. Evidence process for Round 2

1. Make only the corrections above; preserve accepted architecture and behavior.
2. Run full `pytest -q`; report exact count. Mock/FIXTURE tests are not Production Ready.
3. Commit/push exact CODE SHA.
4. Wait for Ubuntu + Windows SUCCESS on that exact CODE SHA; record run/job IDs.
5. On a clean tree at that CODE SHA, produce a fresh REAL Product Truth acceptance authority first, with Blender 5.2.1 LTS + NVIDIA T1000 OptiX and `usedMock=false`.
6. Then run Product Content acceptance consuming that exact Product Truth acceptance authority. No fabricated acceptance-generation fallback is allowed.
7. Acceptance must prove exact observed camera/scene, articulation, DAM/source lineage, mask lineage, DIMENSION_FRONT derivation, and deterministic visible dimension labels.
8. Commit docs/evidence separately and wait for Ubuntu + Windows SUCCESS on the exact docs SHA.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, `docs/PRODUCT_CONTENT_FACTORY_ACCEPTANCE.{md,json}`, and Product Truth acceptance docs only when supported by fresh evidence. Leave `docs/CABINET_REAL_ACCEPTANCE.md` unchanged unless cabinet truth actually changes.
10. Add an Issue #1 handoff with CODE SHA, docs SHA, pytest count, both CI runs, Product Truth acceptance generation, Product Content acceptance generation, and REAL/MOCK/PARTIAL/BLOCKED summary.
11. STOP for ChatGPT Re-Gate. **Phase 961+ remains HOLD.**

## 5. Truth boundaries remain fixed

Until independent new REAL evidence exists:

- live H3 MAX / LTX 2.5 = BLOCKED;
- Vision Judge = MOCK/BLOCKED;
- physical print = false/BLOCKED;
- LIVE_CNC / LIVE_LASER / PLC = BLOCKED;
- `commercialAssetProductionReady=false`;
- `globalProductionReady=false`;
- `fullAutonomousFactoryReady=false`;
- `liveFactoryExecutionReady=false`.

Do not label Mock, fixture, metadata-only evidence, self-minted lineage ids, copied expected hashes, or recomputed expected state as observed Production/REAL execution evidence.
