# Development Agent 下一輪開發指令：Phase 841–900 Re-Gate Round 6 — Frozen Recipe Semantic Authority / Evidence Lineage Final Closure

> Repo: `netfox-web/blender-autonomous-3d`  
> Legacy filename kept for watcher compatibility: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`  
> Reviewed CODE: `e63fe7aa4554ac372c256fe43ea127113a8ed91d`  
> Reviewed docs/head: `c3dfb6215560fb76f40d20fbdc2f06723f949d04`  
> Acceptance generation: `c28a6bc6-4ced-436d-ac95-9aa3562f81bb`  
> CODE Actions: `34707952458` — Ubuntu `103591328351` SUCCESS + Windows `103591328425` SUCCESS  
> docs/head Actions: `34709093768` — still IN_PROGRESS at Re-Gate time; do not count as completed evidence until both jobs are SUCCESS  
> Reported full pytest: **619 passed**  
> Re-Gate result: **CHANGES REQUIRED — Phase 901+ HOLD.**

## 0. Scope / fixed rules

Correction-only. Do **not** rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / ArtworkPlacement / ManufacturingRelease / WorkOrder / MaterialLot / Backup/Restore. Do not create another mm/UV/Product Truth source of truth.

Keep all current truth boundaries honest:

- Product Truth Blender execution: scoped **REAL / REAL_LOGIC**.
- ProductMask / FRONT PrintableSurface ArtworkMask: scoped REAL artifacts.
- Generative Gateway contract: **REAL_LOGIC**.
- live H3 MAX / LTX 2.5: **BLOCKED**.
- Vision Judge: **MOCK / BLOCKED**.
- physical print: **BLOCKED / false**.
- LIVE_CNC / LIVE_LASER / liveFactory execution: **BLOCKED**.
- `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`.

Mock/FIXTURE is not Production Ready. Do not enter Phase 901+ until a later ChatGPT Re-Gate explicitly says GO.

## 1. Accepted from Round 5 — do not regress

The following are accepted within scope and should not be rewritten:

1. Exact CODE SHA `e63fe7aa4554ac372c256fe43ea127113a8ed91d` has GitHub Actions run `34707952458`, Ubuntu + Windows SUCCESS.
2. The official runner now rejects a missing/partial required frozen authority instead of borrowing tenant/placement/engineering/camera/scene/view authority from the final pack, worker evidence, or serialized `expectedIdentity`.
3. The 23-case official-runner adversarial matrix is present and executes through `run_product_truth_render_e2e.main()`, asserting rejected cases do not publish a successful Product Truth acceptance artifact.
4. DAM view evidence now binds exact view role, source path, source job, row/worker path, live bytes, SHA/size, dimensions, `blenderJobId`, and top-level/nested worker-view agreement.
5. Fresh clean-tree REAL acceptance generation `c28a6bc6-4ced-436d-ac95-9aa3562f81bb` is bound to CODE `e63fe7aa...`, Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`.
6. ProductMask and FRONT PrintableSurface ArtworkMask remain separate artifacts with different SHA/occupancy; do not alias them.
7. REAL/MOCK/PARTIAL/BLOCKED labeling remains honest: live H3/LTX blocked, Vision mock/blocked, physical print false, live machine control blocked, global/full/live readiness false.
8. `docs/CABINET_REAL_ACCEPTANCE.md` did not need rewriting and should remain unchanged unless cabinet truth genuinely changes.

## 2. Blocker A — frozen Camera/Scene/View authority only proves a hash exists, not that the frozen recipe is semantically valid

Round 5 removed the pack fallback, but the pre-worker frozen recipe objects are still not fully self-authenticating.

Current strict path effectively does this for camera/scene/view recipes:

- verify the object is a dict;
- verify `cameraRecipeHash` / `sceneRecipeHash` exists;
- copy that hash into canonical expected identity.

`derive_canonical_expected_identity(..., strict=True)` likewise currently accepts the supplied camera/scene/view hash without independently rebuilding the hash from the frozen object's semantic fields.

That leaves a coordinated evidence hole: a frozen request can have semantic fields changed while retaining the old hash, yet still be treated as valid frozen authority. The final pack's own recipe re-hash does not close this gap because the frozen pre-worker request itself must be internally valid before it is allowed to become authority.

### Required correction

Use the existing CameraRecipe / SceneRecipe helpers and schema. Do not create a new recipe authority.

For the official publication/Re-Gate path:

1. Validate the frozen main CameraRecipe semantically and recompute its canonical hash from its actual frozen fields.
2. Validate the frozen SceneRecipe semantically and recompute its canonical hash from its actual frozen fields.
3. Validate both frozen required view recipes (`DOOR_DETAIL`, `ASSEMBLED_FRONT`) semantically and recompute each canonical CameraRecipe hash from its actual frozen fields.
4. The stored frozen hash must exactly equal the recomputed hash. Any mismatch must reject publication before using the final pack as evidence.
5. Required semantic fields must be strict typed. Do not silently default a missing/malformed frozen field to a normal default merely to reproduce a hash. Reuse existing strict numeric helpers where appropriate: bool-as-number, string numbers, NaN, +Inf, -Inf must not pass as valid recipe values.
6. Validate semantic view identity: the frozen `DOOR_DETAIL` recipe must identify DOOR_DETAIL, and frozen `ASSEMBLED_FRONT` must identify ASSEMBLED_FRONT. Cross-swaps must fail.
7. If frozen `engineering` and a top-level frozen `engineeringHash` are both present, they must agree after canonical recomputation/validation. Do not select one while ignoring a contradictory duplicate.
8. Do not use final `pack.cameraRecipe`, `pack.sceneRecipe`, `pack.views`, worker evidence, or serialized `expectedIdentity` to repair invalid frozen recipe semantics.

