# Grok 下一輪開發指令：Phase 841–900 Re-Gate Round 2 — Canonical Worker Authority / True Printable FRONT Mask

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `c2ea14196f3e0ffffcd4345f253874c341a2f563`  
> New correction commits reviewed: `094d641`, `c43ebb`, `c2ea141`  
> CODE Actions: `34615013005` on exact `c2ea141` — Ubuntu + Windows SUCCESS  
> Re-Gate result: **CHANGES REQUIRED — Phase 901+ HOLD.**

## 0. Scope

Correction-only. Do **not** rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / ArtworkPlacement / ManufacturingRelease / WorkOrder / MaterialLot / Backup/Restore, and do not create a second renderer or a second mm/UV/Product Truth source of truth.

Fixed rule:

> **模型可替換，Product Truth 不可替換。**

H3 MAX / LTX 2.5 remain provider boundaries only. Without live provider/runtime request-response evidence they remain **BLOCKED**. Vision remains **MOCK/BLOCKED**. `physicalPrintValidated=false`, LIVE_CNC/LIVE_LASER BLOCKED, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`.

## 1. What this round already improved

The new code is substantive and directionally correct:

- removed the old silent `artwork_mask = product_mask` alias;
- added worker identity fields;
- added strict bool checks for REAL readiness;
- added `DOOR_DETAIL` and `ASSEMBLED_FRONT` output paths;
- added negative tests around mask alias, worker identity and required views;
- exact head `c2ea141` GitHub Actions `34615013005` is GREEN on Ubuntu + Windows.

However, the current implementation still has authority loops/fail-open behavior. Do not publish new REAL acceptance until the following are corrected and fresh REAL evidence exists.

## 2. Blocker A — `build_pack()` currently lets worker evidence define the canonical expected identity

Current pattern is effectively:

```text
pack.engineeringHash = worker.engineeringHash OR canonical engineering
pack.artworkHash = worker.artworkHash OR canonical placement
pack.placementHash = worker.placementHash OR canonical placement
pack.finalUvHash = worker.finalUvHash OR canonical placement
...
validator: worker == pack
```

This is circular. A wrong/forged worker can report a coordinated wrong identity, `build_pack()` copies it into the pack, and the validator can then compare the worker against its own values and pass.

### Required correction

Create an **independent authoritative expected identity** from the already-existing request-side truth only:

- Engineering/CabinetSpec authoritative `engineeringHash`;
- canonical `ArtworkPlacement` record;
- canonical `PrintableSurface` record;
- DAM artwork bytes SHA256;
- canonical `placementId`, `placementHash`, `finalUvHash`, `surfaceHash`;
- canonical `componentId`, `objectName`, `face=FRONT`;
- request-side CameraRecipe / SceneRecipe hashes.

The pack canonical fields must come from that authority, **never from `workerEvidence`**. Worker evidence is observed evidence only.

Validator must exact-compare:

```text
expectedIdentity (independent canonical authority)
        vs
