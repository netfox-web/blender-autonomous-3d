# Development Agent 指令：PR #15 Round 8 — Evidence Closure / Re-Gate HOLD

> Supervisor checkpoint: 2026-09-17
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Prior accepted CODE: `0c6bb2a0e8ed8a8a7d23b8a938b5670e83f3b6c1`
> Prior accepted DOCS: `d36600e4831d7a86e29a4647cf72560b62b744d3`
> Current Round 8 PR head: `8129309c45b1db566385305e0db5a03f23c64e33`
> Round 8 CODE commits reviewed: `ed63440459021f79348c3cba8f9daf8f26d2b01f` + `8129309c45b1db566385305e0db5a03f23c64e33`
> Exact CODE Actions: `35147126655` — Ubuntu + Windows SUCCESS on `8129309c...`
> Decision: **PARTIAL / EVIDENCE CLOSURE REQUIRED — Round 9 HOLD**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Supervisor review result

Round 8 now has substantive implementation and regression coverage, but it is **not yet accepted** because the required evidence/docs closure has not been landed.

What is accepted so far as implementation direction:
- `_once()` batch temps are now target-specific (`<final>.once.<bounded-token>.tmp`) while non-batch authority keeps its prior naming contract;
- `scavenge_once_temps()` is restricted to exact immutable batch targets and requires a live existing `PreviewOwnership` for the exact workspace;
- candidates are restricted by exact name contract and regular/single-link/non-reparse checks;
- ambiguous multi-link/reparse/non-regular candidates fail closed and are preserved;
- cleanup failure blocks the next immutable publication;
- duplicate immutable publication still fails closed;
- relative workspace paths were corrected without broadening cleanup scope;
- actual subprocess hard-kill tests exist for W1/W2/W3 and request/row/terminal targets;
- actual OS behavior is exercised for process kill/restart, ownership contention, link semantics, reparse/symlink rejection and Windows delete-sharing denial;
- exact Actions run `35147126655` completed successfully on Ubuntu and Windows with checkout SHA `8129309c45b1db566385305e0db5a03f23c64e33`.

Truth classification for the current code/test state:
- target-specific publication/cleanup rules: **REAL_LOGIC**;
- actual killed writer + fresh recovery subprocess cases: **REAL_PROCESS_RECOVERY** where directly exercised;
- actual ownership/link/reparse/delete-sharing behavior: **REAL_OS_IO** where directly exercised;
- CI artifact/render path under `FOX3D_MOCK_BLENDER=1`: **MOCK regression**, never REAL_RENDER;
- W2 post-link extra hardlink debris is intentionally preserved/fail-closed because link count is ambiguous: **PARTIAL / PRESERVED UNKNOWN**, not a cleanup success claim;
- generic/global temp cleanup remains **PARTIAL / UNCLAIMED**;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`.

Do not rewrite the queue, state store, authority model, publication verifier, DAM, Renderer, Product Master, or PreviewOwnership.

---

## 1. Missing blocker A — baseline evidence on exact accepted CODE

Before asking for Re-Gate, produce durable evidence for the required W1/W2/W3 baseline on exact accepted CODE:

`0c6bb2a0e8ed8a8a7d23b8a938b5670e83f3b6c1`

Use a clean checkout/worktree of that exact SHA and real child processes. Test-harness instrumentation is allowed; production code at the baseline SHA must not be changed to manufacture the result.

For each required target class (`request.json`, at least one row receipt such as `0.json`, `terminal.json`) record:
- W1: temp fully materialized, final not linked, then hard kill;
- W2: final linked, temp not unlinked, then hard kill;
- W3: nested atomic temp interruption if reproducible;
- exact file names, directory-relative paths, type, link count where available, SHA/bytes, final existence;
- killed PID / fresh recovery PID;
- no automatic replay/adoption;
- immutable final bytes preserved when already published;
- duplicate publication remains blocked.

If old CODE uses a legacy UUID-only temp name, record that truth exactly. Do not retroactively call it target-specific.

---

## 2. Missing blocker B — Round 8 evidence package

Keep current CODE `8129309c...` frozen unless evidence reveals a real bug.

Run and record the focused Round 8 matrix separately from generic pytest:
- 3 crash windows × request/row/terminal targets;
- live competitor while owner is held = zero cleanup / zero immutable write;
- exact-target cleanup only;
- unknown/legacy temp preservation;
- nested-directory sentinel preservation;
- symlink/reparse/non-regular/multi-link preservation and fail-closed behavior;
- cleanup failure blocks publication;
- duplicate publication remains blocked;
- relative workspace path regression;
- no replay after restart;
- process restart never turns interrupted work into succeeded work.

For W2, preserve the current conservative rule unless evidence proves a safer deterministic rule: a two-link temp/final inode is **unknown/ambiguous**, therefore preserve + fail closed. Do not delete it merely because bytes match final.

Retain Round 5/6/7 + strict serialized identity regressions. If any old gate regresses, fix only that regression.

---

## 3. Missing blocker C — clean REAL acceptance because production code changed

Round 8 changed production persistence code, therefore rerun the existing clean product-variant REAL acceptance after the exact CODE CI is green.

Required:
- Blender 5.2.1 LTS;
- OptiX / `realOptix=true`;
- `usedMock=false`;
- at least two synthetic/reference variants;
- artifact SHA/size + finite pixels + `.blend` reopen;
- restart/history/download verification;
- retained process/authority/cleanup matrices;
- record Round 8 process/OS evidence separately from renderer evidence.

Still declare:
- `inputTruth=SYNTHETIC_STATIC_FIXTURE`;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`.

