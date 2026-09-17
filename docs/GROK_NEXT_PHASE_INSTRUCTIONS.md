# Development Agent 指令：PR #15 Round 12 Re-Gate Correction — Receipt Boundary Closure

> Supervisor Re-Gate: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 11 CODE: `74ef218e47f10958cb8a8a66a1bf4a6aa7df7cbd`
> Accepted Round 11 DOCS: `a40c5005f8e2f6d32f7aa76012bf934c975124f5`
> Round 12 candidate reviewed: `9062ae92f3b4f2171e6328ec6c1025ff495bc21b`
> Candidate CODE Actions: `35190925369` — Ubuntu + Windows SUCCESS
> Supervisor decision: **CHANGES REQUIRED / correction-only**
> Round 13: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. What is accepted from candidate `9062ae92...`

The direction is correct and must be preserved:

- `publish_bytes()` receipts are retained for derived PNGs;
- `placement.source.fileSha256` now comes from the publication receipt rather than a later read;
- `publish_binary()` receipts are retained for worker/DAM-backed artifacts;
- manifest SHA selection prefers the retained receipt for receipt-tracked files;
- `verify_receipt()` rejects a symlink/non-regular target **when that helper is actually called** and checks current SHA/size against the receipt;
- exact candidate CI run `35190925369` completed SUCCESS on both Ubuntu and Windows.

Truth classification at this checkpoint:

- receipt lineage / digest binding code: **REAL_LOGIC**;
- actual local file reads/writes exercised outside mocks may be reported as scoped **REAL_OS_IO_INTEGRITY** only when separately evidenced;
- GitHub Actions remain **MOCK regression** because CI uses the mock Blender lane;
- monkeypatch boundary triggers are **MOCK / FAULT_INJECTION_CONTROL**;
- no new clean `usedMock=false` evidence exists yet for this candidate, so no new **REAL_RENDER** acceptance is granted;
- hostile hard-link/concurrent-writer immunity, NAS/object-store durability, hardware power-loss, physical CAD/print/manufacturing remain **PARTIAL or BLOCKED / NOT_TESTED** as previously stated.

Do not promote candidate `9062ae92...` to Round 12 acceptance yet.

## 1. Blocking finding A — current new tests do not hit the required window

The newly added tests named around “tamper before manifest/package” currently mutate the target **inside the monkeypatched `publish_binary()` / `publish_bytes()` wrapper before the production caller performs its immediate `verify_receipt()`**.

That proves the immediate receipt check works, but it does **not** prove the Round 12 invariant:

`successful publication + successful initial receipt verification -> later mutation -> manifest/publication authority must fail closed`.

Correction requirement:

- keep the immediate verification tests;
- add separate tests that mutate only **after** the initial `verify_receipt()` has succeeded;
- the later mutation must occur before manifest authority capture / publication pointer advancement;
- record whether failure occurs at the explicit receipt-boundary check or the existing manifest validator;
- no `published.json` / `latest.json` authority may advance after mismatch.

Do not rename an immediate post-copy failure test as evidence for a post-verification/pre-manifest window.

## 2. Blocking finding B — receipt verification is not yet enforced at the authority boundary

Candidate `9062ae92...` calls `verify_receipt()` immediately after each publication, but then:

- derived PNGs can remain in the generation folder while the Blender worker runs;
- worker artifacts can remain after their immediate receipt check while manifest/pointer gates continue;
- `print_preview.validate()` hashes `read_bytes()` but does not explicitly reject a later symlink/non-regular replacement before following the path;
- `model_compositions.generate()` performs current-master / artwork / input-authority checks after `print_preview.validate()` and before `published.json`, leaving another interval before authority advancement.

The Round 12 requirement was explicit: **before authority advancement, current finals must still equal the original receipts and symlink/non-regular/missing targets must fail closed.**

Make the smallest correction; do not redesign storage.

### A. Verify the complete receipt set immediately before manifest construction

For both `model_compositions.generate()` and `print_preview.generate()`:

1. derive the exact expected artifact names from the existing package/`FILES` contract;
2. require every expected artifact to have exactly one retained publication receipt;
3. reject missing, unexpected, symlink or non-regular entries at this authority boundary;
4. call receipt verification for every expected final and preserve SHA/size equality;
5. construct `manifest['files']` from the accepted receipt identities for the exact expected set — do not allow a later uncontrolled read to become a new digest authority.

Required chain for worker artifacts:

`stored DAM SHA == publish_binary receipt SHA == authority-boundary verified final SHA == manifest SHA`

and when stored size is authoritative:

`stored DAM size == receipt size == authority-boundary verified final size`.

Required chain for derived PNGs:

`publish_bytes receipt SHA == placement source.fileSha256 == authority-boundary verified final SHA == manifest SHA`.

### B. Keep validators fail-closed for later reads

`print_preview.validate()` must explicitly reject expected paths that are symlinks or non-regular before hashing them. Preserve exact file-set verification, `validate_outputs()`, worker observation checks and REAL-Blender flags.

Do not weaken validation merely because a receipt existed earlier.

### C. Re-check immediately before final pointer/publication authority

After all existing master-current / revocation / input-authority gates and immediately before advancing `published.json` / `latest.json`, re-verify the receipt-tracked finals against the retained receipts.

- `model_compositions`: before `published.json`, then existing `latest.json` order remains intact;
- `print_preview`: before `latest.json`.