workerEvidence (observed Blender execution)
```

No `worker.get(...) or canonical...` when building the expected side.

### Required negative

A coordinated tamper that changes BOTH `workerEvidence` and the pack's serialized identity fields must still FAIL because the validator independently recomputes/loads the expected authority from canonical request/placement/DAM truth.

## 3. Blocker B — `finalUvHash` is currently trusted from serialized input inside the REAL worker path

Current `apply_canonical_artwork()` uses behavior equivalent to:

```python
item.get("finalUvHash") or compute_final_uv_hash(item, mapping)
```

That makes a serialized hash capable of becoming the worker's observed evidence without proving that the actual Blender mapping produced it.

### Required correction

- Always compute `observedFinalUvHash = compute_final_uv_hash(actual item, actual mapping)` from the mapping actually applied by Blender.
- If request payload contains an expected `finalUvHash`, exact-compare it to the recomputed observed hash.
- On mismatch: fail closed; do not render/accept as REAL Product Truth evidence.
- Worker evidence must return the **recomputed observed hash**, not echo the serialized request value.

### Required negative

Tamper only the serialized/request `finalUvHash` while leaving actual mapping unchanged → REAL worker/acceptance must FAIL.

## 4. Blocker C — current `c2ea141` ArtworkMask is a placed-object appearance render, not a canonical printable FRONT-surface mask

`c43ebb` attempted a FRONT-face emission proxy, but `c2ea141` replaced it with logic that hides non-placed objects and renders the remaining placed object(s) on a black world using their normal materials.

That is not sufficient Product Truth authority:

- it can include side/back geometry visible from the camera;
- it depends on material/lighting/texture brightness rather than pure printable-surface occupancy;
- it does not prove the pixels represent exactly the canonical `face=FRONT` printable surface / artwork region;
- merely being a strict subset of ProductMask is not enough.

### Required correction

Generate ArtworkMask from the canonical printable surface geometry, not from object appearance.

Acceptable minimal implementation inside the existing Blender worker:

1. resolve the canonical placement -> exact `componentId/objectName`;
2. resolve **exact FRONT printable face/polygon set** from existing engineering/PrintableSurface authority;
3. if the FRONT face/polygon mapping cannot be resolved, **FAIL/BLOCK**, never fall back to whole object;
4. render only that printable surface using a deterministic white emission / ID mask / cryptomatte-equivalent path on black/transparent background;
5. no original material/texture/lighting may determine whether a mask pixel is on/off;
6. mask evidence must include exact source identity: `componentId`, `objectName`, `face`, `surfaceHash`, `placementHash`, `finalUvHash`;
7. for canonical case, `artwork_mask` must be semantically the printable FRONT region, not simply “the selected door object”.

If the artwork only covers a sub-region of the printable surface, choose and document one contract consistently:

- `PrintableSurfaceMask` = whole allowed FRONT printable surface, or
- `ArtworkCoverageMask` = final UV artwork coverage within that surface.

Do not mix the two meanings under the same role. If keeping role `artwork_mask`, document which one it is and validate accordingly.

### Required negatives

- missing/unresolvable FRONT face mapping → FAIL, no whole-object fallback;
- wrong component/object → FAIL;
- BACK/SIDE face → FAIL;
- whole placed-object occupancy masquerading as ArtworkMask → FAIL;
- ProductMask copied to ArtworkMask → FAIL;
- dark/black artwork/material must not make a valid printable surface disappear from the mask.

## 5. Blocker D — view camera identity is still post-hoc labeled by the orchestrator

`DOOR_DETAIL_cameraRecipeHash` and `ASSEMBLED_FRONT_cameraRecipeHash` are currently attached in `render_product_truth()` after outputs are resolved. That does not independently prove the Blender worker actually rendered each artifact with that requested camera recipe.

### Required correction

REAL Blender worker result must return a per-view observed record for at least:

```text
viewId
filename/output key
cameraRecipeHash (computed/confirmed by worker)
actual location
actual lookAt/target
actual focalLengthMm
width / height
artifact path or output id
Blender job id
usedMock
realBlender
realOptix
```

The validator must compare each observed view record against the independent requested CameraRecipe and artifact bytes.

The two views may share one Blender job ID if rendered in one job, but they must have **separate view records and separate artifacts**.

Do not let the pack builder invent the worker-observed camera hash after rendering.

### Required negatives

- worker renders DOOR_DETAIL using ASSEMBLED_FRONT camera but pack labels it DOOR_DETAIL → FAIL;
- post-hoc serialized camera hash changed together with pack metadata → FAIL against independent requested recipe;
- missing worker view record for either required view → FAIL;
- missing/wrong artifact SHA/size/dimensions → FAIL.

## 6. REAL / MOCK / PARTIAL truth boundary for this Re-Gate

Until fresh evidence proves the corrected path:

| Item | Status |
|---|---|
| Product Truth render/gateway code | REAL_LOGIC / PARTIAL |
| exact `c2ea141` CI | GREEN MOCK/unit/integration evidence |
| ArtworkMask printable-surface authority | PARTIAL — not accepted yet |
| Worker identity authority | PARTIAL — circular expected/observed binding remains |
| DOOR_DETAIL + ASSEMBLED_FRONT implementation | PARTIAL — worker camera identity not independently bound |
| prior REAL Blender preview evidence | REAL for its prior accepted scope only |
| new corrected Phase 841–900 REAL acceptance | **NOT YET ACCEPTED** |
| Generative Gateway contract | REAL_LOGIC |
| live H3 MAX / LTX 2.5 | BLOCKED |
| Vision Judge | MOCK/BLOCKED |
| physical print | BLOCKED / false |
| LIVE_CNC / LIVE_LASER | BLOCKED |
| global/full production readiness | false |

Do not change these labels merely to make the dashboard green.

## 7. Tests / negative matrix required before new evidence

Keep all existing tests and add direct formal acceptance-path regressions for at least:

1. coordinated forged worker + forged serialized pack identity → FAIL against independent canonical expected identity;
2. wrong worker `engineeringHash` → FAIL;
3. wrong artwork DAM bytes/SHA → FAIL;
4. wrong `placementHash` / `surfaceHash` / `componentId` / `objectName` / `face` → FAIL;
5. serialized `finalUvHash` tampered but actual mapping unchanged → FAIL;
6. worker observed finalUvHash differs from canonical expected → FAIL;
7. ArtworkMask whole-object fallback → FAIL;
8. ArtworkMask wrong/non-FRONT face → FAIL;
9. ProductMask alias → FAIL;
10. dark/black source artwork still yields correct geometry mask behavior;
11. wrong per-view camera parameters/hash → FAIL;
12. missing `DOOR_DETAIL` worker view evidence → FAIL;
13. missing `ASSEMBLED_FRONT` worker view evidence → FAIL;
14. strict bool schema for `usedMock`, `realBlender`, `realOptix` retained;
15. all Round 8–12 Artwork Placement tamper tests retained without regression.

`pytest` / CI remain test evidence only, not Production Ready evidence.

## 8. Fresh REAL evidence / Definition of Done

After code is corrected:

1. produce a new exact `CODE_EVIDENCE_SHA`;
2. run full `pytest -q` and report exact count;
3. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS;
4. run canonical acceptance on a **clean tree**, no official `--allow-dirty`;
5. REAL Blender 5.2.1 + NVIDIA T1000 OptiX evidence with `usedMock=false`, `realBlender=true`, `realOptix=true` exact bools;
6. independent expected identity vs worker observed identity all exact-match;
7. true printable FRONT ArtworkMask with distinct artifact SHA/size/dimensions and semantic proof;
8. REAL `DOOR_DETAIL` and `ASSEMBLED_FRONT`, each with worker-observed camera record + artifact SHA/size/dims/DAM ref;
9. fresh `acceptanceGenerationId`, `evidenceCodeCommit=<exact CODE SHA>`, `workingTreeClean=true`;
10. update at least:
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md/.json`
   - `docs/GENERATIVE_RENDER_GATEWAY_ACCEPTANCE.md/.json` only if its evidence changed
   - `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet engineering truth actually changed;
11. push docs/evidence commit and require docs/head Actions Ubuntu + Windows SUCCESS;
12. Issue #1 completion comment: CODE SHA, pytest count, CODE Actions, generation, REAL worker identity comparison, true mask proof, two view records, provider truth labels, docs SHA/docs Actions.

Then stop and wait for ChatGPT Re-Gate. **Do not start Phase 901+.**
