# Development Agent 指令：PR #15 Round 3 — Variant Input Authority Gate V1

> Supervisor checkpoint: 2026-09-16
> Current main before this instruction: `64e9d12380b5c4d2329f383d1fd481656075239e`
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR #15 base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Reviewed CODE: `bedc9a08bcdec19076ea70d0000a2a2a272e15db`
> Reviewed DOCS / PR head: `7ca89384c1328710a60ddbff18c160c64e7680d1`
> Decision: **ACCEPT WITH SCOPE / GO**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Supervisor decision

PR #15 Round 2 durable batch-state / exact request-row-publication lineage gate is accepted **within its declared scope**.

Verified evidence:

- exact CODE `bedc9a08bcdec19076ea70d0000a2a2a272e15db`;
- Actions `35057461216`: Ubuntu + Windows SUCCESS, 980 tests each;
- exact DOCS `7ca89384c1328710a60ddbff18c160c64e7680d1`;
- Actions `35059083680`: Ubuntu + Windows SUCCESS, 980 tests each;
- clean REAL acceptance `8305eb4c-8bd6-4112-a248-4219d8d92aac`;
- Blender 5.2.1 LTS + OptiX, `realOptix=true`, `usedMock=false`;
- two REAL synthetic static cabinet variants with artifact SHA/bytes, finite images, `.blend` reopen, publication seal, exact batch/request/row/generation binding;
- actual server restart/history/download validation;
- stale geometry / artwork revoke invalidation;
- 30 tamper/restoration outcomes;
- cancelled/interrupted state does not resurrect success;
- existing Scheduler / Queue / DAM / composition renderer were reused rather than rewritten.

Truth boundary remains mandatory:

- GitHub CI = **MOCK regression only**;
- REAL render evidence = **REAL_RENDER + SYNTHETIC_STATIC_FIXTURE**;
- batch verifier / receipts / lineage = **REAL_LOGIC**;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `globalProductionReady=false`;
- local trusted filesystem semantics are not hostile-admin cryptographic security;
- PR #15 remains stacked on unmerged PR #12;
- `MERGE_AUTHORIZED=false`.

Do not merge PR #15, do not change its base, do not rebase-to-main, and do not open PR #17 for this round.

---

## 1. Round 3 objective — make batch input authority explicit and fail-closed

Round 2 proves durable lineage of **what was requested and what was published**. Round 3 must add an explicit authority boundary for **what the product master input actually means**.

Current synthetic/static/reference masters must never become physical manufacturing truth merely because a batch rendered successfully.

Add an additive, versioned authority snapshot used by product-variant batch submission and verification. Reuse existing master, classification, artwork, composition, publication and batch identity systems. Do not create a second Product Master service.

Required authority model (name may follow existing code conventions):

- authority version;
- tenant ID;
- master/model ID;
- master revision;
- master input hash;
- geometry authority kind;
- geometry evidence/reference hashes;
- dimension authority status;
- dieline/surface authority status where applicable;
- artwork authority hash / current artwork revision where applicable;
- source classification/category revision only as metadata, **not** physical truth;
- created/approved provenance sufficient to reproduce the decision;
- immutable authority snapshot hash included in batch request identity.

Minimum authority kinds:

- `SYNTHETIC_FIXTURE`
- `REFERENCE_RECIPE`
- `OPERATOR_DECLARED_UNMEASURED`
- `MEASURED_OR_CAD_AUTHORITY`

Do not infer `MEASURED_OR_CAD_AUTHORITY` from Blender geometry, category name, screenshots, Vision, AI, worker observation or successful render output.

---

## 2. Required behavior

### 2.1 Batch request binding

Every new batch request must bind the exact authority snapshot/hash in addition to existing Round 2 identity.

A completed generation is valid only when all of these still match:

- tenant;
- master/model ID;
- master revision;
- master input hash;
- authority version/hash;
- geometry authority kind;
- exact request/selection hash;
- row order / SKU / scene / generation ID;
- publication/manifest authority;
- current artwork validity.

Authority snapshot mismatch or disappearance must fail closed.

### 2.2 Availability versus readiness

Separate visual availability from manufacturing/print readiness.

A REAL Blender render may remain downloadable as a **visual/reference asset** when its exact historical authority remains valid, but it must not imply manufacturing/print readiness.

Expose machine-readable flags at verified batch/row level such as:

- `visualAssetReady`
- `physicalGeometryAuthorityReady`
- `printSurfaceAuthorityReady`
- `manufacturingReady`
- `physicalPrintValidated`

For all existing synthetic/static fixture acceptance data in this round:

- `visualAssetReady` may be true after normal publication verification;
- `physicalGeometryAuthorityReady=false`;
- `printSurfaceAuthorityReady=false` unless an already-reviewed exact surface authority exists;
- `manufacturingReady=false`;
- `physicalPrintValidated=false`.

Do not add a bare unscoped `productionReady=true`.

### 2.3 Revocation / stale behavior

The following must invalidate current batch availability/readiness in a deterministic fail-closed way:

- master revision/hash changed;
- authority snapshot/hash changed;
- authority downgraded/revoked;
- artwork revoked/stale;
- request snapshot tampered;
- row identity tampered;
- publication/manifest tampered.

Historical exact generations may remain historically inspectable/downloadable only when the historical authority snapshot and publication are still valid under existing historical-download rules. Do not silently bind a historical row to the latest authority.

### 2.4 No fake physical truth

The following are forbidden authority upgrades:

- using category/tree placement as dimensional proof;
- using generated mesh dimensions as source measurement;
- using prior fixture dimensions as measured product data;
- using Vision/AI/photo inference to mark CAD/measured authority;
- using Blender reopen success as physical correctness;
- using artifact SHA as engineering approval;
- using Mock CI as REAL evidence.

