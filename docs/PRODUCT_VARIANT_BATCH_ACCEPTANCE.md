# Product variant batches — Round 2 durable identity acceptance

Supervisor instruction: `29f45051cb7fc2153dca695f628bb854fc307394`, Issue #1 comment 5691577003. Correction instruction `64e9d12380b5c4d2329f383d1fd481656075239e` / comment 5692029044 also applies. This additive hardening is on existing PR #15, based on unmerged PR #12. It does not merge either PR or extend the scene-library scope.

## Behavior and identity

A batch's mutable progress can no longer prove completion. `identityVersion=1` binds tenant, master ID, batch/task ID, source revision, master input hash, immutable request hash, exact row count/order and each SKU/scene/selection identity. Generation UUIDs are derived deterministically from the batch UUID, row index and exact selection hash.

The existing serial service persists only an additive batch-version marker beside its existing task/input hash. A separate exclusive-write request snapshot anchors recomputation; write-once row and batch terminal receipts prevent mutable cancelled/interrupted progress from resurrecting success. Existing atomic JSON persistence is reused; no second scheduler, queue, DAM or rendering engine is introduced. Exclusive publication uses a fully written temporary file and an atomic no-overwrite hard link.

`current()` checks the outer service task/input identity, independently reconstructs all expected rows from the request, and rejects corrupted, incomplete, swapped, reordered or unknown-version records. For each completed row it reuses `compositions.generation()` and the existing artifact/publication verifier, then binds the exact manifest draft, revision, plan hash and scene to the requested row. Missing, corrupt, stale or revoked results become unavailable/failed. API status cannot keep an outer stale succeeded label; the UI clears old batch progress when verification errors occur.

Completed valid results survive restart. Unfinished rows never replay automatically. A cancelled/interrupted outer task is not promoted to a successful batch merely because completion files exist. Older batches without the new identity records require rechecking; their independently valid historical compositions still use the existing download path. Single-composition flow and category/inventory semantics remain intact.

## Historical Round 1

Round 1 CODE `2a43d9b51001176164bd534f51b63debf3f391cd` produced six REAL synthetic static renders under acceptance `34fbd5bf-a46d-4914-8d08-cf86e36b83bb`. Its evidence remains available in [the immutable Round 1 report](https://github.com/netfox-web/blender-autonomous-3d/blob/f88d5c896be424da54ab379cdd97a9dc35d08f90/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json). Those six renders prove only that earlier static slice; they do not substitute for this Round 2 durable-lineage acceptance. The two renders and REAL_LOGIC corruption/restart checks below are new exact-CODE Round 2 evidence.

## Exact-CODE regression correction

The first CODE `155fd2b602ea6d9c0519a28d28150e5d2a43b275` was reproduced in a clean detached checkout using the added API regression: **2 FAIL / 1 PASS** (MOCK/API logic). Null or malformed persisted outer task IDs returned HTTP 200 before batch validation. A minimal two-line non-idle task-ID guard corrects this; three API regression cases now pass. This was reported in Issue #1 comment 5692136979. The first CI attempt was cancelled while investigating this real gap; its cancellation is not counted as PASS. The later exact CODE below supersedes it under the correction instruction’s actual pytest-failure path.

## Gates

- Exact CODE: `bedc9a08bcdec19076ea70d0000a2a2a272e15db`.
- Exact CODE CI: https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35057461216; Ubuntu + Windows SUCCESS, each **980** pass markers. **MOCK regression only**.
- Local full pytest: 980 pass markers; focused batch/composition/category checks: 76 passed.
- Clean exact-CODE REAL acceptance: `8305eb4c-8bd6-4112-a248-4219d8d92aac`.
- Two synthetic static cabinet artwork variants, REAL Blender 5.2.1 LTS + OptiX, `usedMock=false`. Both validate actual artifact SHA/bytes, publication seal, batch identity/receipts, `.blend` reopen and finite nonuniform 800 × 800 images. Geometry identity remains fixed, beauty hashes differ.
- Actual server restart retains completed batch/results and historical non-latest downloads; changed geometry and revoked artwork disable availability/downloads. Queue exclusion and cross-tenant path isolation remain checked.
- Representative REAL_LOGIC tamper matrix: 30 recorded outcomes, all expected blocks/pass restoration. Batch/task, tenant/master, hash/revision/version, count/order, duplicate/malformed UUID, SKU/scene, truncated JSON, manifest/publication corruption and terminal-state resurrection checks are included. Request/service-input contradiction and succeeded-without-receipt also block in REAL_LOGIC corruption trials; additional adversarial cases are covered in MOCK regressions.
- The interrupted-row scenario is explicitly **SIMULATED_INTERRUPTION_REAL_ARTIFACTS**: persisted progress and receipts are manipulated in the isolated acceptance fixture; this does not claim a real killed Blender process. A stray existing publication cannot mark the interrupted batch row successful.

Full machine-readable evidence: [PRODUCT_VARIANT_BATCH_ACCEPTANCE.json](PRODUCT_VARIANT_BATCH_ACCEPTANCE.json). Operator guide: [PRODUCT_VARIANT_BATCH_GUIDE.md](PRODUCT_VARIANT_BATCH_GUIDE.md).

DOCS is committed after CODE CI and clean REAL PASS. Exact DOCS SHA and its dual-platform CI are recorded in the Issue #1 handoff after they pass, avoiding circular self-SHA claims.

## Truth and scope

`inputTruth=SYNTHETIC_STATIC_FIXTURE`, `physicalPrintValidated=false`, `physicalProductGeometryTruth=false`, `globalProductionReady=false`, `MERGE_AUTHORIZED=false`.

This is local durable lineage validation, not cryptographic protection against an administrator who rewrites all local anchors or production authentication certification. Existing inventory remains 21 masters / 4 previews / 17 drafts. No NAS originals or operator product records were used as tamper fixtures or changed. Missing dimensions/dielines, veneer material management and curved/rotating product adapters remain outstanding.

PR #16 was created under the explicit scene request before this instruction was observed and is now frozen as a draft; it is not part of this Round 2 acceptance. No scene changes were copied into PR #15. PR #13/#14 were not changed. Issue #6 stays `BLOCKED_PR14_NOT_ON_MAIN`; no authority cherry-pick, door-open render, legacy 75-degree substitution, live H3/LTX/Vision or machine control occurred. No merge is authorized. Stop for Supervisor Re-Gate.
