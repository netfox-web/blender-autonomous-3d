# Development Agent 下一輪開發指令：Phase 841–900 Re-Gate Round 3 — External Canonical Authority / Worker-View Verification / Exact CODE CI

> Repo: `netfox-web/blender-autonomous-3d`  
> Legacy filename kept for watcher compatibility: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`  
> Reviewed CODE: `635b316a08e527bd84059a837618c11230f461e2`  
> Reviewed docs/head: `fa5a459b06f556fa87b9e6ef8f74a1382af1c929`  
> Acceptance generation: `2dafd469-0380-4169-96a8-15a42dfbb136`  
> docs/head Actions: `34674276235` — Ubuntu + Windows SUCCESS  
> Re-Gate result: **CHANGES REQUIRED — Phase 901+ HOLD.**

## 0. Scope / fixed rules

Correction-only. Do **not** rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / ArtworkPlacement / ManufacturingRelease / WorkOrder / MaterialLot / Backup/Restore. Do not create a second mm/UV/Product Truth source of truth.

Fixed rule:

> **模型可替換，Product Truth 不可替換。**

H3 MAX / LTX 2.5 remain provider boundaries only. Without live provider/runtime request-response evidence they remain **BLOCKED**. Vision remains **MOCK/BLOCKED**. `physicalPrintValidated=false`, LIVE_CNC/LIVE_LASER BLOCKED, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`.

## 1. What is accepted from `635b316`

The new implementation is substantive and most of Round 2 is directionally correct:

- REAL worker recomputes `observed_final_uv_hash` from the mapping actually applied and fails closed against the request hash.
- ArtworkMask no longer aliases ProductMask and now renders an isolated canonical FRONT polygon using white emission on black background; whole-object fallback is removed.
- REAL worker emits separate `DOOR_DETAIL` / `ASSEMBLED_FRONT` artifacts with per-view `workerViews` records and artifact SHA/size.
- Fresh REAL evidence is bound to `evidenceCodeCommit=635b316...`, `workingTreeClean=true`, Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`.
- Canonical evidence has distinct ProductMask / ArtworkMask SHA and occupancy; live H3/LTX remain BLOCKED, Vision remains MOCK, physical print remains false.
- Reported local test count is `615 passed`; this is MOCK/unit/integration + FIXTURE/REAL_LOGIC evidence only, not Production Ready.

Do not undo these fixes.

## 2. Blocker A — official REAL acceptance still trusts a serialized `pack.expectedIdentity`

`validate_product_truth_render_pack()` currently chooses authority using behavior equivalent to:

```text
expected_identity argument OR pack.expectedIdentity
```

`build_pack()` then calls the validator without an external `expected_identity`, and the official runner consumes the scenario's `pack.ok` / `acceptanceFailures` without independently reloading/recomputing canonical authority.

That means the new unit test proves coordinated tamper only when the test manually supplies a saved external `expected_auth`; it does **not** prove the official REAL acceptance path is independent. A coordinated mutation of:

```text
pack canonical identity
+ workerEvidence
+ pack.expectedIdentity
```

can turn the serialized pack into its own oracle.

### Required correction

Use the existing canonical sources only — no new SoT:

- Engineering/CabinetSpec authoritative engineering hash;
- canonical ArtworkPlacement record;
- canonical PrintableSurface record;
- DAM artwork bytes SHA256;
- canonical placement/surface/component/object/face/final UV identity;
- request-side CameraRecipe / SceneRecipe;
- request-side per-view CameraRecipe records.

Derive/freeze the expected authority **before worker output is accepted**. The official REAL path must validate:

```text
independent canonical/request/DAM authority
        vs
