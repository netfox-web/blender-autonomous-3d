# Development Agent 指令：PR #15 Round 11 — DAM Artifact Source Identity Gate / Evidence Closure

> Supervisor checkpoint: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 10 CODE: `0082b98bbaf9f233eda32a5382b9fc373f5a6236`
> Accepted Round 10 DOCS: `c95179455982d5caeb5338d0ed5603d1479408ea`
> Current Round 11 implementation checkpoint: `74ef218e47f10958cb8a8a66a1bf4a6aa7df7cbd`
> Current checkpoint Actions: `35180923106` — still in progress at Supervisor review; **not acceptance evidence yet**
> Supervisor decision: **PARTIAL / EVIDENCE CLOSURE REQUIRED**
> Round 12: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. Supervisor audit result

The Round 11 production-code direction is acceptable and narrow:

- `dam_identity(source)` reads the existing `DamObject.sha256` as the authoritative digest and validates it as an exact lowercase 64-hex string;
- if existing DAM metadata has `bytes` / `size`, the implementation binds that exact integer as `expected_size` without re-hashing the current source path and calling the result authoritative;
- both `model_compositions.generate()` and `print_preview.generate()` now pass the stored DAM digest/size into `publish_binary()`;
- `publish_binary()` hashes the bytes actually copied into its owned temp and compares those copied bytes to the stored expected digest before namespace publication;
- no DAM/queue/state-store/authority rewrite was introduced.

This is **REAL_LOGIC** implementation work. It is **not yet Round 11 acceptance**.

Do not start Round 12. Do not merge PR #15.

## 1. Why Round 11 is not accepted yet

The new commit is substantive, but the evidence package required by the accepted Round 11 gate is incomplete.

Missing closure at this checkpoint:

1. the mandatory baseline on exact accepted CODE `0082b98...` has not been recorded in the PR authority package;
2. focused adversarial coverage is incomplete — current changes add strict helper coverage, but do not yet prove the service-level mismatch/race/success/isolation matrix;
3. exact checkpoint Actions `35180923106` was still running at review time and cannot be treated as PASS;
4. no new clean `FOX3D_MOCK_BLENDER=0`, `usedMock=false` Blender acceptance exists on a final Round 11 CODE SHA;
5. `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md/.json` has not yet been closed for Round 11;
6. no exact final DOCS SHA + dual-platform DOCS CI exists for this round.

CI with `FOX3D_MOCK_BLENDER=1` remains **MOCK regression**, even when green.

## 2. Baseline first — accepted CODE `0082b98...`

Use an isolated checkout/worktree of exact accepted CODE `0082b98bbaf9f233eda32a5382b9fc373f5a6236`. Do not alter the accepted branch while collecting the baseline.

Required actual local-filesystem probe:

1. create a worker-style object through the existing DAM API;
2. record asset ID, stored `DamObject.sha256`, source path and original byte count;
3. mutate the bytes at `DamObject.path` after DAM registration while leaving stored DAM identity unchanged;
4. exercise the accepted artifact-copy service path far enough to determine whether mutated bytes can enter the generation folder and whether manifest/publication/latest authority advances;
5. record stored digest, mutated source digest, copied-final digest if any, manifest digest if any, authority-file presence, and verifier result.

Classification:

- code/source inspection: **REAL_LOGIC_AUDIT**;
- actual file mutation/read/copy on the exercised local filesystem: **REAL_OS_IO_INTEGRITY**;
- mocked Blender/worker portions: **MOCK**;
- do not call this NAS/object-store/power-loss evidence.

Report the actual baseline outcome. Do not manufacture a fail-open if another accepted verifier already blocks it.

## 3. Complete the focused Round 11 test matrix

Keep the current production correction unless a concrete failing test proves another minimum fix is necessary.

Add focused tests that exercise the production callers, not only `dam_identity()` in isolation.

### A. Stored digest mismatch before copy

- DAM stores digest A;
- on-disk source bytes become digest B;
- `model_compositions.generate()` and/or `print_preview.generate()` fail closed through the real copy path;
- no valid new `manifest.json`, `meta.json`, `published.json`, or `latest.json` authority advances;
- the mismatching target is absent or a prior target remains byte-identical;
- no owned temp is adopted as authority.

### B. Source changes during copy

Deterministically mutate the source while `publish_binary()` is reading it.

Required invariant: SHA computed from the **bytes actually copied** is compared against stored `DamObject.sha256`; mismatch stops publication before authority advancement.

If monkeypatch/fault injection is used, classify it **MOCK / FAULT_INJECTION_LOGIC**. Only a genuine independent-process mutation may be called REAL process/OS evidence.

### C. Correct source success

