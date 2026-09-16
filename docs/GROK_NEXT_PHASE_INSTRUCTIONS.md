# Development Agent 修正指令：PR #15 Round 3 Re-Gate — Serialized Identity Exactness Closure

> Supervisor checkpoint: 2026-09-16
> Current main before this instruction: `782d0bd884473f151e7ed8de909015c08f1a712f`
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR #15 base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Reviewed CODE: `d684686f076fb91c1d9a87ca996a9bd917f1a735`
> Reviewed DOCS / PR head: `91111ed57039df2d537a717b8897d1be82b80625`
> Decision: **CHANGES REQUIRED / FAIL-CLOSED TYPE CLOSURE**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Re-Gate result

Round 3 evidence closure itself is substantially complete:

- CODE `d684686f076fb91c1d9a87ca996a9bd917f1a735` / Actions `35071688400`: Ubuntu + Windows SUCCESS;
- DOCS `91111ed57039df2d537a717b8897d1be82b80625` / Actions `35073905451`: Ubuntu + Windows SUCCESS;
- CI remains **MOCK regression only** (`FOX3D_MOCK_BLENDER=1`);
- clean REAL acceptance `113ade57-fbe8-46c4-8af5-895de4e65d3d`: Blender 5.2.1 LTS + OptiX, `usedMock=false`, two synthetic variants, reopen/restart/publication checks, 30 durable-lineage outcomes and 21 authority outcomes;
- authority source hashing / strict declaration-control integer validation added in `d684686...` correctly closes the Python `True == 1` problem for the authority files it covers.

However, static review found the **same numeric-type coercion class still exists at adjacent persisted batch/publication boundaries**. Because Round 3 promises exact request/row/publication/authority binding and fail-closed tamper handling, this must be closed before ACCEPT.

Do not broaden feature scope. Do not open a new PR. Do not rewrite queue, renderer, DAM, Product Master, publication, or authority architecture.

---

## 1. Reproduce the residual fail-open cases first

On clean exact CODE `d684686f076fb91c1d9a87ca996a9bd917f1a735`, add focused regressions that prove the current behavior before fixing it.

At minimum cover these serialized JSON type substitutions:

1. immutable `request.json.identityVersion: 1 -> true`;
2. immutable `request.json.sourceRevision: 1 -> true`;
3. queue/service `state.json.batchVersion: 1 -> true`;
4. published manifest `historyVersion: 1 -> true`, with publication seal recomputed;
5. published manifest `sourceRevision: 1 -> true`, with publication seal recomputed;
6. terminal row receipt `row.index: 0/1 -> false/true` where Python dict equality could otherwise treat it as equal.

Also test any directly adjacent serialized integer/version/revision field touched by the minimal fix if it is validated with plain Python numeric equality.

The test is successful only if the pre-fix exact CODE demonstrates at least one real fail-open in this class. Record the reproduction in Issue #1. Do not claim a fabricated failure if the current code already blocks a case.

Why this matters:

- `True == 1` in Python;
- `_identity()` currently uses plain equality for request identity/version/revision fields;
- service `batchVersion` uses plain equality;
- `_published()` uses plain equality for manifest version/revision;
- row receipt verification compares a persisted row dict directly with the expected row.

A changed JSON type is still changed serialized evidence. It must not be accepted as the exact original identity merely because Python considers the numeric values equal.

---

## 2. Minimal correction only

Implement one consistent fail-closed rule for persisted integer/version/revision/index values used as identity evidence:

- exact integer type required: `type(value) is int` (or an existing strict schema that has equivalent behavior);
- booleans must never satisfy an integer/version/revision/index gate;
- do not coerce strings/floats/bools into integers;
- where persisted structured identity is compared, prefer canonical hash / strict schema validation over Python dict equality if that removes this class of ambiguity;
- preserve all accepted Round 2/3 semantics and file formats where possible.

Required boundaries:

### 2.1 Immutable request

Fail closed when `identityVersion` or `sourceRevision` is not an exact integer of the expected value. If `batchVersion`, `masterRevision`, or another identity-bearing integer from the request draft reaches `_identity()`, ensure its type is exact too.

### 2.2 Queue/service state

`batchVersion` must be exact integer `1`; `true` must not pass. Do not weaken existing task/input-hash/state checks.

### 2.3 Publication manifest

`historyVersion` and `sourceRevision` must be exact integers of the expected values. Recomputing the ordinary publication seal after changing `1` to `true` must **not** make the generation valid.

Do not replace the existing canonical publication verifier; harden the existing path.

### 2.4 Terminal row receipts