This is not a claim of hostile concurrent-writer atomicity. Existing hard-link/concurrent-writer ambiguity may remain **PARTIAL / PRESERVED UNKNOWN** unless independently solved and tested.

Do not add locks, DB/WAL, replay, second ledger, duplicate manifest or a new storage architecture in this round.

## 3. Blocking finding C — required adversarial coverage is incomplete

Add focused production-caller tests for **both** `model_compositions` and `print_preview` where applicable.

Minimum matrix:

1. immediate post-copy corruption before first `verify_receipt()` -> fail closed (existing coverage may remain);
2. worker final mutated **after first receipt verification** / before manifest -> fail closed; original receipt must remain authority;
3. derived PNG mutated **after first receipt verification** / before manifest -> fail closed; placement SHA and manifest authority remain the original receipt;
4. receipt-tracked final deleted after first verification -> fail closed;
5. receipt-tracked final replaced by symlink to bytes with the **same digest** after first verification -> still fail closed because path type is not authoritative regular-file state; skip only when platform truly cannot create the case and label the skip honestly;
6. non-regular replacement where practical -> fail closed;
7. correct worker success -> prove stored DAM SHA/size == receipt == verified final == manifest for every worker artifact;
8. correct derived success -> prove receipt == placement SHA == verified final == manifest for every derived PNG;
9. no `published.json` / `latest.json` advancement on any mismatch;
10. wrong tenant, revoked artwork, malformed DAM identity, wrong SHA/size, `CommitIndeterminate`, no replay/rollback/adoption regressions remain green.

The trigger may use a monkeypatch only to place mutation at an exact boundary; classify the trigger as **MOCK / FAULT_INJECTION_CONTROL**. Actual local filesystem mutation/read result may be documented separately as scoped local IO evidence.

## 4. Accepted-code baseline is still required

Before claiming Round 12 closure, run the original baseline probe against an isolated exact checkout/worktree of accepted CODE:

`74ef218e47f10958cb8a8a66a1bf4a6aa7df7cbd`

Exercise the actual local-filesystem window after successful publication and before manifest authority for:

- one worker/DAM-backed artifact;
- one derived PNG.

Record the real outcome, including original receipt/stored digest, mutated final digest, manifest digest if produced, validator result, and presence of `manifest.json`, `meta.json`, `published.json`, `latest.json`.

Do not fabricate a fail-open if another existing gate blocks it. This baseline is evidence of the defect/window, not proof of the correction.

## 5. Final CODE gate

After the narrow correction and tests:

1. freeze one exact final Round 12 CODE SHA;
2. run focused tests;
3. run full local `pytest`;
4. run GitHub Actions on that exact CODE SHA;
5. Ubuntu + Windows must both be SUCCESS and checkout the exact SHA;
6. record exact Actions run ID and pass/skip counts.

Candidate Actions `35190925369` is useful regression evidence for `9062ae92...`, but once production code changes again it is not the final Round 12 CI evidence.

CI remains **MOCK regression**, not REAL Blender acceptance.

## 6. New clean REAL Blender acceptance

Only after the exact final corrected CODE dual-platform CI is green, run fresh clean acceptance on that exact CODE SHA:

- Blender 5.2.1 LTS + OptiX;
- `FOX3D_MOCK_BLENDER=0`;
- `usedMock=false`;
- clean working tree;
- at least two current synthetic/static variants;
- record worker stored DAM SHA/size -> receipt -> final verification -> manifest chain;
- record derived PNG receipt -> placement SHA -> final verification -> manifest chain;
- `.blend` reopen, finite pixels, artifact decode/reopen and lineage/history/download checks remain green;
- no duplicate publication, replay or temp adoption.

This may be classified as **REAL_RENDER** plus scoped exercised local **REAL_OS_IO_INTEGRITY** only. It is not physical CAD truth, print proof, NAS durability, power-loss durability or manufacturing readiness.

## 7. Acceptance docs and final handoff

Update only the existing PR #15 authority package unless a factual correction elsewhere is strictly required:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Round 12 evidence must record:

- accepted Round 11 lineage;
- exact accepted-code baseline outcome;
- candidate `9062ae92...` checkpoint and why it required correction;
- exact final Round 12 CODE SHA + changed files;
- exact final CODE Actions ID and pass/skip counts;
- full adversarial matrix and REAL/MOCK/PARTIAL/BLOCKED labels;
- receipt -> final -> manifest equality chains;
- fresh clean REAL acceptance ID;
- remaining hard-link / hostile concurrent-writer / NAS / power-loss / physical-manufacturing boundaries;
- exact final DOCS SHA + exact dual-platform DOCS CI.

Do not rewrite merely for freshness:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their canonical boundaries remain in force: Mock pytest is not Production Ready; CNC live control remains BLOCKED; Vision Judge remains MOCK; `physicalPrintValidated=false`; `globalProductionReady=false`.

When closure is complete, leave exactly one Issue #1 handoff headed:

`[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 12 publication-to-manifest identity`

Include final CODE SHA/Actions, baseline outcome, clean REAL ID, final DOCS SHA/Actions, identity-chain summary, truth matrix, `MERGE_AUTHORIZED=false`, PR #15 DRAFT/OPEN/unmerged, PR #16 FROZEN, and **Round 13 HOLD**. Then STOP for Supervisor Re-Gate.

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
- **Round 13 HOLD**.
