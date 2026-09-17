# Development Agent 指令：PR #15 Round 13 Correction — Publication Seal / Latest Pointer Evidence Closure

> Supervisor Re-Gate: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Candidate CODE: `985385db01bdc354edbce44a4aedd78af52e0735`
> Candidate DOCS: `ec4fd968c0fdf5d98ccb0399cd0543258963f263`
> CODE Actions: `35201860277` — SUCCESS
> DOCS Actions: `35204672640` — SUCCESS
> Supervisor decision: **CHANGES REQUIRED / ROUND 13 CORRECTION ONLY**
> Round 14: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. What is accepted from the candidate

Keep the current narrow direction. Do **not** revert or redesign it.

Accepted implementation intent:

- one captured `manifest_sha` is created after manifest write;
- `meta.json` is bound to that captured digest;
- `verify_manifest_meta()` rechecks regular/non-symlink manifest + meta before authority advancement;
- model-composition `published.json` is written from the captured digest instead of a fresh re-hash;
- modern `historyVersion == 1` composition status is routed through `generation()`;
- print preview rechecks manifest/meta immediately before advancing `latest.json`;
- no DB/WAL/new ledger/replay/global lock/storage rewrite was introduced.

The candidate CI is still **MOCK regression**, not REAL Blender evidence. Clean Blender evidence remains **REAL_RENDER** only within its observed scope.

## 1. Why Round 13 is not accepted yet

### Blocker A — required production-caller adversarial tests were not added

Round 13 explicitly required production-caller tests for the manifest/meta/published/latest boundary. The diff from accepted Round 12 DOCS `46615b2befb3d2e9b707754266677268ed2b9962` to candidate DOCS `ec4fd968c0fdf5d98ccb0399cd0543258963f263` changes only:

- `src/fox3d/durability.py`
- `src/fox3d/model_compositions.py`
- `src/fox3d/print_preview.py`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

No tracked test file was added or modified for the required Round 13 matrix. Passing the retained suite does not prove the newly introduced authority behavior.

**Required correction:** add production-caller tests for the exact post-validation/pre-authority windows. Helper-only tests are not sufficient.

### Blocker B — modern model-composition read path still follows a symlinked `published.json`

Current `generation()` does:

`published = read_json(target/'published.json')`

then compares `published.manifestSha256` with the current manifest digest. `read_json()` uses normal path reads and follows symlinks. Therefore a `published.json` symlink to same-content JSON can satisfy the digest comparison.

This violates the prior requirement that missing / malformed / symlink / non-regular `published.json` fail closed on the public read path.

**Required correction:** before parsing `published.json` for a modern generation, require the path to exist, be a regular file, and not be a symlink. Then parse and require exact `manifestSha256 == validated manifest digest`. Keep legacy behavior only for explicitly supported no-`historyVersion` records.

### Blocker C — print-preview `latest.json` does not durably pin the captured manifest identity

The current print-preview correction re-verifies `manifest.json + meta.json` before writing `latest.json`, but the pointer still stores only:

`{"generationId": gid}`

After successful completion, a later mutation that changes both `manifest.json` and `meta.json` consistently can still pass `print_preview.validate()` because no persisted value outside that pair pins the originally published digest. This means the Round 13 **latest pointer identity** gate is not actually closed for print preview.

Do **not** add `published.json` to print preview. Use the existing pointer as the final authority:

- write `latest.json` with both `generationId` and the captured `manifestSha256`;
- on `print_preview.status()`, require `latest.json` to be regular/non-symlink JSON;
- strictly validate `generationId`;
- validate the pointed generation;
- require pointer `manifestSha256` to equal the validated current manifest digest / `meta.manifestSha256`;
- missing/malformed/mismatched pointer digest for the new/current schema must fail closed;
- preserve legacy compatibility only if explicitly required and covered by a regression test; do not silently upgrade old history.

This is an extension of the **existing** `latest.json` authority, not a new ledger.

### Blocker D — clean REAL evidence did not demonstrate the required print-preview authority chain

The handoff states both clean REAL generations satisfy:

`manifestSha == meta.manifestSha256 == published.manifestSha256`

That is model-composition evidence. Print preview intentionally has no `published.json`, so this does not demonstrate the separately required print-preview chain:

`manifest_sha -> meta.manifestSha256 -> latest.manifestSha256 + latest.generationId`

**Required correction:** after final corrected CODE CI is green, run fresh `usedMock=false` Blender acceptance that exercises both authority paths:

1. model composition: manifest -> meta -> published -> latest;
2. print preview: manifest -> meta -> latest(pointer digest + generation id).

Do not reuse the candidate REAL run as final evidence after code changes.

## 2. Required correction-only implementation

Make the smallest possible patch.

### A. Publication seal verifier

Prefer a tiny helper in an existing module if it reduces duplication. It must:

- reject missing path;
- reject symlink;
- reject non-regular file;
- parse JSON fail closed;
- require exact `manifestSha256` string equal to the expected captured/validated digest.

Use it in both write-boundary verification and modern model-composition read validation. Do not create another authority file.

### B. Print-preview latest pointer binding

For new/current print-preview generations:

1. capture `manifest_sha` once;
2. write `meta.json` from it;
3. validate generation + receipts;
4. final `verify_manifest_meta(folder, manifest_sha)`;
5. write existing `latest.json` as `{generationId, manifestSha256}` using existing durable JSON publication;
6. fresh public status must verify the pointer path and pointer digest before returning `generated=true`.

No DB, WAL, replay, duplicate manifest, second publication seal, or background reconciliation.

### C. Model-composition latest behavior

Do not weaken the existing chain. A modern composition is available only when:

- manifest/meta validate;
- artifact files validate;
- current source/artwork rules validate;
- publication seal is regular/non-symlink and pins the same manifest digest;
- latest points to that generation.

Do not change unrelated master/history/business semantics.

## 3. Mandatory tracked production-caller tests

Add tests under the existing test layout. They must call the production service/caller paths, not only `verify_manifest_meta()`.

### Model compositions

1. mutate manifest after initial successful validation and before `published.json` -> fail closed; no latest advancement;
2. mutate meta after initial successful validation and before `published.json` -> fail closed; no latest advancement;
3. manifest symlink at final boundary -> fail closed;
4. meta symlink/non-regular -> fail closed;
5. after a completed modern generation, delete `published.json` -> public `status.generated == false`;
6. published digest mismatch -> `status()` and `generation()` fail closed;
7. published symlink to **same valid JSON bytes** -> fail closed;
8. correct success -> manifest SHA == meta SHA == published SHA; latest points to same generation;
9. valid historical modern generation remains readable;
10. explicitly supported legacy no-`historyVersion` behavior is covered and cannot inherit modern truth.

### Print preview

11. mutate manifest after initial successful validation / before latest -> fail closed; latest not advanced;
12. mutate meta after initial successful validation / before latest -> fail closed;
13. manifest/meta symlink/non-regular at final boundary -> fail closed;
14. correct success -> manifest SHA == meta SHA == latest.manifestSha256 and latest generationId matches;
15. mutate manifest + meta consistently **after successful completion** while leaving latest untouched -> fresh status fails closed because pointer digest remains pinned;
16. latest symlink/non-regular -> fail closed for new/current schema;
17. latest manifest digest mismatch -> `generated == false`;
18. fresh status after every rejected pointer attempt does not expose the invalid generation.

Retain all Round 9B–12 durability, DAM, receipt, tenant, revocation, wrong SHA/size, indeterminate-commit, no replay/rollback/adoption tests.

## 4. Evidence classification

Keep these boundaries exact:

- captured identity / verifier logic: **REAL_LOGIC**;
- GitHub Actions and mock Blender paths: **MOCK regression**;
- deterministic monkeypatch timing trigger: **MOCK / FAULT_INJECTION_CONTROL**;
- actual local file bytes/read observations: scoped **REAL_OS_IO_INTEGRITY** only where directly observed;
- clean `usedMock=false` Blender output: **REAL_RENDER** only;
- hard-link / hostile concurrent writer: **PARTIAL / PRESERVED UNKNOWN** unless directly solved and proven;
- NAS/object storage, controller durability, hardware power-loss: **BLOCKED / NOT_TESTED**;
- physical CAD authority, physical print proof, manufacturing readiness: **BLOCKED / false**.

`globalProductionReady=false` remains mandatory.

## 5. Final evidence closure order

Do this in order and stop on any failure:

1. implement the narrow correction + tracked production-caller tests;
2. run focused tests;
3. run full local pytest;
4. freeze one exact final Round 13 CODE SHA;
5. run exact CODE GitHub Actions; Ubuntu + Windows must both SUCCESS and checkout that SHA;
6. only then run a **new** clean REAL Blender acceptance on that exact CODE with `FOX3D_MOCK_BLENDER=0`, `usedMock=false`;
7. REAL acceptance must exercise at least one valid model-composition generation and one valid print-preview generation, with the two authority chains recorded separately;
8. restart/status/history/download/reopen checks remain green where applicable;
9. update only the existing PR #15 evidence package (`docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md/.json`) with exact baseline/correction/adversarial outcomes;
10. freeze one exact DOCS SHA and run exact DOCS dual-platform CI;
11. leave one Issue #1 `[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 13 correction` handoff and STOP.

## 6. Files that must not be rewritten for freshness

Do not rewrite these merely to make timestamps look current:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their truth boundaries remain authoritative: Mock pytest is not Production Ready; Vision Judge remains MOCK; CNC live control remains BLOCKED; `physicalPrintValidated=false`; `globalProductionReady=false`.

## 7. Frozen boundaries

- No merge / retarget / rebase-to-main / cherry-pick.
- PR #15 stays DRAFT / OPEN / unmerged.
- PR #16 stays FROZEN DRAFT.
- PR #13 / #14 and Issue #6 gates unchanged.
- Round 14 stays HOLD.
- No H3 / LTX / Vision / CNC / LASER / PLC work.
- No DAM/queue/storage/authority architecture rewrite.
- No DB/WAL/second ledger/replay subsystem/duplicate manifest.
- No Mock/FIXTURE promotion to Production Ready.
- `physicalProductGeometryTruth=false`.
- `physicalPrintValidated=false`.
- `manufacturingReady=false`.
- `globalProductionReady=false`.
- `MERGE_AUTHORIZED=false`.
