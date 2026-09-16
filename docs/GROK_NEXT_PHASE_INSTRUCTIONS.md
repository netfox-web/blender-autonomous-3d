# Development Agent 下一輪指令：PR #15 Round 5 — Abrupt Process Recovery / Commit-Point Gate

> Supervisor checkpoint: 2026-09-16
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Reviewed CODE: `65299811abd076645edbe1cd0777b12b63968c0b`
> Reviewed DOCS / PR head: `c9deeeaeab3411c4fc66e03f7a6c54980ee07e52`
> Decision: **Round 4 ACCEPT WITH SCOPE / GO Round 5**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Round 4 Re-Gate result

Round 4 Windows Durable Atomic Persistence Gate is accepted within its declared scope.

Accepted evidence:

- pre-fix exact CODE `6b118898ebd430592e293c04c5cabe4bc30f37d8` reproduced an actual Windows delete-sharing contention with a real `CreateFileW` handle: old `atomic_json()` raised WinError 5 immediately, old JSON stayed valid, and an orphan temp remained;
- fixed CODE `65299811abd076645edbe1cd0777b12b63968c0b` keeps same-directory atomic replace and adds bounded Windows-only contention handling;
- retry policy is bounded to 8 attempts with 25/50/100/200/200/200/200 ms sleeps; Windows 32/33 are retryable and WinError 5 is retryable only when the independent DELETE-access probe shows 32/33;
- unrelated ACL/permission failures, ENOSPC, invalid paths, serialization/encoding/write failures and other I/O remain fail-closed;
- CODE Actions `35088102902` is SUCCESS on exact CODE: Windows 1099 PASS; Ubuntu 1096 PASS + 3 Windows-only skips;
- three Windows tests use actual OS handles and may be classified **REAL_OS_IO**; the rest of pytest/CI remains MOCK/unit regression, not Production Ready;
- clean exact-CODE REAL Blender acceptance `2b0d86f8-a738-40f5-8420-fab8faccdb8b`: Blender 5.2.1 LTS / OptiX, `realOptix=true`, `usedMock=false`, two synthetic static variants;
- retained 30 durable-lineage + 21 authority + 35 serialized-type/restoration outcomes PASS;
- DOCS/head `c9deeeaeab3411c4fc66e03f7a6c54980ee07e52`, Actions `35090170366`, Ubuntu + Windows SUCCESS;
- input truth remains `SYNTHETIC_STATIC_FIXTURE`; physical geometry/print/manufacturing/global readiness remain false/BLOCKED.

No architecture rewrite is authorized. Round 5 is a recovery/commit-point hardening gate only. Do not add product features. Do not open a new PR.

---

## 1. Goal: prove actual abrupt-process recovery semantics

Round 4 proved bounded handling of a live Windows replace lock while the Python process stays alive. It does **not** prove what happens when the worker/service process is terminated at commit boundaries.

Round 5 must exercise the existing batch path with an actual child process and abrupt termination/restart. The purpose is to prove that immutable request/row/terminal facts plus the publication verifier prevent false success, replay and lineage drift when mutable progress is stale.

Use the exact accepted CODE `65299811abd076645edbe1cd0777b12b63968c0b` as the baseline before any correction.

Do not claim power-loss/fsync durability. This gate is about **process termination and restart on the same local filesystem**, not disk-controller, filesystem-journal, network filesystem or hostile-admin durability.

---

## 2. Required commit-point map

Before modifying code, document the exact existing write/authority sequence for a batch:

1. write-once `request.json`;
2. mutable batch `<batchId>.json` progress;
3. per-row generation/publication verification;
4. write-once row receipt `<index>.json`;
5. mutable progress update;
6. write-once `terminal.json`;
7. outer Recipe service `state.json` transition.

For each file, state whether it is:

- immutable authority;
- mutable operational state;
- publication authority;
- recoverable cache/progress only.

Do not promote mutable progress to authority.

---

## 3. Real subprocess interruption harness

Create a focused test/harness using a **real subprocess / child Python process**. A monkeypatch-only exception is insufficient as the sole evidence.