---

## 3. Tests — additive regression only

Keep existing 980-test behavior green and add focused tests for authority binding.

At minimum cover:

1. synthetic fixture request persists `SYNTHETIC_FIXTURE` and cannot become physical-ready;
2. reference Recipe preserves `REFERENCE_RECIPE` and explicit unmeasured state;
3. authority hash tamper -> fail closed;
4. authority version missing/unknown -> fail closed;
5. master revision/input hash changes -> stale/unavailable;
6. authority downgrade/revoke -> current readiness false;
7. category/classification change alone does not upgrade physical authority;
8. row/publication still exact while authority mismatch -> reject current completion/readiness;
9. historical generation never rebinds to latest authority silently;
10. cross-tenant authority snapshot -> block;
11. artwork revoke remains blocking;
12. forged `MEASURED_OR_CAD_AUTHORITY` without required evidence/provenance -> block;
13. Mock worker/CI cannot set physical truth flags;
14. restart preserves exact authority snapshot identity;
15. Round 2 request/row/publication tamper matrix remains green.

If existing tests reveal a real regression, make the smallest correction; do not broaden scope.

---

## 4. Exact CODE CI gate

When implementation is complete:

1. commit CODE only;
2. run exact CODE SHA GitHub Actions;
3. Ubuntu must be SUCCESS;
4. Windows must be SUCCESS;
5. record exact run ID and both job IDs;
6. verify checkout/head SHA exactly matches CODE SHA.

GitHub Actions still uses `FOX3D_MOCK_BLENDER=1`; therefore CI remains **MOCK/unit/regression evidence**, never REAL render evidence.

If CODE CI fails, fix only the failure and repeat on the new exact CODE SHA.

---

## 5. Clean REAL Round 3 acceptance

After exact CODE dual-platform SUCCESS, extend the existing `scripts/run_model_batches_e2e.py --round2` path rather than creating a parallel renderer/queue. A `--round3` or additive authority mode is acceptable if it reuses the same batch/composition/publication path.

Run from clean working tree and bind evidence to exact CODE SHA.

Required REAL acceptance:

- Blender 5.2.1 LTS;
- OptiX / `realOptix=true`;
- `usedMock=false`;
- at least two static synthetic/reference variants;
- artifact SHA/bytes and finite nonuniform image checks;
- `.blend` reopen;
- exact Round 2 request/batch/row/generation/publication lineage still PASS;
- exact authority snapshot/hash included and re-verified after restart;
- synthetic fixture remains explicitly `physicalProductGeometryTruth=false`;
- authority tamper/revoke/downgrade scenarios fail closed;
- no claim of real killed-render interruption unless a process is actually killed and evidenced;
- no physical print/CAD/manufacturing claim.

This REAL run proves **REAL render execution + REAL_LOGIC authority enforcement over non-physical fixtures**. It does not prove physical product geometry.

---

## 6. Documentation and truth matrix

After REAL acceptance PASS, update the existing batch acceptance documents rather than creating a competing truth source:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`
- `docs/PRODUCT_VARIANT_BATCH_GUIDE.md` if operator behavior changes

Add a clear truth matrix:

- durable batch lineage: REAL_LOGIC
- input authority gate: REAL_LOGIC
- Blender execution: REAL when `usedMock=false`
- fixture/reference geometry: SYNTHETIC / REFERENCE, not physical truth
- GitHub CI: MOCK regression
- physical geometry authority: BLOCKED/false for fixture/reference inputs
- physical print: BLOCKED/false
- manufacturing release: BLOCKED/false
- live H3/LTX/Vision: unchanged / BLOCKED or MOCK
- live CNC/LASER/PLC: BLOCKED
- global Production Ready: false

DOCS commit must occur after CODE CI + clean REAL acceptance. Then run exact DOCS SHA Ubuntu + Windows CI.

---

## 7. Existing gates remain unchanged

### PR #16

Remain **FROZEN DRAFT**. No new scene feature commits. Do not use PR #16 evidence to satisfy this round.

### PR #13 / PR #14 / Issue #6

Unchanged:

- PR #14 remains accepted-with-scope but unmerged;
- Issue #6 remains `BLOCKED_PR14_NOT_ON_MAIN`;
- PR #13 Round 3B must not bypass PR #14 authority gate;
- no cherry-pick/copy of unmerged articulation authority;
- no legacy 75-degree fallback promotion;
- no DOOR_OPEN REAL claim in this round.

### PR #12 / PR #15 stack

Do not merge, retarget, rebase or flatten the stack in this round. If PR #12 head/base changes before implementation starts, report `BLOCKED_BASE_MOVED` and stop instead of silently rebasing.

---

## 8. Final handoff contract

Only after all gates pass, leave one concise Issue #1 handoff containing:

- instruction SHA;
- PR #15 current base/head relationship;
- exact CODE SHA;
- exact CODE CI run ID + Ubuntu/Windows SUCCESS;
- total/focused test counts;
- clean REAL acceptance ID;
- Blender version/device, `realOptix`, `usedMock`;
- authority model version;
- authority kinds exercised;
- authority tamper/revoke/restart summary;
- exact DOCS SHA;
- exact DOCS CI run ID + Ubuntu/Windows SUCCESS;
- `inputTruth`;
- `physicalProductGeometryTruth=false` for fixture/reference evidence;
- `physicalPrintValidated=false`;
- `manufacturingReady=false` for fixture/reference evidence;
- `globalProductionReady=false`;
- PR #16 frozen;
- Issue #6 still blocked;
- `MERGE_AUTHORIZED=false`.

Then STOP for Supervisor Re-Gate. Do not start a new feature scope automatically.