REAL Blender evidence does not convert the hard-kill fixture artifacts into physical/product truth.

---

## 4. Missing blocker D — DOCS closure + exact DOCS CI

Update only the necessary acceptance evidence, primarily:
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Record all of the following:
- exact accepted baseline SHA `0c6bb2a0...` W1/W2/W3 observations;
- new CODE SHA `8129309c...` (or a later minimal correction SHA only if evidence finds a bug);
- CODE Actions run ID and exact Ubuntu/Windows checkout/result;
- focused Round 8 process/OS counts;
- retained Round 5/6/7 + strict identity counts;
- clean REAL acceptance generation and exact evidence CODE SHA;
- explicit REAL / MOCK / PARTIAL / BLOCKED matrix;
- W2 ambiguous hardlink debris classification;
- unchanged global truth boundaries.

Do **not** rewrite `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md`, or `CABINET_REAL_ACCEPTANCE.md` unless their declared truth actually changes.

After docs are pushed:
1. freeze exact DOCS SHA;
2. wait for GitHub Actions Ubuntu + Windows SUCCESS on that exact SHA;
3. verify both jobs checked out the exact DOCS SHA;
4. cancelled/superseded runs are not PASS evidence.

---

## 5. Frozen gates

- PR #15 remains **DRAFT / OPEN / unmerged**;
- Round 9 remains **HOLD** until Supervisor Re-Gate;
- PR #16 remains **FROZEN DRAFT**;
- PR #13 / #14 unchanged;
- Issue #6 gate unchanged;
- no merge / retarget / rebase-to-main / cherry-pick;
- no live H3 / LTX / Vision / CNC / LASER / PLC work;
- `MERGE_AUTHORIZED=false`.

---

## 6. Final handoff

When all blockers above are closed, leave exactly one new `READY_FOR_RE_GATE` comment on Issue #1 containing:
- baseline SHA + W1/W2/W3 evidence result;
- exact final CODE SHA;
- CODE Actions run ID + Ubuntu/Windows result;
- focused Round 8 process/OS counts;
- retained Round 5/6/7 + strict identity counts;
- clean REAL acceptance generation;
- exact DOCS SHA + DOCS Actions run ID + Ubuntu/Windows result;
- REAL / MOCK / PARTIAL / BLOCKED truth matrix;
- `MERGE_AUTHORIZED=false`.

Then STOP. **Do not start Round 9 automatically.**
