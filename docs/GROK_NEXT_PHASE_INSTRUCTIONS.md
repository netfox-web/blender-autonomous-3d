# Development Agent 下一輪指令：PR #15 Round 6 — Cross-Process Single-Writer / Duplicate Submit Ownership Gate

> Supervisor checkpoint: 2026-09-16
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Accepted CODE: `f5ac3a6773d99f30709a84dc9adb97231ca53ba9`
> Accepted DOCS / PR head: `0950a88bd0655c7b492999c17123f1eb090af271`
> Decision: **Round 5 ACCEPT WITH SCOPE / GO Round 6**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Round 5 Re-Gate result

Round 5 Abrupt Process Recovery / Commit-Point Gate is accepted within its declared scope.

Accepted evidence:

- unchanged baseline CODE `65299811abd076645edbe1cd0777b12b63968c0b` reproduced the real request-committed / initial-progress-missing recovery gap as HTTP 422, without false success or replay;
- minimal correction CODE `f5ac3a6773d99f30709a84dc9adb97231ca53ba9` reconstructs only an in-memory disposable progress view when the exact-bound outer state is failed/cancelled and the progress file is absent;
- immutable request / row receipts / terminal receipt plus the existing publication verifier remain authority; mutable progress and latest pointers are not publication authority;
- CODE Actions `35094237439` is SUCCESS on exact CODE: Windows **1109 PASS**, Ubuntu **1105 PASS + 4 Windows-only skips**;
- actual subprocess termination/restart cases A / A_PROGRESS / B / C run on both OSes; Windows Case D uses a real delete-sharing handle and actual TerminateProcess;
- subprocess kill/restart may be classified **REAL_PROCESS_RECOVERY**; Windows real sharing-handle behavior may be classified **REAL_OS_IO**; CI publication/artifact validation remains MOCK where Blender is not used;
- clean exact-CODE REAL Blender acceptance `5588ea74-2db7-47b4-b8d4-9ce7cec7d828`: Blender 5.2.1 LTS / OptiX, `realOptix=true`, `usedMock=false`, two synthetic static variants, `.blend` reopen and publication verification PASS;
- retained 30 durable-lineage + 21 authority + 35 serialized-type/restoration matrices PASS;
- DOCS/head `0950a88bd0655c7b492999c17123f1eb090af271`, Actions `35096217724`, Ubuntu + Windows SUCCESS;
- hard-kill owned temp cleanup remains **PARTIAL / NOT SCAVENGED** and is not authority;
- `inputTruth=SYNTHETIC_STATIC_FIXTURE`; `physicalProductGeometryTruth=false`; `physicalPrintValidated=false`; `manufacturingReady=false`; `globalProductionReady=false`.

No architecture rewrite is authorized. Round 6 is only a concurrency / ownership / stale-writer hardening gate. Do not add product features. Do not open a new PR.

---

## 1. Why Round 6 exists

Round 5 proved one process can be killed and a fresh process can recover safely. It did **not** prove that two independent service processes sharing the same local storage cannot both accept work for the same `(tenant, master)` at the same time.

Current `RecipePreviewService.tasks` and `RLock` are process-local. The production state file is shared filesystem state. Therefore Round 6 must explicitly test simultaneous independent processes and stale-writer races before this batch path can be considered process-concurrency-safe.

Do not assume the current implementation is unsafe; prove the behavior first on exact accepted CODE. If it is already fail-closed, freeze that behavior with tests. If a race is reproduced, make only the smallest correction needed inside the existing queue/service architecture.

This gate is **not** distributed-cluster certification, network-filesystem certification, hostile-admin protection or global Production Ready.

---

## 2. Required ownership invariants

For one `(tenantId, masterId)` shared local workspace:

1. at most one active RecipePreviewService generation owner may execute at a time;
2. process-local `tasks` cannot be the only exclusivity boundary;
3. a loser in a simultaneous submit race must fail before it can become a second active writer/render owner;
4. loser must not overwrite `state.json`, request, progress, row receipt, terminal receipt, publication or latest pointer belonging to the winner;
5. winner identity must remain exact across `taskId`, input hash, batch request, deterministic rows and outer state;
6. a stale/older worker must never overwrite outer state for a newer task;
7. process death must not create a permanent ownership deadlock;
8. immutable `_once()` request/row/terminal semantics remain unchanged and exclusive;
9. mutable progress remains non-authoritative;
10. existing publication verifier remains the only route to `available=true`.

Do not promote an owner/lock file into product truth or publication authority.

---

## 3. Baseline real cross-process race harness

First run exact accepted CODE `f5ac3a6773d99f30709a84dc9adb97231ca53ba9` unchanged.

Build a **test-only real subprocess harness** using two independent Python processes / service instances sharing the same exact root. Synchronize them with a parent barrier so both attempt the critical submit/ownership window concurrently.

A thread-only test inside one service instance is insufficient as the sole evidence.

Do not add a production crash/race API.

Record for every case:

- both PIDs;
- exact start barrier / release time;
- returned task IDs or deterministic conflict errors;
- state file bytes/hash after race;
- request anchors created;
- generation directories created;
- row/terminal receipts created;
- publication/latest pointers created;
- whether any render function was entered by each process;
- final recover/read API result from a fresh third process.

Preserve failing baseline evidence before correction.

---

## 4. Required race cases

### Case A — simultaneous identical batch submit

Two independent processes submit the exact same tenant/master/revision/draft at the same barrier.

Required safe result:

- exactly one active owner/winner;
- exactly one task becomes queued/running;
- loser receives deterministic busy/conflict/fail-closed result;
- loser performs no render and creates no second batch request/publication;
- outer `state.json` binds to the winner only;
- after completion, a fresh process sees one coherent result set.

If both renders run, both task IDs become active, or winner state can be replaced by the loser, baseline is a real fail-open.

### Case B — simultaneous different batch submit

Two independent processes submit different valid batch drafts for the same tenant/master at the same barrier.

Required safe result:

- exactly one winner;
- state/inputHash/taskId/request lineage all match the same winner;
- loser cannot partially publish its own draft or overwrite winner state;
- there is no mixed lineage where state belongs to draft A and request/progress/publication belongs to draft B.

### Case C — owner process dies before immutable request commit

After ownership has been acquired but before `request.json` is committed, hard-kill the winning process.

Required safe result:

- OS/process ownership mechanism releases automatically or is safely recoverable;
- a fresh process can submit new work without manual file deletion;
- no stale owner marker is treated as authority;
- no request/row/terminal fact is fabricated;
- no automatic replay occurs.

Do not use wall-clock-only stale lock deletion as the sole safety rule.

### Case D — owner process dies after request commit / while generation is active

Hard-kill after the existing Round 5 request/progress boundary while a competing process tries to submit the same tenant/master.

Required safe result:

- competitor cannot silently replace the active task while the old task is still legitimately active;
- after interruption is recognized using existing semantics, explicit operator resubmit can create a new task;
- old immutable receipts/publications remain historical facts and cannot be relabeled as the new task;
- no automatic replay.

### Case E — stale writer versus newer task fencing

Force the older task to reach a delayed final-state write while a newer task has already legitimately acquired ownership after the old task became terminal/interrupted.

Required safe result:

- old task/finally block cannot overwrite `state.json` for the newer task;
- every mutable outer-state write must be fenced by the exact task identity it owns;
- stale callbacks / `on_job` / finally writes from task A cannot mutate task B state;
- fresh API view remains internally consistent.

### Case F — cancel versus submit race

Race cancellation of the active task against a second process attempting a new submit.

Required safe result:

- no overlapping active generation owners;
- new task may start only after the old task is safely terminal/ownership-released;
- cancelled task cannot later write `succeeded` over the new task;
- completed immutable row results from the cancelled task remain individually valid only through the existing publication verifier.

---

## 5. Correction constraints

If the baseline exposes a race, make the smallest correction possible.

Allowed direction, if needed:

- an OS-backed local advisory ownership guard or equivalent minimal local single-writer primitive around the existing service lifecycle;
- exact `taskId` fencing before mutable outer-state writes;
- reuse the existing state/request/receipt/publication structure.

Any new local guard must:

- work on Ubuntu and Windows;
- be scoped to the exact tenant/master workspace, not one global repository lock;
- release on process termination or have an independently safe recovery rule;
- never be interpreted as publication/product/physical authority;
- never require wildcard deletion of unknown temp/lock files;
- fail closed on lock acquisition/ownership ambiguity.

Forbidden:

- new database;
- Redis/distributed lock service;
- second queue;
- second batch state store;
- replacing RecipePreviewService architecture;
- changing DAM/renderer/master/authority/publication architecture;
- network filesystem / distributed cluster claims;
- importing PR #16 or PR #13/#14 code.

If an OS-specific primitive is used, keep a tiny compatibility wrapper and focused tests; do not build a lock framework.

---

## 6. Required regression / negative tests

Retain all Round 5 evidence and add focused tests for:

- same-payload double submit;
- different-payload double submit;
- loser cannot write outer state;
- loser cannot create request/progress/publication;
- stale `on_job` callback cannot overwrite newer task state;
- stale `_run` finally cannot overwrite newer task state;
- kill-before-request ownership release/recovery;
- kill-after-request + competitor submit;
- cancel/new-submit race;
- lock/ownership acquisition failure is surfaced, not swallowed;
- malformed owner metadata, if any is persisted, fails closed;
- cross-tenant and different-master operations remain independent and may proceed concurrently;
- no regression to `_once()` exclusive immutable writes;
- no regression to Round 5 A/A_PROGRESS/B/C/D process recovery;
- no regression to 30 + 21 + 35 matrices.

Classification:

- ordinary pytest/fault injection = **MOCK/unit regression**;
- independent child processes contending on same local workspace = **REAL_PROCESS_CONCURRENCY**;
- actual OS file/advisory lock semantics, if exercised = **REAL_OS_IO / REAL_PROCESS_CONCURRENCY**;
- Blender winner render = **REAL_RENDER** only with `usedMock=false`;
- none of the above means distributed Production Ready.