### Required official-runner negative tests

All tests below must execute through the real publication runner and assert FAIL/BLOCK plus **no successful `PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json` publication**:

1. frozen main camera: change `focalLengthMm` but keep stale `cameraRecipeHash`;
2. frozen main camera: change location/lookAt/sensor/resolution/safeMargin while keeping stale hash;
3. frozen main camera: change only `cameraRecipeHash` while fields remain unchanged;
4. frozen scene: change samples/engine/lighting/scene identity while keeping stale `sceneRecipeHash`;
5. frozen scene: change only `sceneRecipeHash` while fields remain unchanged;
6. frozen `DOOR_DETAIL`: change semantic camera field but retain stale hash;
7. frozen `DOOR_DETAIL`: hash-only tamper;
8. frozen `ASSEMBLED_FRONT`: change semantic camera field but retain stale hash;
9. frozen `ASSEMBLED_FRONT`: hash-only tamper;
10. swap frozen DOOR_DETAIL and ASSEMBLED_FRONT recipe objects/hashes;
11. malformed/missing required numeric recipe fields, including bool/string/NaN/Inf where applicable;
12. frozen engineering body/hash contradiction if both copies are present.

Keep the existing Round 5 23-case matrix; add these semantic-authority cases rather than replacing it.

## 3. Blocker B — exact instruction lineage in docs is wrong

`docs/GROK_PROGRESS_REPORT.md` currently reports this full Source instruction SHA:

`2b1b174092b3bc3983226782390885141154f243`

That SHA is not the actual Round 5 instruction commit. The real instruction commit is:

`2b1b174d0ebeb1e8ced6ff73faba5d2fc18fd7ee`

This is an evidence-lineage defect. Prefix `2b1b174` happens to look right, but exact evidence must never contain a fabricated/near SHA.

### Required correction

1. Correct the exact Source instruction SHA in `docs/GROK_PROGRESS_REPORT.md`.
2. Search the Round 5 evidence/docs for the wrong full SHA and correct any other occurrence that claims exact lineage.
3. Do not modify historical SHA values that are actually correct.
4. Add a small regression/test or deterministic evidence-generation check if practical so an instruction SHA written into a report comes from the real git/input value rather than hand transcription.

## 4. Evidence completion / CI gate

Round 5 docs/head run `34709093768` was still IN_PROGRESS when this Re-Gate checked it. It is not a failure, but an in-progress run is not completed acceptance evidence.

For Round 6 use the same strict two-phase process:

1. Run full `pytest -q`; report exact count and preserve labels (MOCK/FIXTURE tests are not Production Ready).
2. Commit **CODE + tests only** first; push the exact CODE SHA.
3. Wait for exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS; record run ID and both job IDs/results.
4. On a clean working tree at that exact CODE SHA, run fresh REAL Blender 5.2.1 + NVIDIA T1000 OptiX Product Truth acceptance with `usedMock=false`.
5. Verify ProductMask and FRONT PrintableSurface ArtworkMask remain distinct; verify DOOR_DETAIL and ASSEMBLED_FRONT both have valid, independently bound worker/DAM evidence.
6. Verify the official-runner old 23-case matrix and the new frozen-recipe semantic matrix all fail closed as intended.
7. Update only necessary docs/evidence in a separate docs commit:
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md/.json`
   - Generative acceptance only if its evidence actually changes.
8. Leave `docs/CABINET_REAL_ACCEPTANCE.md` unchanged unless cabinet truth changes.
9. Push docs commit and wait for exact docs/head Ubuntu + Windows SUCCESS; record run/job IDs.
10. Update Issue #1 with instruction SHA, CODE SHA, docs SHA, pytest count, CODE CI, docs CI, fresh acceptance generation, and exact REAL/MOCK/PARTIAL/BLOCKED boundary summary.
11. STOP for ChatGPT Re-Gate. **Do not start Phase 901+.**

## 5. Definition of Done for Round 6

All must be true:

- frozen main CameraRecipe semantic fields are strict-validated and their hash is independently recomputed;
- frozen SceneRecipe semantic fields are strict-validated and their hash is independently recomputed;
- frozen DOOR_DETAIL / ASSEMBLED_FRONT recipes are strict-validated, exact view identity bound, and hashes independently recomputed;
- stale-hash semantic drift and hash-only tampering in frozen authority fail through the official runner;
- frozen engineering body/hash contradictions fail if both are present;
- no invalid frozen authority case can bootstrap from final pack / worker / serialized expected copies;
- all prior Round 5 zero-fallback, 23-case, camera-worker, DAM source/job/path and ArtworkMask protections stay green;
- wrong full Round 5 instruction SHA is corrected to `2b1b174d0ebeb1e8ced6ff73faba5d2fc18fd7ee` wherever it is claimed as exact lineage;
- full pytest passes;
- exact CODE SHA dual-platform CI succeeds;
- fresh clean-tree REAL T1000 OptiX evidence succeeds on exact CODE SHA;
- docs/head exact SHA dual-platform CI succeeds;
- H3/LTX remain BLOCKED, Vision remains MOCK/BLOCKED, physical print remains false, LIVE_CNC/LASER remain BLOCKED, global/full/live readiness remain false;
- Phase 901+ remains HOLD until ChatGPT explicitly releases it.