worker-observed evidence + serialized pack evidence
```

Requirements:

1. `build_pack()` must receive/use an external canonical expected identity for the official path; do not let `pack.expectedIdentity` become authority merely because it is serialized in the pack.
2. `pack.expectedIdentity` may remain as an evidence copy, but the official validator/runner must compare it against independently derived authority.
3. The canonical runner must revalidate the final pack against independent authority before `ok=true` / publication. Do not merely trust `pack.ok` produced earlier.
4. Re-resolve DAM artwork bytes and exact placement/surface identity from existing platform stores or the request-side canonical context. Do not read these values back from worker evidence.
5. Missing canonical authority must FAIL/BLOCK, never fall back to worker/pack values.

### Required negative matrix

Add formal full-acceptance-path regressions, not helper-only tests:

- forge `pack.engineeringHash` + `workerEvidence.engineeringHash` + `pack.expectedIdentity.engineeringHash` together → FAIL against canonical engineering authority;
- same coordinated forge for `placementHash`, `surfaceHash`, `finalUvHash`, `componentId`, `objectName`, `face`, artwork DAM SHA → FAIL;
- delete the independent canonical placement/surface/DAM record → FAIL/BLOCK rather than falling back to serialized pack evidence;
- prove the canonical runner refuses publication when the only matching values are pack/worker/serialized `expectedIdentity`.

## 3. Blocker B — worker-view camera record is not semantically re-hashed by the validator

The REAL worker now computes a per-view camera hash, which is good. But the validator currently mostly checks:

```text
workerView.cameraRecipeHash == view.cameraRecipeHash
```

and separately recomputes the serialized requested `view.cameraRecipe` hash. It does **not** recompute a hash from the actual fields inside `workerView` itself before trusting the supplied worker hash.

Therefore a post-run tamper such as changing only:

- `workerView.location`,
- `workerView.lookAt/target`,
- `focalLengthMm`,
- `sensorWidthMm`,
- `safeMargin`,
- `width` / `height`

while leaving `workerView.cameraRecipeHash` unchanged can evade the current semantic check.

Also, a coordinated mutation of workerView + its hash + serialized view row + serialized camera recipe must still fail against the independent request-side view recipe.

### Required correction

For every required REAL view (`DOOR_DETAIL`, `ASSEMBLED_FRONT`):

1. Strictly validate observed worker fields and numeric types (no bool-as-number, string-number, NaN, ±Inf).
2. Recompute `observedWorkerCameraRecipeHash` from the **workerView actual fields**.
3. Exact-compare recomputed observed hash to `workerView.cameraRecipeHash`.
4. Exact-compare observed fields/hash to the independent request-side CameraRecipe, not merely to a serialized copy inside the pack.
5. Exact-verify `viewId`, filename/output role, width/height, artifact SHA, byte size, DAM ref/path binding, Blender job ID.
6. For a REAL view require exact booleans: `usedMock=false`, `realBlender=true`, `realOptix=true`.
7. Missing or malformed workerView evidence must fail REAL readiness.

### Required negative matrix

- mutate workerView location only, keep hash unchanged → FAIL;
- mutate lookAt/target only → FAIL;
- mutate focalLengthMm only → FAIL;
- mutate sensorWidthMm / safeMargin / width / height only → FAIL;
- coordinated mutate workerView fields + worker hash + serialized view hash + serialized `cameraRecipe` → FAIL against independent request-side recipe;
- wrong viewId / swapped `DOOR_DETAIL` and `ASSEMBLED_FRONT` → FAIL;
- wrong artifact SHA/size/dimensions/DAM binding → FAIL;
- string/bool/NaN/±Inf camera fields → FAIL;
- REAL worker view with `usedMock=true`, `realBlender=false`, or `realOptix=false` → FAIL.

## 4. Blocker C — exact CODE SHA GitHub Actions evidence is missing

The progress report and Issue completion comment claim exact CODE dual-platform CI GREEN for `635b316...`, but GitHub Actions currently returns **zero workflow runs** for that exact SHA.

The only verified current Actions run is docs/head `fa5a459...`:

- run `34674276235`
- `unit (ubuntu-latest)` SUCCESS
- `unit (windows-latest)` SUCCESS

This does not satisfy the Round 2 Definition of Done that explicitly required an **exact CODE SHA** dual-platform run.

### Required correction / push sequence

For the next code correction:

1. commit CODE/tests only → record exact `CODE_EVIDENCE_SHA`;
2. **push that CODE commit by itself**;
3. wait until GitHub Actions for that exact SHA completes SUCCESS on Ubuntu + Windows;
4. only then run fresh clean-tree REAL Blender acceptance on that exact CODE SHA;
5. then update docs/evidence in a separate docs commit;
6. push docs commit and verify docs/head Ubuntu + Windows SUCCESS;
7. report both run IDs explicitly.

Do not claim CODE CI green before an exact-head run actually exists.

## 5. Documentation cleanup required

After the correction is genuinely proven:

- update `docs/GROK_PROGRESS_REPORT.md` (legacy name may remain for watcher compatibility);
- update `docs/CURRENT_IMPLEMENTATION_AUDIT.md` header so it no longer starts from stale `4a88680` / prior instruction metadata;
- update `docs/REAL_E2E_ACCEPTANCE.md`;
- regenerate `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md/.json`;
- update `docs/GENERATIVE_RENDER_GATEWAY_ACCEPTANCE.md/.json` only if evidence changes;
- leave `docs/CABINET_REAL_ACCEPTANCE.md` unchanged unless cabinet engineering truth actually changes;
- correct the prior completion-report docs SHA typo in the next Issue #1 handoff by reporting the exact full Git SHA returned by GitHub.

The semantic contract for current `artwork_mask` must remain explicitly documented as the **whole canonical FRONT PrintableSurface mask**, not artwork-color/appearance coverage. If a future ArtworkCoverageMask is needed, add a distinct role rather than silently changing this role's meaning.

## 6. REAL / MOCK / PARTIAL / BLOCKED status for this Re-Gate

| Item | Status |
|---|---|
| Worker UV independent recompute | ACCEPTED REAL_LOGIC |
| FRONT printable-surface mask implementation | REAL_LOGIC + fresh REAL artifact evidence, accepted for current scoped direction |
| Per-view worker emission | REAL_LOGIC + REAL artifacts, but validator semantic binding still PARTIAL |
| Canonical expected authority in official acceptance | **PARTIAL / BLOCKER** |
| Exact CODE SHA Actions | **MISSING / BLOCKER** |
| docs/head Actions `34674276235` | GREEN Ubuntu + Windows |
| Product Truth REAL evidence | REAL for current artifact execution, but Phase 841–900 gate remains not fully accepted until blockers close |
| Generative Gateway contract | REAL_LOGIC |
| live H3 MAX / LTX 2.5 | BLOCKED |
| Vision Judge | MOCK/BLOCKED |
| physical print | BLOCKED / false |
| LIVE_CNC / LIVE_LASER | BLOCKED |
| global/full/live production readiness | false |

Do not change labels just to make dashboards green.

## 7. Definition of Done for Round 3

Before asking for Re-Gate again, all must be true:

1. external canonical authority is used by the official REAL path and canonical runner;
2. coordinated tamper including serialized `expectedIdentity` fails;
3. workerView actual camera fields are strictly re-hashed/revalidated against independent requested view recipes;
4. all new negative regressions pass;
5. all Round 8–12 Artwork Placement and prior Phase 841–900 regressions remain green;
6. full `pytest -q` exact count reported;
7. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS, with run ID;
8. fresh clean-tree REAL Blender 5.2.1 + NVIDIA T1000 OptiX acceptance, `usedMock=false`, exact CODE SHA, fresh generation ID;
9. ProductMask and FRONT PrintableSurfaceMask remain distinct, non-alias, fail-closed;
10. separate `DOOR_DETAIL` and `ASSEMBLED_FRONT` REAL artifacts + independently verified worker camera records;
11. docs/evidence updated in a separate commit;
12. docs/head GitHub Actions Ubuntu + Windows SUCCESS, with run ID;
13. Issue #1 handoff lists exact CODE SHA, docs SHA, pytest count, both CI run IDs, generation ID, REAL/MOCK/PARTIAL/BLOCKED truth table summary;
14. stop and wait for ChatGPT Re-Gate. **Do not start Phase 901+.**
