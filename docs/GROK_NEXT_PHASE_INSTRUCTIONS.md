# Development Agent 指令：PR #15 Round 9 — Durable Commit / File + Namespace Flush Gate

> Supervisor checkpoint: 2026-09-17
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 8 CODE: `8129309c45b1db566385305e0db5a03f23c64e33`
> Accepted Round 8 DOCS: `85ecad41da13bcd14140a7dd373fed4e09012a4f`
> Exact CODE Actions: `35147126655` — Ubuntu + Windows SUCCESS
> Exact DOCS Actions: `35149729964` — Ubuntu + Windows SUCCESS
> Clean REAL Blender acceptance: `ba4eaa0a-1e33-4e52-a2e5-061a3ffeec45`
> Decision: **ACCEPT WITH SCOPE — GO ROUND 9**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Supervisor review result

Round 8 evidence closure is accepted. The frozen implementation and evidence prove the scoped process/OS behavior required by the prior gate, without promoting Mock evidence to Production Ready.

Accepted classification:
- real child-process hard-kill/restart evidence: **REAL_PROCESS_RECOVERY**;
- real ownership/link/reparse/delete-sharing behavior: **REAL_OS_IO** where directly exercised;
- scoped write-once temp cleanup/fencing: **REAL_LOGIC**;
- CI render/artifact path under `FOX3D_MOCK_BLENDER=1`: **MOCK regression** only;
- clean Blender evidence with `usedMock=false`: **REAL_RENDER**, but still synthetic/static visual/runtime evidence;
- W2 final+temp same-file two-hardlink crash state: **PARTIAL / PRESERVED UNKNOWN** by design — preserve + fail closed, no auto-delete/adopt/replay;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`.

Do not rewrite queue/state/authority/publication/DAM/Renderer/Product Master/PreviewOwnership architecture.

---

# Round 9 goal

Round 5–8 established process-crash atomicity, single-writer ownership/fencing, strict serialized identity, and scoped crash-debris handling. Round 9 must now separate **process-crash atomicity** from **actual storage durability**.

The accepted persistence paths use temp files plus `os.replace()` / `os.link()` / `unlink()`. A Python close and a successful rename/link do not by themselves prove that file contents and namespace mutations survive a sudden OS/hardware power-loss event.

Round 9 must first audit the real commit points. Only after the gap is demonstrated may you add the smallest durability primitive possible.

**A subprocess hard kill is not proof of power-loss durability. Never label it that way.**

## 1. Frozen baseline

Start from exact accepted production CODE:

`8129309c45b1db566385305e0db5a03f23c64e33`

Retain all accepted behavior:
- `PreviewOwnership`;
- exact `taskId` / `inputHash` / `batchVersion` fencing;
- immutable `_once()` authority semantics;
- request / row receipt / terminal receipt / publication authority rules;
- W2 ambiguous hardlink preservation;
- scoped target-specific temp cleanup;
- no orphan adoption;
- no automatic replay;
- existing Windows sharing-violation fail-closed semantics.

Before production changes, capture baseline evidence.

---

## 2. Phase A — Prove the durability gap before fixing it

Build a focused Round 9 audit/repro harness around the actual persistence paths. Prefer real child processes and actual host filesystem behavior; pure monkeypatch-only evidence is not sufficient for the host-OS classification.

Audit at minimum:

### `src/fox3d/model_batches.py`
- `BatchStorage.atomic_json()`;
- `_once()`;
- immutable request / row receipt / terminal / publication writes that depend on these functions.

### `src/fox3d/recipe_3d.py`
- `atomic_write_json()` / `_atomic_json`;
- authority/state commit paths using those persistence semantics.

Record explicitly:
- whether the complete temp file receives an explicit durable host-OS file flush before `os.replace()` or `os.link()`;
- whether containing-directory / namespace synchronization is issued after rename/link/unlink where supported/required;
- exact Windows behavior;
- exact POSIX/Linux behavior;
- which guarantees are only process-crash atomicity;
- which guarantees, if any, are genuinely storage durability guarantees.

If accepted CODE has no explicit durable file flush and/or namespace durability operation, record that as the reproduced durability gap. Do not claim observed data loss unless a destructive crash actually demonstrated it.

Classification:
- child-process kill = **REAL_PROCESS_RECOVERY**;
- directly observed real OS flush/namespace operation = **REAL_OS_IO_FLUSH**;
- code-path audit showing a missing primitive = **REAL_LOGIC_AUDIT**;
- sudden hardware/power-cut survival = **BLOCKED** unless actually tested with a destructive harness.

---

## 3. Phase B — Minimal durable-commit primitive

Only if Phase A proves the gap, implement the smallest shared durability helper(s) needed by the existing persistence paths.

### File data durability
For a temp file that can become committed authority/state:
1. write complete bytes;
2. flush language/runtime buffering;
3. request the platform's durable file flush on the open file handle;
4. only after that succeeds, perform the existing namespace commit (`os.replace()` / `os.link()`).

A durable-flush failure must fail closed. Do not continue and later emit success.

### POSIX namespace durability
Where supported, synchronize the containing directory after the actual namespace mutation sufficiently to make the directory entry durable according to the platform contract.

Cover real commit sequences, not a disconnected helper:
- temp -> final `os.replace()`;
- write-once `os.link()` final creation;
- owned temp unlink where that deletion is part of a completed commit path.

Do not broaden cleanup or weaken W2 ambiguity handling.

### Windows durability
Use only a real Windows-supported file-handle flush mechanism that can be exercised on the current Windows runner.

Do not invent a fake directory-fsync equivalent. If durable directory/namespace flush cannot be safely guaranteed through the current surface, implement only what is real and explicitly classify the remaining guarantee **PARTIAL/BLOCKED**.

Retain current Windows sharing retry and fail-closed behavior.

### Forbidden architecture changes
Do not add:
- SQLite/PostgreSQL/DB journal;
- Redis;
- second queue;
- WAL subsystem;
- replacement object store;
- new replay engine;
- alternate authority model;
- renderer/DAM/Product Master redesign;
- broad `*.tmp` sweeps;
- mtime/PID stale heuristics;
- orphan adoption as authority.

---

## 4. Phase C — Required acceptance matrix

Use actual subprocesses/filesystem operations for process/OS cases. Fault injection may supplement them but cannot replace them.

### D1 — Durable temp, kill before replace
For atomic JSON:
- child fully writes and performs the real file durability primitive;
- terminate child before `os.replace()`;
- start a fresh process;
- no phantom final success;
- temp is not treated as authority;
- existing scoped recovery rules only.

### D2 — Namespace commit then kill before namespace sync hook
Create a deterministic test hook around the actual commit point:
- `os.replace()` or `os.link()` has occurred;
- child is killed before namespace durability hook completes;
- fresh process inspects resulting bytes/state;
- no automatic replay/adoption;
- report only observed process-crash behavior; do not call this a power-loss test.

### D3 — `_once()` link succeeded, temp remains
Preserve accepted Round 8 W2 behavior:
- final + temp same-file hardlinks may remain after interruption;
- `WRITE_ONCE_TEMP_AMBIGUOUS` / multilink path remains fail closed;
- do not delete/adopt either path merely to make the test pass;
- keep classification **PARTIAL / PRESERVED UNKNOWN** unless stronger evidence truly proves otherwise.

### D4 — Durable immutable authority + restart
After durable commit succeeds:
- terminate owner process;
- start fresh process;
- request / row receipt / terminal / publication authority reads consistently;
- no duplicate publication;
- no stale-writer overwrite;
- no implicit replay.

### D5 — Durable flush/sync failure
Force or inject a file durability failure and, where practical, a namespace-sync failure:
- operation fails closed;
- success receipt/publication is not emitted;
- existing immutable authority is not overwritten;
- caller is not silently repaired behind its back.

Injected/fake failures are **MOCK / FAULT_INJECTION_LOGIC**, not host durability evidence.

### D6 — Regression retention
Retain all accepted Round 5–8 gates, including:
- cross-process single-writer ownership;
- strict serialized identity (`true != 1`, absent != null);
- real Windows sharing-handle cases;
- hard-kill outer-state recovery;
- scoped Round 7 cleanup;
- Round 8 W1/W2/W3 behavior;
- publication/receipt authority;
- no duplicate publication.

---

## 5. Evidence classification rules

### REAL_OS_IO_FLUSH
Only an actually executed host-OS durable file flush / supported namespace synchronization on the target OS.

### REAL_PROCESS_RECOVERY
Only a real child process terminated and a fresh process recovering.

### REAL_RENDER
Only a clean Blender run with `usedMock=false` and real Blender runtime evidence.

### MOCK
GitHub CI render/artifact tests under `FOX3D_MOCK_BLENDER=1`, plus pure unit/fault-injection evidence.

### PARTIAL
Any guarantee covering only part of a platform/commit sequence, including Windows namespace durability if it cannot be safely proven.

### BLOCKED
Sudden power-loss / hardware-reset durability unless a real destructive power-loss harness is actually executed and captured.

Do not use labels such as `REAL_POWER_LOSS`, `POWER_LOSS_SAFE`, `CRASH_DURABLE`, or equivalent unless that exact failure mode was actually tested.

---

## 6. Clean REAL Blender acceptance

Because persistence production code will change if the durability gap is fixed, rerun clean real acceptance after final CODE SHA is frozen.

Required:
- trusted real runner;
- Blender version recorded;
- device/backend recorded;
- `usedMock=false`;
- generation/batch/task identifiers recorded;
- verifier results recorded;
- input source classified honestly.

Synthetic/static input remains acceptable for this regression gate but must be labeled as such. It does not establish physical product geometry, physical print, manufacturing readiness, or global Production Ready.

---

## 7. Evidence package

Update the existing truth package only:
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`;
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`.

Record:
- Round 9 baseline SHA;
- final CODE SHA;
- exact repro commands;
- D1–D6 outcome matrix;
- OS/platform for every real case;
- REAL/MOCK/PARTIAL/BLOCKED classification per case;
- exact file-flush / namespace-sync mechanism used per platform;
- unsupported durability guarantees marked PARTIAL/BLOCKED;
- clean REAL Blender run ID and truth boundary;
- exact CODE Actions run ID;
- exact DOCS SHA;
- exact DOCS Actions run ID.

Do **not** rewrite `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md`, or `CABINET_REAL_ACCEPTANCE.md` merely to make them look newer. Modify them only if an existing declared truth becomes factually false.

---

## 8. CI / Re-Gate protocol

1. Freeze final production CODE SHA.
2. Run exact CODE SHA CI on Ubuntu + Windows.
3. Both must be SUCCESS and check out the exact CODE SHA.
4. Run clean `usedMock=false` REAL Blender acceptance against final CODE SHA.
5. Publish Round 9 evidence only after evidence is complete.
6. Freeze exact DOCS SHA.
7. Run exact DOCS SHA CI on Ubuntu + Windows.
8. Both must be SUCCESS and check out the exact DOCS SHA.
9. Leave exactly one new `[GROK_PHASE_COMPLETE]` / `READY_FOR_RE_GATE` handoff on Issue #1 containing:
   - baseline SHA;
   - final CODE SHA;
   - CODE Actions run ID + Ubuntu/Windows results;
   - D1–D6 focused evidence summary;
   - clean REAL Blender run ID;
   - exact DOCS SHA;
   - DOCS Actions run ID + Ubuntu/Windows results;
   - REAL/MOCK/PARTIAL/BLOCKED matrix;
   - `MERGE_AUTHORIZED=false`.
10. STOP.

Do not begin Round 10 until Supervisor accepts Round 9.

---

## 9. Stop conditions

Stop and report **BLOCKED** instead of inventing evidence if:
- a platform does not expose the required durability primitive safely in the current architecture;
- Windows runner cannot exercise the selected real flush primitive;
- directory/namespace durability cannot be guaranteed on a supported platform;
- a durability-flush failure can still produce a success receipt/publication;
- any accepted Round 5–8 authority/fencing behavior regresses;
- exact CODE or DOCS CI is not green on both operating systems.

Frozen gates remain:
- PR #15 = DRAFT / OPEN / unmerged;
- PR #16 = FROZEN DRAFT;
- PR #13 / #14 unchanged;
- Issue #6 gate unchanged;
- no merge / retarget / rebase-to-main / cherry-pick;
- no live H3 / LTX / Vision / CNC / LASER / PLC expansion in this round;
- `MERGE_AUTHORIZED=false`;
- **Round 10 HOLD**.
