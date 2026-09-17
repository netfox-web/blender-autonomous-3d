# Development Agent 指令：PR #15 Round 13 — Manifest / Publication Seal / Latest Pointer Identity Gate

> Supervisor Re-Gate: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 12 CODE: `0780d24e04fbed59e33f7fad36d7bff886998b01`
> Accepted Round 12 DOCS: `46615b2befb3d2e9b707754266677268ed2b9962`
> CODE Actions: `35196017765` — Ubuntu + Windows SUCCESS
> DOCS Actions: `35198732575` — Ubuntu + Windows SUCCESS
> Supervisor decision: **ACCEPT WITH SCOPE / GO Round 13**
> Round 14: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. Round 12 accepted scope

Round 12 is accepted with the existing truth boundaries.

Accepted facts:

- both production callers retain publication receipts for worker/DAM-backed artifacts and derived PNGs;
- the complete expected receipt set is verified before manifest construction and again before publication/latest authority advancement;
- `print_preview.validate()` rejects symlink/non-regular expected artifact paths;
- final CODE `0780d24e04fbed59e33f7fad36d7bff886998b01` has exact dual-platform Actions `35196017765` SUCCESS;
- final DOCS `46615b2befb3d2e9b707754266677268ed2b9962` has exact dual-platform Actions `35198732575` SUCCESS;
- clean REAL evidence `4c135de2-3aa2-4988-8201-8633a02cc5ae` used Blender 5.2.1 LTS + OptiX with `usedMock=false`, and recorded receipt -> verified final -> manifest equality for current synthetic/static variants.

Truth classification remains:

- receipt/manifest binding implementation: **REAL_LOGIC**;
- actual local file mutation/read observations: scoped **REAL_OS_IO_INTEGRITY** only where directly exercised;
- clean Blender evidence: **REAL_RENDER** only;
- GitHub Actions: **MOCK regression** because CI uses the mock Blender lane;
- monkeypatch timing triggers: **MOCK / FAULT_INJECTION_CONTROL**;
- hard-link/hostile concurrent-writer immunity: **PARTIAL / PRESERVED UNKNOWN**;
- NAS/object-store durability, hardware power-loss, physical CAD/print/manufacturing: **BLOCKED / NOT_TESTED**.

Do not reinterpret Round 12 as global Production Ready.

## 1. New Round 13 finding — artifact receipts are closed, but JSON authority identity can still drift between validation and pointer advancement

The current accepted Round 12 code closes the artifact-byte receipt gap, but the JSON authority chain still has a smaller TOCTOU/read-path gap.

### A. `model_compositions.generate()`

Current order is effectively:

`manifest.json -> meta.json(manifestSha) -> validate -> business/current checks -> receipt reverify -> published.json(re-hash current manifest) -> latest.json`

The code re-reads and re-hashes `manifest.json` when creating `published.json`. If `manifest.json` changes after the earlier validator has passed but before `published.json` is written, `published.json` can bind the later bytes even though those later bytes were not the validated manifest/meta pair. The following `latest.json` can then advance to a generation that the read path later rejects.

This is an **authority pollution / identity drift window**, not proof of a successful invalid production result.

### B. `model_compositions.status()` read path

`generation()` correctly checks `published.json` for modern `historyVersion=1` generations, but `status()` only escalates to `generation()` when `inputAuthority` / `inputAuthorityHash` is present.

Therefore a normal current composition with `historyVersion=1` but no input-authority extension can potentially report `generated=true` after `published.json` is deleted or corrupted, because `print_preview.validate()` alone validates manifest/meta/artifacts but does not require the publication seal.

This read-path inconsistency is the primary Round 13 blocker.

### C. `print_preview.generate()`

Print preview has no separate `published.json` contract and must not gain a new second authority. Its existing authority is `manifest.json + meta.json + latest.json`.

However, after the existing `validate(folder)` call, the code performs receipt verification and then advances `latest.json` without re-binding the manifest/meta pair to the exact validated manifest digest at that final pointer boundary. A mutation after validation can therefore advance `latest.json` to a generation that the next read rejects.

Round 13 must close this with the existing manifest/meta contract, not by inventing a new publication ledger.

## 2. Required accepted-code baseline before correction

Use an isolated exact checkout/worktree of accepted CODE:

`0780d24e04fbed59e33f7fad36d7bff886998b01`

Run real local-filesystem probes with deterministic timing controls. Do not modify the accepted checkout.

Minimum baseline cases:

1. **Model composition manifest drift after successful validate / before published**
   - allow current `print_preview.validate(target)` to return success;
   - mutate `manifest.json` before `published.json` creation;
   - record old validated manifest SHA, mutated SHA, `meta.json` SHA, resulting `published.json` SHA if created, `latest.json` presence, and fresh `status()` / `generation()` behavior.

2. **Model composition publication seal loss after successful completion**
   - complete one accepted-path generation;
   - delete `published.json`, then call the public/current status path;
   - repeat with mismatched `published.json.manifestSha256`;
   - record whether `generated` remains true or false.

3. **Print preview manifest/meta drift after successful validate / before latest**
   - allow `validate(folder)` to return success;
   - mutate `manifest.json` or `meta.json` before `latest.json` advancement;
   - record pointer presence and fresh status behavior.

The timing hook may be monkeypatched and is **MOCK / FAULT_INJECTION_CONTROL**. The filesystem bytes/read result can be labeled only as scoped **REAL_OS_IO_INTEGRITY** when actually exercised.

Do not fabricate a fail-open result. Record the actual behavior.

## 3. Minimal production correction — bind one validated manifest identity through existing authorities

Do not redesign storage. Do not add DB/WAL, a new ledger, a duplicate manifest, replay engine or global locks.

### A. Capture one manifest digest and keep it immutable for the publication transaction

For each generation path, after the final manifest object is assembled and durably written:

1. require `manifest.json` to be a regular non-symlink file;
2. compute a single `manifest_sha` from the written bytes;
3. write existing `meta.json` using exactly that `manifest_sha`;
4. validate current manifest/meta/artifacts through the existing validator;
5. preserve the captured `manifest_sha` as the transaction identity; do not silently replace it later with a new digest read from changed bytes.

### B. Re-verify manifest/meta immediately before pointer/publication authority

Add a small reusable helper in an existing module if useful, but do not create a second authority protocol.

Immediately before `published.json` / `latest.json` advancement, require:

- `manifest.json` exists, is regular, non-symlink, and SHA == captured `manifest_sha`;
- `meta.json` exists, is regular, non-symlink, parses correctly, and `meta.manifestSha256 == manifest_sha`;
- the existing artifact receipt set remains verified;
- the existing current-master/revocation/input-authority checks remain unchanged.

For `model_compositions`:

- create `published.json` with the **captured** `manifest_sha`, not a fresh authority-changing re-hash;
- verify the resulting publication seal is a regular non-symlink JSON authority and still references the captured `manifest_sha` before advancing `latest.json`;
- preserve current order: manifest/meta -> validate/current checks -> published -> latest.

For `print_preview`:

- keep the existing authority model; **do not add `published.json`**;
- re-verify the captured manifest/meta identity and artifact receipt set immediately before `latest.json`.

### C. Align model-composition read paths with the publication seal

Modern retained results with `historyVersion == 1` must not be reported `generated=true` unless the existing publication seal is present and matches the validated manifest.

Make the smallest change:

- `status()` should route modern `historyVersion==1` composition results through the existing `generation()` validation path (or an equivalent shared verifier);
- missing, malformed, symlink/non-regular or mismatched `published.json` must make the result unavailable/fail closed;
- legacy results without `historyVersion` may keep the existing legacy behavior if currently supported;
- do not weaken current input-authority, tenant, artwork-revocation, source-revision or history checks.

## 4. Required adversarial matrix

Add production-caller tests, not helper-only tests.

### Model compositions

1. manifest mutation after successful validator / before `published.json` -> fail closed; no latest advancement;
2. meta mutation after successful validator / before `published.json` -> fail closed; no latest advancement;
3. manifest replaced by symlink to same bytes at final authority boundary -> fail closed;
4. meta replaced by symlink/non-regular where supported -> fail closed;
5. published seal missing after an otherwise complete modern generation -> public `status()` must not report `generated=true`;
6. published seal digest mismatch -> public `status()` and `generation()` fail closed;
7. published seal symlink/non-regular -> fail closed;
8. correct success -> `meta.manifestSha256 == captured manifest SHA == published.manifestSha256`, then `latest.json` points to that generation;
9. historical valid generation remains readable through `history()` / current public retrieval rules;
10. legacy no-`historyVersion` compatibility remains only if explicitly supported and tested.