---

## 7. Exact CODE gate

After baseline reproduction and any minimal correction:

1. freeze a new CODE SHA on existing PR #15;
2. run exact CODE GitHub Actions;
3. Ubuntu SUCCESS;
4. Windows SUCCESS;
5. actual checkout SHA must equal CODE SHA;
6. report total tests and new race-focused counts;
7. report which race cases used real independent subprocesses on each OS;
8. preserve baseline fail evidence if a race was found;
9. if CI fails, fix only that failure and repeat on a new exact CODE SHA.

GitHub CI remains non-Blender regression evidence even when subprocess concurrency is real.

---

## 8. Clean REAL acceptance after concurrency gate

Only after exact CODE dual-platform SUCCESS, rerun the existing product-variant batch REAL acceptance on a clean exact-CODE tree.

Required retained evidence:

- Blender 5.2.1 LTS;
- OptiX / `realOptix=true`;
- `usedMock=false`;
- at least two synthetic/reference variants;
- exact artifact SHA/bytes and `.blend` reopen;
- restart/history/download verification;
- 30 + 21 + 35 matrices PASS;
- Round 5 process-recovery matrix still PASS.

Additionally run at least one **local real-Blender ownership race trial** for the same tenant/master with two independent submitter processes. It is sufficient for exactly one process to enter the real Blender generation while the loser fails closed. Record winner/loser PIDs, task ID, generation IDs and final publication lineage.

Do not call the loser path REAL_RENDER. Do not claim renderer concurrency capacity from this gate.

Truth boundary remains:

- durable batch / authority / publication = **REAL_LOGIC**;
- subprocess race ownership = **REAL_PROCESS_CONCURRENCY**;
- Round 5 kill/restart = **REAL_PROCESS_RECOVERY**;
- Windows lock behavior = **REAL_OS_IO** where actually exercised;
- Blender winning render = **REAL_RENDER**;
- geometry/input = **SYNTHETIC / REFERENCE**;
- normal GitHub pytest = **MOCK/unit regression**;
- hard-kill orphan cleanup remains **PARTIAL / NOT SCAVENGED** unless separately proven safely;
- physical geometry authority = **BLOCKED / false**;
- physical print = **BLOCKED / false**;
- manufacturing readiness = **BLOCKED / false**;
- global Production Ready = **false**.

---

## 9. DOCS closure

Only after CODE CI + cross-process race evidence + clean REAL Blender acceptance PASS:

- update existing `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md` and `.json`;
- record baseline race outcomes before correction;
- include ownership / fencing invariant table;
- include Cases A–F results;
- identify exactly which tests are real subprocess concurrency versus unit/fault injection;
- record winner/loser task IDs and whether any losing render/publication occurred;
- explicitly record process-death ownership release behavior;
- explicitly retain hard-kill orphan cleanup as PARTIAL unless safely proven otherwise;
- commit DOCS after evidence exists;
- run exact DOCS SHA Ubuntu + Windows CI;
- both must be SUCCESS before `READY_FOR_RE_GATE`.

Do not rewrite `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md` or `CABINET_REAL_ACCEPTANCE.md` merely to make historical docs look current. Update them only if their declared truth actually changes.

---

## 10. Existing gates stay frozen

- PR #15 remains DRAFT / OPEN on PR #12; **no merge, retarget, rebase-to-main or cherry-pick**.
- PR #16 remains **FROZEN DRAFT**.
- PR #14 remains unmerged and without merge authorization.
- Issue #6 remains `BLOCKED_PR14_NOT_ON_MAIN`.
- PR #13 Round 3B remains blocked; no articulation authority copy and no DOOR_OPEN promotion.
- No live H3/LTX/Vision/CNC/LASER/PLC work.
- `MERGE_AUTHORIZED=false`.

---

## 11. Final handoff

When all gates pass, leave one concise Issue #1 `READY_FOR_RE_GATE` handoff containing:

- this instruction SHA;
- exact baseline and post-fix CODE SHA(s);
- exact CODE CI run/jobs;
- Cases A–F real-process outcomes;
- ownership primitive / fencing rule actually used;
- winner/loser PIDs/task IDs and render-entry counts;
- process-death ownership release result;
- stale-writer/finally fencing result;
- total/focused test counts;
- retained Round 5 process recovery and 30 + 21 + 35 matrices;
- clean REAL acceptance ID and Blender/OptiX/usedMock fields;
- local real-Blender double-submit ownership trial result;
- exact DOCS SHA + DOCS CI run/jobs;
- REAL_LOGIC / REAL_PROCESS_CONCURRENCY / REAL_PROCESS_RECOVERY / REAL_OS_IO / REAL_RENDER / MOCK / PARTIAL / BLOCKED matrix;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`;
- PR #16 frozen / Issue #6 blocked / `MERGE_AUTHORIZED=false`.

Then STOP for Supervisor Re-Gate. Do not start Round 7 automatically.
