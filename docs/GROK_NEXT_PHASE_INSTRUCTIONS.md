# Development Agent 下一輪指令：PR #15 Round 7 — Scoped Hard-Kill Temp Scavenging / Crash Debris Hygiene Gate

> Supervisor checkpoint: 2026-09-17
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Accepted CODE: `70587508bb8afc2ebe876cebd4304c369be7ed76`
> Accepted DOCS / PR head: `7c01e0306db106cee146e70f04e8f7b6c8e452bd`
> Decision: **Round 6 ACCEPT WITH SCOPE / GO Round 7**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Round 6 Re-Gate result

Round 6 Cross-Process Single-Writer / Duplicate Submit Ownership Gate is accepted within its declared local-filesystem scope.

Accepted evidence:

- baseline exact CODE `f5ac3a6773d99f30709a84dc9adb97231ca53ba9` reproduced A–F cross-process fail-open behavior with independent subprocesses;
- minimal correction CODE `70587508bb8afc2ebe876cebd4304c369be7ed76` adds one tenant/master-scoped OS-backed ownership guard (`msvcrt.locking` on Windows, `flock` on Ubuntu) and exact `taskId/inputHash/batchVersion` mutable-state fencing;
- no DB, Redis, second queue, second state store or renderer/DAM/master/authority/publication rewrite was introduced;
- exact CODE Actions `35109488260`: Windows **1130 PASS**, Ubuntu **1126 PASS + 4 Windows-only skips**;
- exact DOCS/head `7c01e0306db106cee146e70f04e8f7b6c8e452bd`, Actions `35112516774`: Windows and Ubuntu SUCCESS with the same test totals and exact checkout SHA;
- six A–F process cases and two isolation cases use independent child processes on both OSes;
- actual process death releases ownership and explicit resubmit works without deleting `owner.lock`;
- stale callback/finally writes cannot overwrite a newer exact task;
- clean local real-Blender double-submit trial produced exactly one winner render and a `PreviewBusy` loser with zero writes/request/publication/render entry;
- clean REAL acceptance `d837bbaf-6bce-438e-aaae-f2fb2db65ec5`: Blender 5.2.1 LTS / OptiX, `usedMock=false`, two synthetic static variants, artifact/reopen/restart/download and retained 30 + 21 + 35 matrices PASS;
- hard-kill orphan atomic temp cleanup remains **PARTIAL / NOT SCAVENGED**;
- `inputTruth=SYNTHETIC_STATIC_FIXTURE`; `physicalProductGeometryTruth=false`; `physicalPrintValidated=false`; `manufacturingReady=false`; `globalProductionReady=false`.

Classification remains strict:

- publication / authority / fencing logic = **REAL_LOGIC**;
- independent process contention = **REAL_PROCESS_CONCURRENCY**;
- actual terminate/restart = **REAL_PROCESS_RECOVERY**;
- actual OS ownership/Windows handle behavior = **REAL_OS_IO** where directly exercised;
- winning Blender path only = **REAL_RENDER**;
- ordinary CI pytest/artifact path = **MOCK / regression**;
- hard-kill temp cleanup = **PARTIAL / NOT SCAVENGED** until this round proves otherwise;
- physical CAD/print/manufacturing/global readiness = **BLOCKED / false**.

Do not rewrite existing architecture. Round 7 is a narrow crash-debris hygiene gate only. Do not add product features and do not open a new PR.

---

## 1. Why Round 7 exists

`atomic_json()` writes a same-directory temporary file using the existing naming contract and atomically replaces the destination. Normal exceptions attempt to remove the owned temp file, but an external hard kill can terminate the process before Python cleanup runs. Round 5/6 deliberately preserved this fact as `PARTIAL_NOT_SCAVENGED`.

The remaining gap is operational hygiene, not publication authority: after a hard kill, a `state.json.<token>.tmp` owned by the dead writer can remain in the tenant/master workspace. A fresh owner must never interpret that temp file as state, request, receipt, publication or product truth.

This round must prove whether a narrowly scoped, ownership-safe cleanup can remove only dead **outer-state atomic temp debris** without touching any immutable or unknown file.

Do **not** turn this into a repository-wide temp cleaner, generic GC, age-based sweeper, queue rewrite or storage migration.

