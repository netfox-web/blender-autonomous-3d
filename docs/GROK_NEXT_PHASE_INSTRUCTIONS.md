# Development Agent 下一輪開發指令：Phase 841–900 Re-Gate Round 5 — Strict Publication Closure / Provenance Adversarial Matrix

> Repo: `netfox-web/blender-autonomous-3d`  
> Legacy filename kept for watcher compatibility: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`  
> Reviewed CODE: `475997ee1921498cd6147a1f88f3a265276c933c`  
> Reviewed docs/head: `7efa3272df45a29bd6f76cb0fc5c1f6b806c6efc`  
> Acceptance generation: `bb58ba9d-158c-4076-99a2-3306867b216c`  
> CODE Actions: `34697114368` — Ubuntu + Windows SUCCESS  
> docs/head Actions: `34698174978` — Ubuntu + Windows SUCCESS  
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

Mock/FIXTURE is not Production Ready. Do not enter Phase 901+ until the next ChatGPT Re-Gate explicitly says GO.

## 1. Accepted from Round 4 — do not regress

The following are accepted and should not be rewritten:

1. Exact CODE SHA `475997e...` has real GitHub Actions evidence: run `34697114368`, Ubuntu + Windows SUCCESS.
2. docs/head `7efa327...` has run `34698174978`, Ubuntu + Windows SUCCESS.
3. Fresh clean-tree REAL acceptance generation `bb58ba9d-158c-4076-99a2-3306867b216c` is bound to CODE `475997e...`, Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`.
4. ProductMask and FRONT PrintableSurface ArtworkMask remain distinct/non-alias.
5. Worker camera semantic re-hash and strict numeric schema remain accepted.
6. Nested `row.workerView` vs top-level `pack.workerViews[name]` conflict detection is directionally correct.
7. Basic `viewId`, filename/role, width/height, SHA/size, job-id, DAM tenant/SHA/role/renderPackId checks are present.
8. `CURRENT_IMPLEMENTATION_AUDIT.md` header is current.
9. REAL/MOCK/PARTIAL/BLOCKED labels are honest; live providers, physical print, Vision and live machine control remain blocked as required.
10. Persistent autonomous-agent rules in `AGENTS.md` / `GEMINI.md` may remain; do not broaden them to bypass Human Approval or live-machine safety boundaries.

## 2. Blocker A — strict publication runner still has pack fallback when frozen authority is partial

The official runner now uses `frozenAuthorityContext`, but strict publication still contains fallback paths such as:

```text
f_tenant_id = frozen_authority.tenant_id OR pack.tenantId OR "pt-a"
place_id = frozen_authority.placement.placementId OR pack.placementId
canonical_place = store[place_id]
```

Round 4 required **no final-pack / worker fallback in strict publication mode**. A completely missing frozen context is rejected, but a partially missing frozen context can still borrow required identity from the final pack.

### Required correction

For the official REAL publication/re-gate path only:

1. Validate the frozen pre-worker authority object **before** using the final pack for anything authoritative.
2. Required frozen fields must include, through existing sources/structures only:
   - tenant identity;
   - canonical placement identity / placementId;
   - canonical engineering request/lineage;
   - main CameraRecipe request;
   - SceneRecipe request;
   - required view request recipes for `DOOR_DETAIL` and `ASSEMBLED_FRONT`.
3. If any required frozen authority item is missing/invalid, append a specific blocker and refuse publication. Do **not** read `pack.tenantId`, `pack.placementId`, `pack.engineeringHash`, `pack.cameraRecipe`, `pack.sceneRecipe`, `pack.views[*]`, worker evidence or serialized `expectedIdentity` to fill that gap.
4. Canonical placement/surface/artwork must then be re-resolved from the existing ArtworkPlacement / PrintableSurface / artwork-DAM stores using the frozen request identity.
5. `pack.expectedIdentity` remains an evidence copy only; it must never bootstrap authority.
6. Do not add a second persistent authority database. Reuse the already-created pre-worker context and existing stores.

## 3. Blocker B — required official-runner adversarial matrix is incomplete

The current official-runner negative test covers only a subset: engineeringHash, main camera, DOOR_DETAIL camera, deleted surface, corrupted artwork bytes, and completely missing frozen context. Round 4 required the complete matrix through the **official runner/publication path**, not helper-only validation.

### Required full-run tests

For each case below, mutate coordinated copies in `pack` + `workerEvidence` + serialized `expectedIdentity` where applicable, execute the official runner, and prove:

- runner exit/result is FAIL/BLOCK;
- **no** `PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json` is published with `ok=true` (prefer no file at all on rejected publication).

Required cases:

1. `engineeringHash`
2. `placementHash`
3. `surfaceHash`
4. `finalUvHash`
5. `componentId`
6. `objectName`
7. `face`
8. artwork `artworkHash`
9. artwork SHA / authoritative artwork bytes
10. main `cameraRecipe` / `cameraRecipeHash`
11. `sceneRecipe` / `sceneRecipeHash`
12. `DOOR_DETAIL` requested camera recipe/hash
13. `ASSEMBLED_FRONT` requested camera recipe/hash
14. delete canonical placement record
15. delete canonical PrintableSurface / required surface record
16. delete canonical artwork/DAM authority record or replace its bytes
17. remove only frozen engineering authority
18. remove only frozen placement identity
19. remove only frozen main camera authority
20. remove only frozen scene authority
21. remove only frozen `DOOR_DETAIL` request recipe
22. remove only frozen `ASSEMBLED_FRONT` request recipe
23. leave final pack/worker/serialized copies mutually consistent while frozen authority is absent for one required field → still FAIL.

Keep existing helper-level negatives too; the key is that the above must hit the actual publication runner.

## 4. Blocker C — DAM provenance needs source/path lineage closure

Current worker-view validation checks row ↔ worker normalized path, DAM tenant/SHA/role/renderPackId and live DAM bytes. This is useful, but it still does not prove the DAM asset corresponds to the exact source view lineage when DAM stores/copied the same bytes at a different path. A wrong valid asset with copied bytes/metadata can be too hard to distinguish if only SHA and role are checked.

### Required correction

Use the existing DAM API / metadata model; do not create a second DAM authority.

For each required view:

1. Bind `row.artifactId` / `row.damRef` to the exact DAM asset created for that view.
2. Preserve and validate an existing-source lineage field or source-path identity when the DAM API copies bytes into storage. If an existing DAM field already carries origin/source path, use it; otherwise add minimal metadata at `dam.put()` for this artifact only, such as normalized source view path / source job identity, without creating a new system of record.
3. Validate the stored DAM path/bytes **and** source lineage against row/worker evidence and `blenderJobId`.
4. A same-byte valid DAM asset from the wrong view/job/source must fail even if SHA/size match.
5. Keep `DOOR_DETAIL` ↔ `door_detail.png` and `ASSEMBLED_FRONT` ↔ `assembled_front.png` role mapping exact.

### Required provenance negatives

Add fail-closed tests for:

- `damRef` changed to another valid asset;
- DAM asset/source-lineage changed to another valid path while SHA/size remain copied/equal;
- swap `DOOR_DETAIL` and `ASSEMBLED_FRONT` artifact identities;
- same SHA/size with wrong `viewId` / role / source job;
- copied bytes with wrong dimensions/role/view mapping;
- nested worker view and top-level worker view remain required to agree;
- wrong/swapped/missing `blenderJobId` remains FAIL.

Do not require naïve `DAM storage path == Blender output path` if DAM legitimately copies artifacts; bind via explicit source lineage instead.

## 5. Documentation / evidence sequence

After corrections:

1. Run full `pytest -q`; report exact count.
2. Commit **CODE + tests only**, push exact CODE SHA by itself.
3. Wait for exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS; record run ID and both job results.
4. On a clean working tree at that exact CODE SHA, run fresh REAL Blender 5.2.1 + NVIDIA T1000 OptiX acceptance with `usedMock=false`.
5. Verify ProductMask vs FRONT PrintableSurface ArtworkMask remain distinct; both required REAL views remain separately valid.
6. Update only necessary docs/evidence in a separate docs commit:
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md/.json`
   - Generative acceptance only if its evidence actually changes.
7. Leave `docs/CABINET_REAL_ACCEPTANCE.md` unchanged unless cabinet truth genuinely changes.
8. Push docs commit and verify docs/head Ubuntu + Windows SUCCESS.
9. Update Issue #1 with instruction SHA, CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation ID, and exact REAL/MOCK/BLOCKED boundary summary.
10. STOP for ChatGPT Re-Gate. **Do not start Phase 901+.**

## 6. Definition of Done for Round 5

All must be true:

- strict publication path has zero final-pack/worker fallback for missing required frozen authority;
- all 23 official-runner adversarial cases above fail closed;
- no rejected runner case publishes a false `ok=true` acceptance artifact;
- DAM artifact binding proves correct view/job/source lineage, not only equal bytes;
- wrong-valid-DAM, path/source swap and cross-view swap regressions fail;
- existing camera semantic validation and Round 4 accepted behavior stay green;
- full pytest passes;
- exact CODE SHA dual-platform CI succeeds;
- fresh clean-tree REAL T1000 OptiX evidence succeeds on exact CODE SHA;
- docs/head dual-platform CI succeeds;
- H3/LTX remain BLOCKED, Vision remains MOCK/BLOCKED, physical print remains false, LIVE_CNC/LASER remain BLOCKED, global/full/live readiness remain false;
- Phase 901+ remains HOLD until ChatGPT explicitly releases it.