Do not add a production API that lets callers fake a crash. Test orchestration may use a dedicated test script/helper that drives the existing functions and external process termination.

Required interruption windows:

### Case A — request committed, no row terminal receipt

Terminate after the write-once batch request exists but before a row has a terminal receipt.

After a fresh process restart, verify:

- request identity remains exact and parse-valid;
- no row is reported succeeded/available merely from mutable progress;
- incomplete work is surfaced as interrupted/cancelled according to existing semantics;
- no automatic render replay occurs;
- user must explicitly resubmit/requeue unfinished work.

### Case B — published row + row receipt committed, mutable progress stale

Terminate after one row has a valid published generation and write-once row receipt, but before the following mutable batch progress write is known to have committed.

After restart, verify:

- the exact completed row can be recovered from immutable receipt + publication verifier;
- availability is granted only if exact generation / selection / authority / publication lineage re-verifies;
- stale mutable progress cannot hide, invent or alter the completed immutable fact;
- unfinished rows remain non-available;
- no duplicate generation or duplicate row receipt is created.

### Case C — all row receipts committed, no successful terminal batch receipt

Terminate after all row terminal receipts exist but before a successful `terminal.json` is committed.

After restart, verify:

- outer batch must **not** become successful merely because every row receipt exists;
- already valid row outputs may remain individually recoverable/available if existing policy permits;
- outer state remains interrupted/failed until a valid terminal commit point exists;
- no API reports a false successful outer task.

### Case D — termination during Windows atomic replace retry/backoff

On Windows, use a real destination handle that denies DELETE sharing so the child enters the real Round 4 retry path, then terminate the child while it is in the bounded retry window.

After restart, record the actual filesystem state:

- destination must remain parse-valid and represent either the old committed value or a fully committed new value; never partial JSON;
- any orphan owned temp created by abrupt termination must **not** be treated as committed state;
- a later valid write must still succeed;
- do not silently delete another process's possible active temp.

If an orphan temp remains after hard termination, report it explicitly. Do not claim hard-kill temp cleanup unless it is actually implemented and safely proven.

---

## 4. Fail-closed correction rule

First run the interruption matrix on the accepted CODE unchanged.

If every case already behaves safely, do not invent a code change merely to create a new commit. Add only the regression harness/evidence needed to freeze the behavior.

If a fail-open is found, make the smallest correction inside the existing architecture. Examples of unacceptable behavior that require correction:

- outer `succeeded` without exact successful terminal authority;
- row `available=true` based only on mutable progress;
- restart automatically replays an incomplete generation;
- a stale progress row overrides an immutable receipt;
- duplicate row receipt/publication is silently accepted;
- a `.tmp` file is loaded as authoritative state;
- malformed/torn destination JSON is treated as success;
- process restart loses already committed immutable row evidence and fabricates failure/success instead of re-verifying it.

Do not add a second queue, second batch state store, database migration, distributed lock service or new persistence architecture.

---

## 5. Hard-kill temp policy

Round 4 only guarantees cleanup on normal success or caught terminal failure. An OS-level process kill can bypass Python `finally`.

For Round 5:

- stale `.tmp` files are **not authority**;
- loader paths must ignore them;
- do not wildcard-delete temps merely because they exist;
- do not delete a temp that could belong to another live writer;
- if you implement stale-temp scavenging, it must have an independently safe ownership/staleness rule and focused concurrent-writer tests;
- otherwise leave hard-kill orphan cleanup explicitly **PARTIAL** and document it. Safe non-corruption is required; zero orphan files after SIGKILL/TerminateProcess is not required unless safely implemented.

---

## 6. Regression requirements

All accepted Round 4 behavior must remain green:

- 1099 existing tests retained;
- 3 real Windows handle-lock integrations retained;
- 30 durable-lineage outcomes retained;
- 21 authority outcomes retained;
- 35 serialized-type/restoration outcomes retained;
- `MEASURED_OR_CAD_AUTHORITY` remains rejected without reviewed evidence;
- fixture/reference inputs cannot become physical truth;
- `_once()` immutable request/row/terminal semantics remain exclusive;
- no PR #16 scene code or PR #13/#14 articulation is imported.

