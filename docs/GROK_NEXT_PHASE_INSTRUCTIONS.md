# Development Agent 指令：PR #15 Round 12 — Publication Receipt → Manifest Identity Gate

> Supervisor Re-Gate: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 11 CODE: `74ef218e47f10958cb8a8a66a1bf4a6aa7df7cbd`
> Accepted Round 11 DOCS: `a40c5005f8e2f6d32f7aa76012bf934c975124f5`
> CODE Actions: `35180923106` — Ubuntu + Windows SUCCESS
> DOCS Actions: `35183320822` — Ubuntu + Windows SUCCESS
> Clean REAL evidence: `53b009bc-74f8-4fab-acba-38a967bc0271`
> Supervisor decision: **Round 11 ACCEPT WITH SCOPE / GO Round 12**
> Round 13: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. Round 11 accepted scope

Round 11 is accepted for its stated DAM source-identity objective.

Accepted facts:

- the accepted-code baseline proved the old path could copy post-registration mutated DAM bytes while stored `DamObject.sha256` remained unchanged;
- `dam_identity(source)` now requires a strict stored lowercase 64-hex digest and valid optional authoritative size;
- `model_compositions.generate()` and `print_preview.generate()` pass that stored identity into `publish_binary()`;
- `publish_binary()` hashes the **bytes actually copied** and compares them against stored DAM identity before namespace publication;
- exact CODE CI and exact DOCS CI are dual-platform green;
- clean Blender 5.2.1 LTS + OptiX evidence is `usedMock=false`, but input remains `SYNTHETIC_STATIC_FIXTURE`.

Truth classification remains:

- DAM digest binding / publication checks: **REAL_LOGIC**;
- accepted local tamper baseline: **REAL_OS_IO_INTEGRITY** on the exercised local filesystem;
- GitHub Actions with `FOX3D_MOCK_BLENDER=1`: **MOCK regression**;
- injected TOCTOU/failure paths: **MOCK / FAULT_INJECTION_LOGIC** unless a genuine independent process is used;
- clean Blender evidence: **REAL_RENDER** for synthetic/static fixtures only;
- NAS/object-store guarantees, hardware power-loss, physical CAD/print/manufacturing: **BLOCKED / NOT_TESTED**.

Do not promote any of the above to global Production Ready.

## 1. New Round 12 finding — manifest can re-authorize bytes after publication

Do **not** rewrite the architecture. The next gate is a narrow identity-continuity problem.

Current accepted code correctly verifies worker DAM bytes at `publish_binary()` time, but both generation paths later build `manifest['files']` by re-reading the current files from the generation directory:

- `model_compositions.generate()` → `files={f.name: sha256_bytes(f.read_bytes()) ...}`
- `print_preview.generate()` → same pattern.

Also, derived preview PNG publication currently ignores the `publish_bytes()` return receipt and then re-reads the final path to establish `source.fileSha256`.

That means a byte change **after successful publication but before manifest/package identity capture** can potentially be re-hashed and silently become the new authority. Round 11 proves source identity at copy time; Round 12 must prove that identity remains continuous through manifest authority.

Required invariant:

**publication receipt / stored expected identity → final file verification → manifest digest must remain the same identity. A later re-read must never become a new authority merely because the bytes are self-consistent at that moment.**

## 2. Baseline first — exact accepted CODE `74ef218...`

Use an isolated checkout/worktree of exact accepted CODE `74ef218e47f10958cb8a8a66a1bf4a6aa7df7cbd`.

Create a deterministic actual-local-filesystem probe at the narrow window:

1. let a source-backed worker artifact complete `publish_binary()` successfully with the correct stored DAM digest;
2. after publication returns, mutate the **generation-folder final artifact** before `manifest.json` is constructed;
3. use a structurally valid replacement where practical (for example a valid PNG) so an unrelated decoder error does not hide the identity problem;
4. continue the existing production caller path;
5. record publication receipt digest/size, mutated final digest/size, manifest digest if produced, verifier result, and presence of `manifest.json`, `meta.json`, `published.json`, `latest.json`;
6. repeat the same idea for one derived PNG produced by `publish_bytes()` if the current path can similarly re-authorize changed bytes.

Classification:

- actual file mutation/read/write on local storage: **REAL_OS_IO_INTEGRITY**;
- monkeypatch used only to place the mutation at an exact call boundary: **MOCK / FAULT_INJECTION_CONTROL** for the trigger, while the file IO result itself may still be recorded separately as actual local IO;
- do not call this cross-process, NAS or power-loss evidence unless those were truly exercised.

Report the real outcome. Do not fabricate a fail-open if another existing verifier already blocks the mutation.

## 3. Minimum implementation correction

Make the smallest change that preserves the current architecture and authority model.

### A. Source-backed worker artifacts

For every `publish_binary()` call:

- retain its returned `{sha256, size}` receipt in memory for that generation;
- assert receipt SHA equals stored `DamObject.sha256` and authoritative size when present (the helper already enforces this; retain the explicit lineage in evidence);
- build the manifest digest for that file from the accepted publication identity/receipt — **not from a later uncontrolled re-read that can become a new authority**;
- before authority advancement, re-open the final path and verify current SHA/size still equals the receipt;
- mismatch/missing/non-regular/symlink target must fail closed before `published.json` / `latest.json` advancement.

Required clean-success chain:

`stored DAM SHA == publish_binary receipt SHA == verified final SHA == manifest SHA`

and, when authoritative size exists:

`stored DAM size == receipt size == verified final size`.

### B. Derived PNGs from `publish_bytes()`

Do not create a second digest authority.

- use the `publish_bytes()` return receipt as the original derived-file identity;
- `placement.source.fileSha256` must come from that receipt, not from a later read becoming authoritative;
- keep the existing decode/reopen validation;
- before manifest/publication authority advances, verify final file SHA/size against the receipt/placement identity;
- manifest SHA must equal the same receipt identity.

Required clean-success chain:

`publish_bytes receipt SHA == placement source.fileSha256 == verified final SHA == manifest SHA`.

### C. Keep existing validators authoritative

Do not weaken or replace:

- exact file-set verification;
- existing `print_preview.validate()` / worker observation checks;
- tenant isolation / revocation / master-current checks;
- `CommitIndeterminate` semantics;
- existing atomic JSON / publication ordering.

Do **not** add DB/WAL, a second ledger, replay engine, rollback authority, duplicate manifest, new queue or new DAM implementation.

## 4. Required adversarial tests

Add focused production-caller tests for both `model_compositions` and `print_preview` where applicable.

Minimum matrix:

1. **worker final tampered after `publish_binary()` / before manifest** → fail closed; tampered bytes must not become manifest authority; no `published.json` / `latest.json` advancement;
2. **derived PNG tampered after `publish_bytes()` / before manifest** → fail closed; placement/manifest identity must remain the original receipt;
3. **missing final after receipt** → fail closed;
4. **final replaced by symlink or non-regular path** where the platform permits the test → fail closed; platform-limited skipped tests must be labeled honestly;
5. **correct success** → prove the complete SHA/size equality chains above for every source-backed worker artifact and every derived PNG;
6. existing wrong tenant, revoked artwork, malformed DAM identity, wrong SHA/size, no retry/rollback/replay, and `CommitIndeterminate` regressions remain green.

Do not claim hard-link or hostile concurrent-writer immunity beyond what is actually tested. Existing hard-link ambiguity may remain **PARTIAL / PRESERVED UNKNOWN** unless this round genuinely resolves it without broad architecture changes.

## 5. Final CODE gate

After the narrow correction and focused tests:

1. freeze one exact final Round 12 CODE SHA;
2. run focused tests;
3. run full local `pytest`;
4. run GitHub Actions on that exact CODE SHA;
5. Ubuntu + Windows must both be SUCCESS and checkout that exact SHA;
6. record exact Actions run ID and pass/skip counts.

CI uses `FOX3D_MOCK_BLENDER=1`, therefore it remains **MOCK regression evidence**, not REAL Blender acceptance.

If CI fails, make only the smallest correction supported by the failure. Do not start Round 13.

## 6. New clean REAL Blender acceptance

Only after exact final CODE dual-platform CI is green, run a fresh clean acceptance on the exact CODE SHA:

- Blender 5.2.1 LTS + OptiX;
- `FOX3D_MOCK_BLENDER=0`;
- `usedMock=false`;
- clean working tree;
- at least two current synthetic/static variants;
- record publication receipt SHA/size, stored DAM SHA/size, verified final SHA/size and manifest SHA for source-backed worker artifacts;
- record receipt/placement/final/manifest SHA for derived PNGs;
- `.blend` reopen, finite pixels, artifact decode/reopen and existing lineage/history/download checks remain green;
- no duplicate publication, replay or temp adoption.

This can be **REAL_RENDER** plus exercised local **REAL_OS_IO_INTEGRITY**. It is still not physical CAD truth, print proof, NAS durability, power-loss durability or manufacturing readiness.

## 7. Acceptance docs and handoff

Update only the existing PR #15 authority package unless a factual correction to another canonical document is strictly required:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Record a `round12` section with:

- accepted Round 11 lineage;
- exact accepted-code baseline probe and outcome;
- exact final Round 12 CODE SHA + changed files;
- exact CODE Actions ID and pass/skip counts;
- adversarial matrix with REAL/MOCK/PARTIAL/BLOCKED classification;
- complete receipt → final → manifest identity chains;
- fresh clean REAL acceptance ID;
- remaining hard-link / NAS / power-loss / physical-manufacturing boundaries;
- exact final DOCS SHA + exact dual-platform DOCS CI.

Do not rewrite merely for freshness:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their truth boundaries remain authoritative: Mock pytest is not Production Ready; CNC live control remains BLOCKED; Vision Judge remains MOCK; `physicalPrintValidated=false`; `globalProductionReady=false`.

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