---

## 2. Scope boundary

Round 7 scope is only the RecipePreviewService outer mutable state destination in the exact tenant/master workspace:

- authoritative destination: `state.json`;
- candidate debris: only the exact temp naming contract generated for that destination by current `atomic_json()`;
- cleanup may run only after the caller successfully holds the existing `PreviewOwnership` for that exact workspace;
- cleanup must occur before the fresh owner performs a new outer-state write.

Out of scope and forbidden to scavenge in this round:

- `owner.lock`;
- `batches/**/request.json`;
- row receipts / `terminal.json`;
- `generations/**/published.json`;
- artifact files, `.blend`, images, DAM files;
- `latest.json` or publication pointers;
- authority snapshots/declarations;
- arbitrary `*.tmp` elsewhere;
- unknown files that merely look old;
- another tenant/master workspace.

Global atomic-temp cleanup remains unclaimed unless separately proved in a later gate.

---

## 3. Required cleanup invariants

A valid correction must satisfy all of the following:

1. cleanup requires a **live held `PreviewOwnership`** for the exact tenant/master workspace;
2. a process that cannot acquire ownership must perform **zero cleanup**;
3. candidate matching must be derived from the actual `atomic_json(state.json, ...)` naming contract — exact destination basename + exact token shape + `.tmp`; do not use a broad `*.tmp` glob as authority;
4. candidate must be a direct child of the exact workspace and must not escape by path normalization;
5. never delete `state.json` itself;
6. never delete `owner.lock`, immutable request/receipt/publication files, assets or unknown sentinels;
7. do not use file age/mtime alone to decide ownership or staleness;
8. cleanup must not read orphan temp bytes and promote them into current state;
9. cleanup must not auto-replay a batch;
10. cleanup must not grant `available=true`, success, physical truth or publication authority;
11. if a candidate cannot be safely removed because of permission/locking/type ambiguity, fail closed before a new mutable-state write rather than silently reporting clean success;
12. multiple exact orphan state-temp files may be cleaned deterministically after ownership is acquired;
13. a live writer's temp file must never be removed by a competitor, because the competitor must fail ownership acquisition first;
14. cleanup result must be observable in tests/log evidence but must not become product state or publication metadata.

No PID file, wall-clock lease, stale timeout or lock-file deletion is authorized.

---

## 4. Baseline hard-kill reproduction on exact accepted CODE

First use exact accepted CODE `70587508bb8afc2ebe876cebd4304c369be7ed76` unchanged.

Build a **test-only real subprocess harness** that pauses a child inside the real outer `state.json` atomic-write path after its same-directory temp file exists but before successful replace/cleanup. Kill that child externally with actual process termination.

Do not substitute a raised exception for the baseline hard kill. Do not add a production crash API.

Record:

- child PID;
- workspace path;
- exact destination path;
- exact temp filename(s);
- temp SHA/size if readable after death;
- pre-kill authoritative `state.json` SHA/bytes or explicit absence;
- post-kill authoritative `state.json` SHA/bytes or explicit absence;
- request/receipt/publication inventory before and after;
- `owner.lock` persistence;
- fresh-process status/submit result;
- whether any cleanup occurred on accepted CODE.

The expected accepted-CODE baseline is that the dead writer releases OS ownership but one or more owned state temp files may remain. Preserve that baseline evidence before correction.

---

## 5. Required real-process cases

### Case A — kill before first queued-state replace

Pause after `state.json.<token>.tmp` exists but before the initial queued `state.json` replace. Hard-kill the child.

Required post-fix result:

- ownership is released by process death;
- authoritative `state.json` remains absent if it was absent before;
- exact orphan state temp is removed only by a fresh process after it acquires ownership;
- no request, receipt, generation or publication is fabricated;
- explicit resubmit can proceed normally.

### Case B — kill while replacing an existing state

Start with a valid prior `state.json`, pause the dead writer after its temp is complete but before replace, then kill it.

Required:

- prior `state.json` bytes remain exact and valid;
- orphan temp is cleaned after fresh ownership acquisition;
- orphan temp contents are never adopted as state;
- explicit subsequent state transition uses the existing normal path.

### Case C — Windows delete-sharing / retry hard kill