Add focused recovery tests for Cases A–D. Clearly label:

- normal unit/fault-injection tests = MOCK/unit regression;
- actual Windows handle sharing test = REAL_OS_IO;
- actual child-process terminate/restart test = **REAL_PROCESS_RECOVERY**;
- Blender acceptance = REAL_RENDER only when `usedMock=false` and exact evidence is present.

`REAL_PROCESS_RECOVERY` does not mean power-loss or Production Ready.

---

## 7. Exact CODE gate

After the harness and any minimal correction:

1. freeze a new CODE SHA on existing PR #15;
2. run exact CODE GitHub Actions;
3. Ubuntu SUCCESS;
4. Windows SUCCESS;
5. actual checkout SHA must equal the CODE SHA;
6. report total tests and focused recovery counts;
7. identify which process-kill tests ran on which OS;
8. preserve exact failure evidence if the baseline exposes a bug before correction.

If CI fails, fix only the failure and repeat on a new exact CODE SHA.

CI remains non-Blender regression evidence.

---

## 8. Clean REAL acceptance after process-recovery gate

After exact CODE dual-platform SUCCESS, rerun the existing product-variant batch REAL acceptance on a clean exact-CODE tree. Reuse the existing runner; do not build a second acceptance architecture.

Required:

- Blender 5.2.1 LTS;
- OptiX / `realOptix=true`;
- `usedMock=false`;
- at least two synthetic/reference variants;
- exact artifact SHA/bytes and `.blend` reopen;
- restart/history/download verification;
- 30 + 21 + 35 matrices still PASS;
- new process-recovery outcomes summarized separately;
- no persistence error is swallowed;
- if an interruption case is simulated inside Blender acceptance, label it simulated; do not call it a killed render unless the renderer process was actually terminated.

Truth boundary remains:

- batch/authority/publication verifier = **REAL_LOGIC**;
- Windows lock integration = **REAL_OS_IO**;
- child-process termination/restart harness = **REAL_PROCESS_RECOVERY**;
- Blender = **REAL_RENDER**;
- geometry/input = **SYNTHETIC / REFERENCE**;
- normal GitHub pytest = **MOCK/unit regression**;
- hard-kill orphan cleanup may remain **PARTIAL** if not safely implemented;
- physical geometry authority = **BLOCKED / false**;
- physical print = **BLOCKED / false**;
- manufacturing readiness = **BLOCKED / false**;
- global Production Ready = **false**.

---

## 9. DOCS closure

Only after CODE CI + process-recovery evidence + clean REAL Blender acceptance PASS:

- update existing `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md` and `.json`;
- record baseline interruption results and any minimal correction;
- include a commit-point authority table;
- include Case A/B/C/D outcomes;
- explicitly distinguish graceful exception cleanup from hard-process-kill behavior;
- explicitly record whether hard-kill orphan temps remain and why they are or are not safe;
- commit DOCS after evidence exists;
- run exact DOCS SHA Ubuntu + Windows CI;
- both must be SUCCESS before `READY_FOR_RE_GATE`.

Do not rewrite `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md` or `CABINET_REAL_ACCEPTANCE.md` merely to make historical docs look current. Update them only if their actual declared truth changes.

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
- commit-point authority map;
- Case A/B/C/D actual results;
- child-process termination method and OS;
- real Windows lock result;
- hard-kill temp behavior;
- total/focused test counts;
- clean REAL acceptance ID and Blender/OptiX/usedMock fields;
- retained 30 + 21 + 35 matrices;
- exact DOCS SHA + DOCS CI run/jobs;
- REAL_LOGIC / REAL_OS_IO / REAL_PROCESS_RECOVERY / REAL_RENDER / MOCK / PARTIAL / BLOCKED matrix;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`;
- PR #16 frozen / Issue #6 blocked / `MERGE_AUTHORIZED=false`.

Then STOP for Supervisor Re-Gate. Do not start Round 6 automatically.