The persisted receipt row must be semantically and serially exact. A boolean substituted for `index` must fail even though Python numeric equality would otherwise accept it. Keep existing batch identity hash and receipt lifecycle behavior.

---

## 3. Regression matrix

Add focused tests for both direct verifier and API/current-state behavior where applicable.

Minimum PASS expectations after the fix:

- request identityVersion bool tamper -> BLOCK;
- request sourceRevision bool tamper -> BLOCK;
- service batchVersion bool tamper -> BLOCK;
- manifest historyVersion bool tamper + recomputed publication seal -> BLOCK;
- manifest sourceRevision bool tamper + recomputed publication seal -> BLOCK;
- receipt row index bool tamper -> BLOCK;
- restored exact integer values -> valid again;
- existing 1010 tests remain green;
- existing 30 durable-lineage outcomes remain green;
- existing 21 authority outcomes remain green;
- authority `MEASURED_OR_CAD_AUTHORITY` remains rejected without reviewed provider;
- physical/manufacturing/print readiness flags remain false for fixture/reference inputs.

Do not add unrelated UI, scene, room, provider, articulation, CNC, print or manufacturing features.

---

## 4. Exact CODE gate

After the minimal fix:

1. freeze a new CODE SHA on existing PR #15;
2. run exact CODE GitHub Actions;
3. Ubuntu SUCCESS;
4. Windows SUCCESS;
5. verify actual checkout SHA equals the new CODE SHA;
6. report total and focused test counts.

GitHub Actions remains MOCK/unit/regression evidence only.

If CI fails, fix only that failure and repeat with a new exact CODE SHA.

---

## 5. Clean REAL correction acceptance

After exact CODE dual-platform SUCCESS, rerun the existing Round 3 acceptance path from a clean tree against the **new exact CODE**. Reuse `scripts/run_model_batches_e2e.py --round3`; do not create another acceptance architecture.

Required evidence:

- Blender 5.2.1 LTS;
- OptiX / `realOptix=true`;
- `usedMock=false`;
- at least two synthetic/reference visual variants;
- artifact SHA/bytes, finite nonuniform images and `.blend` reopen;
- restart/history/download checks;
- all prior durable-lineage and authority outcomes;
- new serialized-type tamper outcomes listed above, including manifest cases with recomputed ordinary publication seal;
- restored exact data becomes valid only when all existing authority/publication conditions are satisfied.

Truth classification remains:

- render execution: **REAL_RENDER**;
- authority/batch/publication verification: **REAL_LOGIC**;
- fixture geometry/input: **SYNTHETIC / REFERENCE**;
- CI: **MOCK regression**;
- physical geometry truth: **BLOCKED / false**;
- physical print: **BLOCKED / false**;
- manufacturing readiness: **BLOCKED / false**;
- global Production Ready: **false**.

---

## 6. DOCS closure

Only after the new CODE CI and clean REAL correction acceptance PASS:

- update the existing `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md` and `.json` with the new exact CODE/evidence and the numeric-type closure outcomes;
- do not rewrite unrelated historical audit documents merely to make them look current;
- commit DOCS after REAL evidence;
- run exact DOCS SHA Ubuntu + Windows CI;
- both must be SUCCESS before READY_FOR_RE_GATE.

---

## 7. Existing gates remain unchanged

- PR #15 remains DRAFT / OPEN, stacked on PR #12; **no merge, retarget, rebase-to-main or cherry-pick**.
- PR #16 remains **FROZEN DRAFT**; no scene work.
- PR #14 remains unmerged and without merge authorization.
- Issue #6 remains `BLOCKED_PR14_NOT_ON_MAIN`.
- PR #13 Round 3B remains blocked; no articulation authority copy, no legacy 75° promotion, no DOOR_OPEN claim.
- No live H3/LTX/Vision/CNC/LASER/PLC work.
- `MERGE_AUTHORIZED=false`.

---

## 8. Final handoff

When all correction gates pass, leave one concise Issue #1 `READY_FOR_RE_GATE` handoff with:

- this instruction SHA;
- exact new CODE SHA and CODE CI run/jobs;
- reproduction result from old CODE `d684686...`;
- exact fields fixed;
- total/focused test counts;
- clean REAL acceptance ID and Blender/OptiX/usedMock fields;
- counts/results for prior + new tamper matrices;
- exact DOCS SHA and DOCS CI run/jobs;
- `inputTruth` and REAL/MOCK/PARTIAL/BLOCKED truth matrix;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`;
- PR #16 frozen / Issue #6 blocked / `MERGE_AUTHORIZED=false`.

Then STOP for Supervisor Re-Gate. Do not start Round 4 automatically.
