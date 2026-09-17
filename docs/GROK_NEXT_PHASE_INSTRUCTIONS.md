# Development Agent 指令：PR #15 Round 10 — BINARY ARTIFACT PUBLICATION DURABILITY GATE

> Supervisor checkpoint: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 9B CODE: `87ea4d3ba753c811f693cec8f4a3f465aca94364`
> Accepted Round 9B DOCS: `14a2c83528b3a0d76c0ec71a51afa40cc443e30b`
> CODE Actions: `35161605399` — Ubuntu + Windows SUCCESS
> DOCS Actions: `35163856420` — Ubuntu + Windows SUCCESS
> Clean REAL Blender acceptance: `12711dff-d675-4a2e-a620-7d5ad81bf05e`
> Supervisor decision: **ACCEPT WITH SCOPE / GO ROUND 10**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Round 9B acceptance boundary

Round 9B is accepted only for the scope actually proven:

- actual host file / containing-directory flush calls on the exercised Windows NTFS and Linux surfaces: **REAL_OS_IO_FLUSH**;
- actual killed-writer / fresh-reader cases: **REAL_PROCESS_RECOVERY**;
- typed durability outcomes, ownership, identity and verifier rules: **REAL_LOGIC**;
- injected EIO / sync failures and CI renderer paths: **MOCK / FAULT_INJECTION_LOGIC**;
- post-namespace sync failure: **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
- W2 extra hard-link case: **PARTIAL / PRESERVED UNKNOWN**;
- real hardware power cut / controller-cache / reset survival: **BLOCKED / NOT_TESTED**;
- clean Blender run is **REAL_RENDER** only and uses a synthetic/static cabinet fixture.

Do not upgrade any of the following:

- `physicalProductGeometryTruth=false`
- `physicalPrintValidated=false`
- `manufacturingReady=false`
- `globalProductionReady=false`
- `MERGE_AUTHORIZED=false`

Round 9B does **not** prove durability of copied Blender artifacts, every ancestor directory, NAS/network storage, storage-controller caches, or real power-loss survival.

`docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, and `docs/CABINET_REAL_ACCEPTANCE.md` remain canonical/historical lanes. Do not rewrite them just to make dates look current. Update them only if an existing declared truth becomes factually false.

---

# 1. Round 10 objective

Close the next concrete durability boundary without redesigning the system:

**Binary render/artifact files must be fully materialized and verifier-consistent before the existing manifest / publication seal can make a generation available.**

The current accepted branch still contains direct final-name writes such as worker artifact copies in `model_compositions.generate()` / `print_preview.generate()` and derived preview image writes. Round 10 must audit and, only where required, harden those existing paths.

This is **not** a request for a new bundle database, WAL, transaction manager, queue, authority marker, or publication protocol.

Keep the existing authority chain:

`artifact bytes -> manifest hashes -> meta / verifier -> published.json -> latest pointer`

Do not create a second source of truth.

---

# 2. Baseline audit first — accepted CODE only

Start from clean exact CODE:

`87ea4d3ba753c811f693cec8f4a3f465aca94364`

Before production changes, map every file that can enter a published generation and record how it is created today.

At minimum inspect:

- `src/fox3d/model_compositions.py`
- `src/fox3d/print_preview.py`
- `src/fox3d/recipe_3d.py`
- `src/fox3d/durability.py`
- existing DAM retrieval/copy path used by the generation
- existing `manifest.json`, `meta.json`, `published.json`, and `latest.json` ordering

Explicitly enumerate:

1. worker-copied binary artifacts (`beauty.png`, `front-closed.png`, `model.glb`, `model.blend`, `geometry.json`, `golden-observation.json`, or the exact current set);
2. derived preview/artwork PNG files written locally before Blender;
3. JSON authority files already covered by Round 9B;
4. which files are verifier inputs and which files are only disposable/intermediate.

For each artifact path classify whether it currently has:

- write-to-final-name vs same-directory temp publication;
- runtime flush;
- host file flush;
- namespace synchronization;
- SHA/size verification;
- verifier binding before `published.json`;
- safe behavior after process death.

Do not call an audit finding REAL data-loss evidence unless an actual process/filesystem experiment demonstrates it.

---

# 3. Required crash-window baseline evidence

Use fresh child processes and real filesystem I/O. Do not rely only on monkeypatches.

Create deterministic Round 10 probes for the existing accepted CODE covering at least these windows:

### A. Kill during binary materialization

Kill the child while a sufficiently large artifact is still being copied/written.

After a fresh process starts, prove:

- no generation is reported `available=true` unless the full existing verifier passes;
- no download path treats the partial artifact as published authority;
- no temp/intermediate file is adopted as final authority;
- existing prior generations remain unchanged.

### B. Kill after artifact file write but before manifest authority

After artifact bytes are present but before `manifest.json` / `meta.json` authority is complete, kill the writer.

Fresh process must fail closed for that generation and must not reconstruct publication authority from loose files.

### C. Kill after manifest/meta but before `published.json`

A verifier-consistent artifact set without the existing final publication seal must not be promoted to an available published batch result where `published.json` is required.

### D. Publication / latest-pointer boundary

Exercise the window after `published.json` is committed but before or during `latest.json` update.

Keep the semantics explicit:

- immutable published generation authority and mutable convenience pointer are different;
- a failed/indeterminate latest-pointer update must never corrupt or overwrite the published generation;
- a stale latest pointer must not cause duplicate render/publication or rewrite history.

All child-kill cases are **REAL_PROCESS_RECOVERY** only for the process/filesystem behavior actually exercised. They are not power-loss tests.

---

# 4. Minimal production hardening only if baseline justifies it

If the baseline confirms final-name binary publication can be partially visible or lacks the intended durable ordering, implement the smallest shared primitive necessary.

Preferred shape: extend `src/fox3d/durability.py` with a narrowly scoped helper for **same-directory artifact publication** rather than duplicating ad-hoc fsync logic in multiple modules.

A valid implementation may use this sequence:

1. create an exact target-bound same-directory temp file;
2. stream/copy bytes to that temp;
3. flush Python/runtime buffering;
4. execute the existing platform-specific host file flush;
5. verify expected bytes/hash/size where an expected digest is already available;
6. atomically replace/rename the final artifact name;
7. synchronize the containing directory using the accepted Round 9B primitive;
8. never auto-adopt unknown debris;
9. never broad-sweep `*.tmp`;
10. never delete unrelated files.

For locally generated preview PNGs, use an equivalent target-bound temp publication path if they are part of the manifest authority set. Do not invent another seal just for PNGs.

Do **not**:

- add SQLite/PostgreSQL/Redis/WAL;
- add a second manifest/publication marker;
- add background replay;
- retry a `CommitIndeterminate` publication as though it definitely failed;
- rewrite DAM, queue, renderer, Product Master, PreviewOwnership, or batch identity architecture;
- modify worker-origin files in DAM;
- claim remote/NAS durability from a local filesystem helper.

---

# 5. Required ordering invariant

After the fix, the following must be true for a successful generation:

1. every manifest-authoritative binary/derived artifact is complete on its final path;
2. every such file's bytes/hash/size match what the manifest records;
3. `manifest.json` and `meta.json` are committed using the existing durable JSON path;
4. the existing full verifier passes;
5. only then may `published.json` be committed;
6. only after publication may `latest.json` advance.

A failure before artifact final-name publication must leave the old final absent/unchanged.

A post-namespace synchronization failure for an artifact or publication file must use the existing conservative **`CommitIndeterminate`** semantics:

- the current call returns no success;
- no automatic retry/rollback/replay;
- later readers use the unchanged verifier;
- if exact valid bytes are visible later, classify the outcome **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
- never label this `POWER_LOSS_SAFE` or `CRASH_DURABLE`.

---

# 6. Mandatory adversarial tests

Add focused tests that prove at least:

- partial/truncated temp bytes never satisfy the generation verifier;
- partial/truncated final bytes never coexist with a valid publication seal through the supported success path;
- wrong SHA, wrong size, swapped artifact, cross-generation artifact, and stale artifact all fail closed;
- corrupted `.blend`, PNG, GLB, geometry JSON, or golden observation cannot be surfaced as available when covered by the manifest;
- artifact temp from another generation is never adopted;
- symlink/reparse/extra-hardlink cases are preserved or rejected safely; do not broaden cleanup semantics;
- `CommitIndeterminate` stops the current success path and does not continue to later publication work;
- latest-pointer failure does not duplicate a generation;
- prior accepted Round 6–9B ownership, strict identity, temp-debris, and durability suites remain green.

Fault-injected I/O errors are **MOCK / FAULT_INJECTION_LOGIC** even if they test real production code.

Use actual child processes / actual host calls separately for **REAL_PROCESS_RECOVERY / REAL_OS_IO_FLUSH** evidence.

---

# 7. Exact CODE gate

When production changes are complete:

1. freeze one exact Round 10 CODE SHA;
2. run the focused Round 10 tests on Windows and Linux;
3. run the full local suite;
4. run GitHub Actions against exact CODE SHA;
5. Ubuntu + Windows must both complete SUCCESS;
6. record exact pass/skip counts and exact run ID;
7. do not substitute an earlier CI run.

GitHub CI renderer/artifact fixtures remain **MOCK regression** unless an individual test is specifically exercising the actual OS primitive, in which case only that primitive receives the narrower REAL label.

If the exact CODE CI fails, classify the defect, fix minimally, freeze a new CODE SHA, and restart this gate. Do not keep stacking speculative fixes while CI is running.

---

# 8. Clean REAL Blender acceptance

Only after exact CODE dual-platform CI is green, run a new clean acceptance on the exact Round 10 CODE:

- `FOX3D_MOCK_BLENDER=0`;
- Blender 5.2.1 LTS + OptiX;
- `usedMock=false`;
- clean working tree bound to exact CODE SHA;
- existing synthetic/static fixture scope only;
- at least two product variants;
- real PNG/BLEND/GLB/geometry/golden-observation artifact bytes;
- SHA/size checks;
- `.blend` reopen;
- finite image checks;
- restart/history/download checks;
- request/row/terminal/publication lineage checks;
- no duplicate generation/publication;
- no adoption/replay of debris;
- Round 9B durability gates retained.

This clean run is **REAL_RENDER** for the render path only. It remains synthetic visual evidence, not physical geometry, print, manufacturing, or power-loss proof.

---

# 9. Evidence package

Update the existing Round 9/10 product-variant acceptance package rather than creating a competing authority document:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Record:

- accepted Round 9B baseline CODE/DOCS;
- Round 10 baseline crash-window results A–D;
- exact files/path(s) changed;
- final Round 10 CODE SHA;
- exact CODE Actions run ID and both OS results;
- clean REAL acceptance ID;
- per-artifact SHA/size and verifier result;
- actual OS/file-system scope for host flush evidence;
- injected-fault classification;
- any remaining PARTIAL/BLOCKED conditions;
- exact DOCS SHA and exact DOCS CI.

Keep these boundaries explicit:

- local host artifact flush: **REAL_OS_IO_FLUSH** only on tested surface;
- process kill/fresh reader: **REAL_PROCESS_RECOVERY**;
- verifier/order logic: **REAL_LOGIC**;
- injected errors / mock renderer paths: **MOCK / FAULT_INJECTION_LOGIC**;
- post-namespace uncertain outcome: **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
- NAS/network filesystem durability: **BLOCKED / NOT_TESTED** unless actually exercised;
- physical power-cut/reset survival: **BLOCKED / NOT_TESTED**;
- physical product/print/manufacturing/global Production Ready: **false**.

---

# 10. Exact DOCS gate and handoff

After evidence docs are complete:

1. freeze exact DOCS/head SHA on PR #15;
2. run GitHub Actions on that exact SHA;
3. Ubuntu + Windows both SUCCESS;
4. verify checkout/head SHA exactly matches the DOCS SHA;
5. record pass/skip counts;
6. then leave one Issue #1 comment headed:

`[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 10 artifact publication durability`

The handoff must include:

- final CODE SHA;
- exact CODE Actions run ID/results;
- clean REAL acceptance ID;
- exact DOCS SHA;
- exact DOCS Actions run ID/results;
- A–D crash-window summary;
- REAL/MOCK/PARTIAL/BLOCKED matrix;
- `globalProductionReady=false`;
- `MERGE_AUTHORIZED=false`;
- PR #15 still DRAFT / OPEN / unmerged;
- PR #16 still FROZEN;
- **Round 11 HOLD**.

Then STOP for Supervisor Re-Gate.

If the baseline proves no production change is necessary, do not manufacture a code change. Produce reproducible evidence showing the current verifier/publication ordering is already sufficient for the stated Round 10 process-crash scope, run the same exact CODE/REAL/DOCS gates, and STOP for Re-Gate.

---

# 11. Frozen boundaries

- No merge / retarget / rebase-to-main / cherry-pick.
- PR #15 remains DRAFT / OPEN / unmerged.
- PR #16 remains FROZEN DRAFT.
- PR #13 / #14 and Issue #6 gates unchanged.
- No live H3 / LTX / Vision / CNC / LASER / PLC work.
- No architecture rewrite.
- No Mock/FIXTURE promotion to Production Ready.
- No physical manufacturing readiness claim.
- No power-loss claim without actual destructive hardware/power-reset evidence.
- `MERGE_AUTHORIZED=false`.
- `globalProductionReady=false`.
- **Round 11 HOLD**.