### Print preview

11. manifest mutation after successful validate / before latest -> fail closed; no latest advancement;
12. meta mutation after successful validate / before latest -> fail closed; no latest advancement;
13. manifest/meta symlink/non-regular at final pointer boundary -> fail closed;
14. correct success -> captured manifest SHA == meta SHA, artifacts/receipts valid, then latest advances;
15. fresh status after any rejected pointer attempt must not report the invalid generation as generated.

Retain Round 9B–12 tests for `CommitIndeterminate`, artifact receipts, source DAM identity, tenant isolation, wrong SHA/size, no replay/rollback/adoption and current-master/artwork revocation.

## 5. Final CODE gate

After the narrow correction:

1. freeze one exact Round 13 CODE SHA;
2. run focused tests and full local `pytest`;
3. run GitHub Actions on that exact SHA;
4. Ubuntu + Windows must both be SUCCESS and checkout that exact SHA;
5. record Actions run ID and pass/skip counts.

CI remains **MOCK regression**. Do not label it REAL Blender acceptance.

## 6. Clean REAL acceptance

Only after exact final CODE dual-platform CI is green, run one fresh clean acceptance on that exact CODE:

- Blender 5.2.1 LTS + OptiX;
- `FOX3D_MOCK_BLENDER=0`;
- `usedMock=false`;
- clean working tree;
- at least two current synthetic/static variants;
- prove existing receipt -> final -> manifest chain remains exact;
- additionally record `manifest_sha -> meta.manifestSha256 -> published.manifestSha256` for model compositions;
- for print preview record `manifest_sha -> meta.manifestSha256 -> latest generationId` with final boundary verification;
- restart/history/status/download checks must remain green;
- `.blend` reopen, finite pixels and artifact decode/reopen remain green.

Classify only as **REAL_RENDER** plus scoped local **REAL_OS_IO_INTEGRITY** where directly observed. It is not physical product geometry, print proof, manufacturing readiness, NAS durability or power-loss proof.

## 7. Acceptance package and handoff

Update the existing PR #15 evidence package:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Record:

- accepted Round 12 CODE/DOCS lineage;
- exact baseline outcomes for the three Round 13 windows;
- final CODE SHA and changed files;
- exact CODE Actions + platform results;
- adversarial matrix;
- manifest/meta/published/latest identity chains;
- new clean REAL acceptance ID;
- final DOCS SHA and exact DOCS dual-platform CI;
- remaining REAL/MOCK/PARTIAL/BLOCKED boundaries.

Do not rewrite for freshness only:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their current boundaries remain authoritative: Mock pytest is not Production Ready; CNC live control remains BLOCKED; Vision Judge remains MOCK; `physicalPrintValidated=false`; `globalProductionReady=false`.

When complete, leave exactly one Issue #1 handoff headed:

`[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 13 manifest/publication pointer identity`

Include final CODE SHA/Actions, accepted-code baseline outcomes, clean REAL ID, DOCS SHA/Actions, truth matrix, `MERGE_AUTHORIZED=false`, PR #15 DRAFT/OPEN/unmerged, PR #16 FROZEN, and **Round 14 HOLD**. Then STOP for Supervisor Re-Gate.

## 8. Frozen boundaries

- No merge / retarget / rebase-to-main / cherry-pick.
- PR #15 stays DRAFT / OPEN / unmerged.
- PR #16 stays FROZEN DRAFT.
- PR #13 / #14 and Issue #6 gates unchanged.
- No live H3 / LTX / Vision / CNC / LASER / PLC work.
- No DAM/queue/storage/authority architecture rewrite.
- No DB/WAL/second authority/replay subsystem/duplicate manifest.
- No Mock/FIXTURE promotion to Production Ready.
- No physical manufacturing-readiness claim.
- `physicalProductGeometryTruth=false`.
- `physicalPrintValidated=false`.
- `manufacturingReady=false`.
- `globalProductionReady=false`.
- `MERGE_AUTHORIZED=false`.
- **Round 14 HOLD**.