- stored DAM digest equals source bytes;
- copy succeeds;
- copied final digest == stored DAM digest;
- manifest digest == copied final digest == stored DAM digest for every source-backed worker artifact;
- stored authoritative size, when present, equals copied size;
- existing Blender/verifier/history/download/publication lineage remains green.

### D. Isolation / malformed identity remains fail-closed

Retain or add proof for:

- malformed/missing `DamObject.sha256`;
- malformed authoritative `bytes` / `size` including bool/string/negative values;
- wrong asset ID;
- cross-tenant DAM access;
- missing source;
- symlink artifact target rejection;
- wrong SHA/size preserving prior final;
- `CommitIndeterminate` never creates retry/adoption/replay authority.

Do not introduce a second digest authority. `expected_sha256` must come from the stored DAM object returned for the exact worker asset ID.

## 4. Final CODE gate

After baseline + focused tests are complete:

1. freeze one exact final Round 11 CODE SHA;
2. run the focused source-identity/publication tests;
3. run the full local suite;
4. run GitHub Actions on that exact final CODE SHA;
5. Ubuntu + Windows must both complete SUCCESS and checkout the exact final SHA;
6. record exact Actions run ID and pass/skip counts.

The current `35180923106` run may be retained as checkpoint evidence if it completes, but if any tests/docs/code are added afterward it is **not** the final CODE gate and must not be cited as such.

If CI fails, make only the smallest correction supported by the failure. Do not rewrite architecture.

## 5. New clean REAL Blender acceptance on final CODE

Only after exact final CODE dual-platform CI is green, run a fresh clean acceptance:

- `FOX3D_MOCK_BLENDER=0`;
- Blender 5.2.1 LTS + OptiX;
- `usedMock=false`;
- clean working tree bound to the exact final Round 11 CODE SHA;
- at least two current synthetic/static variants;
- record for each source-backed worker artifact: asset ID, stored DAM digest, copied digest, manifest digest, stored size if present, copied size and equality result;
- keep PNG/BLEND/GLB/geometry/golden-observation decode/reopen/finite checks as applicable;
- restart/history/download/publication lineage remains green;
- no duplicate publication and no temp adoption/replay.

Truth labels:

- exercised Blender output: **REAL_RENDER** only;
- local stored-DAM-digest → copied-byte verification: **REAL_LOGIC + REAL_OS_IO_INTEGRITY** on that local surface;
- actual host flush: **REAL_OS_IO_FLUSH** where exercised;
- injected races/errors: **MOCK / FAULT_INJECTION_LOGIC** unless truly cross-process;
- post-namespace sync uncertainty remains **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
- W2 hard-link ambiguity remains **PARTIAL / PRESERVED UNKNOWN**;
- NAS/object-store immutable-source guarantee and hardware power-loss remain **BLOCKED / NOT_TESTED**.

Do not change physical/manufacturing/global readiness flags.

## 6. Acceptance docs and final handoff

Update only the existing PR #15 authority package:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Record:

- accepted Round 10 lineage;
- exact accepted-CODE baseline probe and outcome;
- final Round 11 CODE SHA + changed files;
- exact final CODE Actions and pass/skip counts;
- mismatch/race/success/isolation evidence and correct REAL/MOCK classification;
- stored DAM digest → copied final digest → manifest digest equality for clean success;
- new clean REAL acceptance ID;
- remaining PARTIAL/BLOCKED boundaries;
- exact final DOCS SHA + exact dual-platform DOCS CI.

Do not rewrite merely for freshness:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their boundaries remain valid: Mock pytest is not production evidence; CNC live control is BLOCKED; Vision Judge is MOCK; `globalProductionReady=false`.

When all closure is complete, leave exactly one Issue #1 handoff headed:

`[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 11 DAM artifact source identity`

Include final CODE SHA/Actions, baseline outcome, clean REAL ID, final DOCS SHA/Actions, digest-equality summary, truth matrix, `MERGE_AUTHORIZED=false`, PR #15 DRAFT/OPEN/unmerged, PR #16 FROZEN, and **Round 12 HOLD**. Then STOP for Supervisor Re-Gate.

## 7. Frozen boundaries

- No merge / retarget / rebase-to-main / cherry-pick.
- PR #15 stays DRAFT / OPEN / unmerged.
- PR #16 stays FROZEN DRAFT.
- PR #13 / #14 and Issue #6 gates unchanged.
- No live H3 / LTX / Vision / CNC / LASER / PLC work.
- No DAM/queue/storage/authority architecture rewrite.
- No second authority, storage ledger, replay subsystem, or duplicate DAM.
- No Mock/FIXTURE promotion to Production Ready.
- No physical manufacturing-readiness claim.
- `MERGE_AUTHORIZED=false`.
- `globalProductionReady=false`.
- **Round 12 HOLD**.
