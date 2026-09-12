# Development Agent 下一輪開發指令：Phase 841–900 Re-Gate Round 4 — Runner Authority / View Provenance Finalization

> Repo: `netfox-web/blender-autonomous-3d`  
> Legacy filename kept for watcher compatibility: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`  
> Reviewed CODE: `ab20c1e3754a3767640c2ce7dc646cfd85a3ae71`  
> Reviewed docs/head: `5c042e42b04b20cfd1ec0ba0512027c952eec718`  
> Acceptance generation: `cf9e5828-d65d-4858-bc2b-09926c5b5ca2`  
> CODE Actions: `34685704758` — Ubuntu + Windows SUCCESS  
> docs/head Actions: `34686700529` — Ubuntu + Windows SUCCESS  
> Reported full pytest: **618 passed**  
> Re-Gate result: **CHANGES REQUIRED — Phase 901+ HOLD.**

## 0. Scope / fixed rules

Correction-only. Do **not** rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / ArtworkPlacement / ManufacturingRelease / WorkOrder / MaterialLot / Backup/Restore. Do not create another mm/UV/Product Truth source of truth.

Fixed rule:

> **模型可替換，Product Truth 不可替換。**

Keep current truth boundaries unchanged unless new real evidence genuinely exists:

- Product Truth Blender execution: scoped **REAL / REAL_LOGIC**.
- Product/Artwork masks: scoped REAL artifacts; current `artwork_mask` means whole canonical FRONT PrintableSurface mask, not artwork-color coverage.
- Generative Gateway contract: **REAL_LOGIC**.
- live H3 MAX / LTX 2.5: **BLOCKED**.
- Vision: **MOCK/BLOCKED**.
- physical print: **BLOCKED / false**.
- LIVE_CNC / LIVE_LASER / liveFactory execution: **BLOCKED**.
- `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`.

Do not change status labels to make dashboards green. Mock/FIXTURE is not Production Ready.

## 1. Accepted from Round 3 — do not regress

The following are accepted:

1. `validate_product_truth_render_pack()` no longer treats serialized `pack.expectedIdentity` as automatic authority when an external authority is supplied.
2. `build_pack()` now passes an explicit expected identity into validation.
3. worker-view actual camera fields are strict typed and semantically re-hashed; bool-as-number, numeric strings, NaN and Inf have negative tests.
4. required REAL views `DOOR_DETAIL` and `ASSEMBLED_FRONT` are emitted separately.
5. ProductMask and FRONT PrintableSurface ArtworkMask remain distinct; current canonical evidence has different SHA/occupancy.
6. exact CODE SHA CI is now genuinely proven: `ab20c1e...`, run `34685704758`, Ubuntu + Windows SUCCESS.
7. fresh evidence generation `cf9e5828-d65d-4858-bc2b-09926c5b5ca2` is clean-tree bound to `ab20c1e...`, Blender 5.2.1 + NVIDIA T1000 OptiX, `usedMock=false`.
8. docs/head `5c042e...` run `34686700529` is Ubuntu + Windows SUCCESS.

Round 3 Blocker C is therefore closed.

## 2. Blocker A — canonical runner authority is still partly pack-derived

The official runner now revalidates before publishing, which is directionally correct, but its current re-derivation still passes values copied from the final pack back into `derive_canonical_expected_identity()`:

```text
engineering={"engineeringHash": pack.engineeringHash}
camera=pack.cameraRecipe
scene=pack.sceneRecipe
view_recipes=pack.views[*].cameraRecipe
```

This is still circular for those fields. A coordinated forged final pack can become the source used to rebuild its own supposed external authority.

Also, `derive_canonical_expected_identity()` still has permissive fallbacks such as canonical placement OR caller placement and DAM lookup OR placement-carried SHA. Those fallbacks are useful for non-strict helpers but are not sufficient for the official REAL publication gate.

### Required correction

Use the existing sources only; do not add a new system of record.

Create/use a **strict publication-authority path** with these properties:

1. Freeze the canonical/request authority **before worker output is accepted**.
2. Official publication/re-gate validation must receive that frozen authority separately from the final pack. `pack.expectedIdentity` may be an evidence copy only.
3. For official REAL publication, engineering identity must come from the existing authoritative engineering/CabinetSpec lineage or the pre-worker request context — never from `pack.engineeringHash`.
4. Artwork placement/surface/component/object/face/finalUv must be re-resolved from canonical ArtworkPlacement / PrintableSurface stores.
5. Artwork SHA must be re-resolved from the authoritative DAM/artwork record/bytes. No fallback to worker or final-pack SHA in strict mode.
6. SceneRecipe, main CameraRecipe, and both requested view CameraRecipes must come from the frozen request-side context created before execution, not from `pack.sceneRecipe`, `pack.cameraRecipe`, or `pack.views[*].cameraRecipe` during publication validation.
7. Missing authoritative engineering, placement, surface, DAM artwork, scene/camera/view request context must FAIL/BLOCK. No pack/worker fallback in strict publication mode.
8. If `derive_canonical_expected_identity()` is retained for both permissive fixture use and strict REAL use, add an explicit strict/fail-closed mode rather than silently changing fixture semantics.

### Required full-run negative matrix

These must exercise the **official acceptance runner/publication path**, not only call `validate_product_truth_render_pack()` directly.

Forge pack + worker + serialized `expectedIdentity` together and prove publication fails against frozen external authority for each of:

- `engineeringHash`
- `placementHash`
- `surfaceHash`
- `finalUvHash`
- `componentId`
- `objectName`
- `face`
- artwork DAM SHA / artworkHash
- main `cameraRecipeHash`
- `sceneRecipeHash`
- `DOOR_DETAIL` requested camera recipe/hash
- `ASSEMBLED_FRONT` requested camera recipe/hash

Also prove:

- delete canonical placement → FAIL/BLOCK;
- delete canonical PrintableSurface/required surface authority → FAIL/BLOCK;
- delete/replace canonical DAM artwork record/bytes → FAIL/BLOCK;
- remove frozen request camera/scene/view authority → FAIL/BLOCK;
- runner never publishes acceptance JSON with `ok=true` when only pack/worker/serialized copies agree.

The current helper-level coordinated-tamper test is useful but is **not enough** for this gate.

## 3. Blocker B — REAL worker-view artifact provenance binding is incomplete

Round 3 correctly re-hashes worker camera fields, but the validator still needs exact provenance binding for the complete view record.

Current remaining risks include:

- `row.workerView` can win over top-level `pack.workerViews[name]` without proving both copies agree when both are present;
- `damRef` is created but is not semantically validated against the view artifact/DAM asset;
- `blenderJobId` is required but not proven equal across pack view ↔ workerView ↔ pack/job identity;
- view path / artifact role binding needs explicit exact validation, not only live-file SHA/size validation.

### Required correction

For each required REAL view (`DOOR_DETAIL`, `ASSEMBLED_FRONT`):

1. Choose one canonical worker-view evidence object or require exact equality between nested `row.workerView` and top-level `pack.workerViews[name]` when both exist. Conflicting duplicates must FAIL.
2. Exact-verify `viewId` and expected output role/filename mapping (`DOOR_DETAIL` ↔ `door_detail.png`; `ASSEMBLED_FRONT` ↔ `assembled_front.png`) using the existing role contract.
3. Exact-verify width/height, SHA256, byte size and actual file bytes.
4. Exact-verify `blenderJobId` across workerView, row, and pack/job lineage. Wrong/swapped/missing job ID must FAIL REAL readiness.
5. Exact-verify DAM binding: `damRef`/asset ID must point to the same stored artifact metadata/bytes/path/tenant/role if that metadata is available in the existing DAM API. Do not create a second DAM authority.
6. Exact-verify normalized output path binding between worker evidence, row, and DAM artifact according to the existing path rules. Wrong path with copied SHA must FAIL.
7. Keep strict camera semantic re-hash from Round 3 and external requested-view comparison.
8. For REAL views keep exact booleans `usedMock=false`, `realBlender=true`, `realOptix=true`.

### Required negative regressions

- nested workerView differs from top-level workerViews copy → FAIL;
- wrong/swapped `blenderJobId` → FAIL;
- wrong `damRef` to another valid asset → FAIL;
- wrong path/DAM path with copied SHA/size → FAIL;
- swap `DOOR_DETAIL` and `ASSEMBLED_FRONT` artifact identity → FAIL;
- copied artifact SHA with wrong dimensions/role/viewId → FAIL;
- all existing camera field tamper negatives remain green.

## 4. Documentation blocker

`docs/CURRENT_IMPLEMENTATION_AUDIT.md` body contains newer Phase 841–900 information, but its header still starts from stale Round-0-era metadata (`4a88680` / `3268f65` / `191a150`). Round 3 explicitly required this cleanup and it remains incomplete.

After code/evidence passes:

- update `docs/GROK_PROGRESS_REPORT.md`;
- update the `docs/CURRENT_IMPLEMENTATION_AUDIT.md` header/current reviewed SHA metadata to this new round;
- update `docs/REAL_E2E_ACCEPTANCE.md`;
- regenerate `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md/.json`;
- update Generative Gateway acceptance only if its evidence changes;
- leave `docs/CABINET_REAL_ACCEPTANCE.md` unchanged unless cabinet engineering truth actually changes.

Do not claim physical print, live provider, LIVE_CNC/LASER, or global production readiness.

## 5. Required push/evidence sequence

Repeat the proven safe sequence:

1. implement correction-only code/tests;
2. run full `pytest -q`, report exact count;
3. commit CODE/tests only and push that exact CODE SHA by itself;
4. wait for exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS and record run ID;
5. run fresh clean-tree REAL Blender 5.2.1 + NVIDIA T1000 OptiX acceptance on that exact CODE SHA (`usedMock=false`);
6. verify ProductMask and FRONT PrintableSurfaceMask remain distinct/non-alias and both required REAL views exist;
7. update docs/evidence in a separate docs commit;
8. push docs commit and verify docs/head GitHub Actions Ubuntu + Windows SUCCESS;
9. update Issue #1 with exact CODE SHA, docs SHA, pytest count, both run IDs, generation ID and truth-boundary summary;
10. STOP and wait for ChatGPT Re-Gate. **Do not start Phase 901+.**

## 6. Definition of Done for Round 4

All must be true before requesting Re-Gate:

- official runner/publication gate uses independently frozen pre-worker engineering/artwork/DAM/scene/camera/view authority, not final-pack-derived authority;
- full-run coordinated tamper matrix fails closed for all identity + scene/camera/view cases listed above;
- missing canonical authority fails closed without pack/worker fallback;
- worker-view duplicate/provenance/DAM/path/job identity binding is exact and fail-closed;
- strict camera semantic validation from Round 3 remains intact;
- full pytest passes with exact count;
- exact CODE SHA CI Ubuntu + Windows SUCCESS;
- fresh clean-tree REAL T1000 OptiX evidence on exact CODE SHA;
- ProductMask / FRONT PrintableSurfaceMask distinct and valid;
- separate DOOR_DETAIL / ASSEMBLED_FRONT REAL artifacts valid;
- CURRENT_IMPLEMENTATION_AUDIT header is current;
- docs/head CI Ubuntu + Windows SUCCESS;
- truth boundaries remain honest;
- Phase 901+ remains HOLD until next ChatGPT Re-Gate.
