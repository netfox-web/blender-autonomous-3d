# Reusable product scene library V1 — acceptance

Explicit user request (2026-09-16): add living-room and kitchen scenes to the reusable product artwork/batch workflow. No new instruction-commit or source-Issue identity is invented. This is separate from Issue #6 Round 3B.

## Behavior

The model workbench now presents a scene library with a furnished living room (sofa, coffee table, wall art and lamp) and kitchen (base/upper cabinets, worktop and props). Operators choose a scene, automatic or explicit floor/surface placement, and right/front/left camera view. The existing batch UI retains these selections and allows the same SKU in different views while rejecting an exact duplicate.

Cabinets and mats use floor slots; coasters use the living-room table or kitchen worktop. Unsupported product families, mismatched slots and out-of-range dimensions fail before enqueueing. Products never shrink to fit. Every room configuration has an identity covering furniture, camera, lights and rigid placement; queued snapshots reject a changed template. Cache identity includes the room configuration.

The presentation scene uses linked copies of the canonical product mesh, materials and UV data. Flat products rotate as a whole with the print face upward. Canonical front renders, observed component dimensions/positions and product-only GLB export stay in canonical coordinates. The saved Blender file contains both scenes and opens in the furnished presentation scene.

## Exact CODE and REAL gates

- CODE: `0c4039fcea18ce15c0f7b414db5972b048ed1f05`
- CODE CI: https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35051142918 — Ubuntu and Windows jobs recorded in the JSON evidence, each 958 PASS. MOCK regression only.
- Clean exact-CODE acceptance ID: `595824b2-ee68-495a-b00a-1b3d39273ee6`.
- REAL Blender 5.2.1 LTS + OptiX, `usedMock=false`: eight outputs, two synthetic product masters (cabinet and flat coaster) x two rooms x two artwork/view variants (right and left).
- Every output validates artifact SHA/size, 800 x 800 finite nonuniform pixels, scene identity, exact component membership, linked geometry and rigid placement. Actual geometry artifacts remain identical within each master.
- All eight `.blend` files reopen with linked meshes/materials/UVs, the expected room/camera, product fully within frame and artwork face centers unobstructed by furniture. Product-only GLB validation excludes room meshes.
- Actual HTTP checks retain queue exclusion, non-latest history/downloads, service restart, changed geometry invalidation/restoration, artwork revocation and cross-tenant denial.
- Browser checks preserve the existing 21-master inventory (4 previews / 17 drafts), add both rooms at LEFT, reject duplicates, add FRONT selections, clear the four-row review list, and show no JavaScript console errors. These UI checks did not generate or modify user product records.
- MOCK regressions additionally exercise downward-face prevention, mat floor height, unsupported/oversized/wrong-slot input, template-version changes, altered scene hash, matrix, scale, mesh linkage, missing components and environment count. Front camera and mat floor cases are not claimed as separate REAL fixture renders.

## Delivery

[PR #16](https://github.com/netfox-web/blender-autonomous-3d/pull/16) is stacked on PR #15 (`codex/product-variant-batches`); no merge authorization is assumed. Exact DOCS SHA and its Ubuntu/Windows CI run are reported in Issue #1 after they pass, avoiding circular self-SHA claims.

Machine-readable evidence: [PRODUCT_SCENE_LIBRARY_ACCEPTANCE.json](PRODUCT_SCENE_LIBRARY_ACCEPTANCE.json). Operator guide: [PRODUCT_SCENE_LIBRARY_GUIDE.md](PRODUCT_SCENE_LIBRARY_GUIDE.md).

## Truth and boundaries

All fixture product geometry and room furniture are synthetic demonstration inputs. REAL rendering does not establish physical CAD, verified installation dimensions, print accuracy or Production Ready. No NAS originals or user master records were changed. The 17 incomplete product drafts, curved-product adapters, veneer texture library, AI scene generation, photo matching and custom scene upload/editor remain outside this delivery. These are two built-in procedural room templates, not a user-authored scene editor.

PR #13 was not modified; PR #14 authority must still be authorized and actually present on main before Issue #6 Round 3B. No authority copy/cherry-pick, door-open fallback work, live H3/LTX/Vision provider or CNC/UV machine operation occurred.