On Windows, reproduce the existing real destination sharing contention used by Round 4/5: hold a real delete-sharing-conflicting handle so `atomic_json()` enters its bounded retry/backoff, then terminate the writer while its owned temp exists.

Required:

- destination old JSON remains valid;
- process death releases the writer-owned handles;
- after the external destination lock is released and fresh `PreviewOwnership` is acquired, exact orphan state temp is removable;
- no wildcard cleanup and no deletion of another-writer sentinel;
- no claim about arbitrary ACL/disk/power-loss durability.

On Ubuntu, use the corresponding hard-kill temp-exists case; do not fabricate Windows semantics there.

### Case D — live owner protects its temp from a competitor

Keep process A alive, owning the workspace and paused with a valid state temp file present. Process B calls status/submit concurrently.

Required:

- B receives busy/read-only live-owner behavior according to existing Round 6 semantics;
- B performs zero scavenging and zero writes;
- A's temp remains until A completes or dies;
- no second render owner.

### Case E — multiple exact orphans + unrelated sentinels

After dead ownership is released, place multiple files matching the exact state-temp naming contract plus unrelated files:

- unknown `.tmp` names;
- similarly prefixed but invalid-token names;
- `owner.lock`;
- request/receipt/publication sentinels;
- nested temp-like files outside direct workspace root.

Required:

- clean only exact eligible dead state-temp candidates;
- every unrelated/unknown/immutable sentinel remains byte-identical;
- cleanup never descends recursively.

### Case F — cleanup failure is fail-closed

Make one exact candidate undeletable/locked/permission-denied in a controlled OS-specific test.

Required:

- cleanup failure is surfaced deterministically;
- no new `state.json` write occurs after ambiguous cleanup failure;
- no success/available/readiness promotion occurs;
- once the external lock/permission condition is removed, a fresh retry can clean and continue.

---

## 6. Minimal correction constraints

If the baseline confirms the orphan behavior, implement only the smallest helper necessary.

Preferred shape:

- a tiny helper near the existing atomic-write/service code that enumerates **only** temp names belonging to the exact `state.json` target;
- require the caller to pass/hold the already-existing `PreviewOwnership` and verify `owner.held`;
- call it only at a bounded recovery/submit point after ownership acquisition and before a fresh outer-state write;
- no periodic background sweeper;
- no repository startup scan;
- no database/index/registry of temp files;
- no deletion based only on age;
- no change to `_once()` immutable semantics;
- no change to publication verification;
- no change to authority, renderer, DAM, Product Master or batch identity.

Do not broaden `atomic_json()` into a storage subsystem. Keep the helper easy to audit.

If the exact current token generated by `new_id()[:8]` is used for matching, validate the token using the actual generator contract rather than accepting arbitrary basename suffixes.

---

## 7. Required regressions

Add focused tests for:

- exact state-temp candidate recognition;
- reject wrong basename / wrong token shape / nested path / directory candidate;
- require held ownership;
- no cleanup when `PreviewBusy`;
- absent destination + orphan cleanup;
- existing valid destination + orphan cleanup;
- multiple exact orphan cleanup;
- unknown temp/sentinel preservation;
- immutable request/receipt/publication preservation;
- cleanup deletion failure fail-closed;
- retry after external lock release;
- live-owner competitor cannot scavenge;
- no automatic replay;
- no regression to Round 6 A–F concurrency/isolation;
- no regression to Round 5 A/A_PROGRESS/B/C/D recovery;
- no regression to 30 + 21 + 35 matrices;
- no regression to Windows bounded replace retry semantics.

Classification:

- pure filename/helper tests = **MOCK / unit regression**;
- actual killed child leaving a temp = **REAL_PROCESS_RECOVERY / REAL_OS_IO**;
- actual Windows delete-sharing handle = **REAL_OS_IO**;
- independent live-owner/competitor case = **REAL_PROCESS_CONCURRENCY**;
- successful cleanup logic itself = **REAL_LOGIC**;
- none of these are renderer/physical/manufacturing Production Ready evidence.

---

## 8. Exact CODE gate

After baseline capture and minimal correction:

1. freeze one new CODE SHA on existing PR #15;
2. run exact CODE GitHub Actions;
3. Ubuntu SUCCESS;
4. Windows SUCCESS;
5. actual checkout SHA must equal the CODE SHA;
6. report full test totals per OS;
7. report focused Round 7 counts and which cases use actual child-process termination / real OS handles;
8. preserve accepted-CODE baseline orphan evidence;
9. if CI fails, fix only the failing issue and repeat on a new exact CODE SHA.

CI remains non-Blender regression evidence.

---

## 9. Clean retained REAL acceptance

Only after exact CODE dual-platform SUCCESS:

- rerun the existing clean exact-CODE product-variant REAL acceptance;
- Blender 5.2.1 LTS;
- OptiX / `realOptix=true`;
- `usedMock=false`;
- at least two synthetic/reference variants;
- exact artifact SHA/bytes and `.blend` reopen;
- restart/history/download verification;
- retained 30 + 21 + 35 matrices PASS;
- retained Round 5 recovery PASS;
- retained Round 6 A–F ownership/fencing PASS;
- run at least one killed outer-state writer + fresh cleanup/recovery case on the clean CODE tree.

A Blender render is not required inside every cleanup case. Do not label a cleanup-only case REAL_RENDER.

Truth boundary after a successful Round 7 may become:

- RecipePreviewService outer-state dead-temp cleanup = **REAL_LOGIC + REAL_PROCESS_RECOVERY / REAL_OS_IO** within this exact local-workspace scope;
- generic repository/global atomic temp cleanup = still **UNCLAIMED / PARTIAL**;
- physical geometry/print/manufacturing/global readiness = still **false / BLOCKED**.

---

## 10. DOCS closure

Only after CODE CI + required real-process cleanup cases + retained REAL acceptance PASS:

- update existing `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md` and `.json`;
- record accepted-CODE baseline orphan temp evidence;
- record exact candidate-matching rule;
- record cleanup call site and ownership prerequisite;
- include Cases A–F results;
- prove sentinel/immutable files byte-identical;
- state explicitly that cleanup does not confer publication/physical truth;
- state explicitly that cleanup is scoped only to RecipePreviewService outer `state.json` temp debris;
- keep generic/global cleanup unclaimed;
- commit DOCS after evidence exists;
- run exact DOCS SHA Ubuntu + Windows CI;
- both must be SUCCESS before `READY_FOR_RE_GATE`.

Do not rewrite `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md` or `CABINET_REAL_ACCEPTANCE.md` merely to make historical docs look current. Update them only if their declared truth actually changes.

---

## 11. Existing gates stay frozen

- PR #15 remains DRAFT / OPEN on PR #12; **no merge, retarget, rebase-to-main or cherry-pick**.
- PR #16 remains **FROZEN DRAFT**.
- PR #14 remains unmerged and without merge authorization.
- Issue #6 remains `BLOCKED_PR14_NOT_ON_MAIN`.
- PR #13 Round 3B remains blocked; no articulation authority copy and no DOOR_OPEN promotion.
- No live H3/LTX/Vision/CNC/LASER/PLC work.
- `MERGE_AUTHORIZED=false`.

---

## 12. Final handoff

When all gates pass, leave one concise Issue #1 `READY_FOR_RE_GATE` handoff containing:

- this instruction SHA;
- exact accepted baseline and post-fix CODE SHA;
- exact CODE CI run/jobs and per-OS test totals;
- baseline orphan temp filenames/hashes and authoritative state before/after kill;
- Cases A–F results with real PIDs where applicable;
- exact cleanup candidate rule and cleanup call site;
- proof ownership is required before cleanup;
- proof live competitor performs zero cleanup;
- proof unknown temp/owner.lock/immutable sentinels remain byte-identical;
- cleanup-failure fail-closed result;
- retained Round 5 and Round 6 matrices;
- clean REAL acceptance ID and Blender/OptiX/usedMock fields;
- exact DOCS SHA + DOCS CI run/jobs;
- REAL_LOGIC / REAL_PROCESS_CONCURRENCY / REAL_PROCESS_RECOVERY / REAL_OS_IO / REAL_RENDER / MOCK / PARTIAL / BLOCKED matrix;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`;
- PR #16 frozen / Issue #6 blocked / `MERGE_AUTHORIZED=false`.

Then STOP for Supervisor Re-Gate. Do not start Round 8 automatically.
