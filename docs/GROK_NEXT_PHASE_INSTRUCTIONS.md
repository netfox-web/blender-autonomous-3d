# Development Agent 指令：PR #15 Round 9B — Durable Commit / Indeterminate Namespace Commit Correction

> Supervisor checkpoint: 2026-09-17
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 8 CODE: `8129309c45b1db566385305e0db5a03f23c64e33`
> Accepted Round 8 DOCS: `85ecad41da13bcd14140a7dd373fed4e09012a4f`
> Exact CODE Actions: `35147126655` — Windows 1285 PASS; Ubuntu 1281 PASS + 4 existing Windows-only skips
> Exact DOCS Actions: `35149729964` — Windows 1285 PASS; Ubuntu 1281 PASS + 4 existing Windows-only skips
> Clean REAL Blender acceptance: `4c084b88-a7b3-4780-89e9-7bc60721d07e`
> New Grok report: Issue #1 comment `5705499390`
> Decision: **CHANGES REQUIRED — ROUND 9 CORRECTION AUTHORIZED**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Supervisor review result

The Round 9 Phase A stop report is valid and must not be hidden or relabeled as a successful durability acceptance.

Accepted findings from the unchanged Round 8 baseline:

- `recipe_3d.atomic_json()` and `model_batches._once()` currently provide process-crash atomicity semantics but do not explicitly perform a durable host file flush plus namespace synchronization before/after the commit boundary.
- Actual Windows NTFS `FlushFileBuffers` and exercised directory-handle flush succeeded on the tested host. This is platform-specific **REAL_OS_IO_FLUSH** only.
- Actual Linux file `fsync` plus directory-fd `fsync` succeeded on the exercised Linux filesystem path. This is **REAL_OS_IO_FLUSH** only.
- The post-namespace failure reproducer is **MOCK / FAULT_INJECTION_LOGIC** at the injected EIO boundary, even though it uses real file flush/replace operations and the real publication verifier.
- The reproducer correctly demonstrates that once the final namespace mutation has already happened, a later namespace-sync error can leave a complete final publication visible to a fresh process. That state is not equivalent to a clean failure and cannot honestly be proven "not committed" using only the existing final file.
- Hardware/power-loss survival remains **BLOCKED / NOT_TESTED**.

The previous D5 wording was over-constrained for the existing file-only authority model. Do **not** invent a second database/WAL/marker authority solely to force the old wording to pass.

Do not rewrite queue/state/authority/publication/DAM/Renderer/Product Master/PreviewOwnership architecture.

---

# Round 9B goal

Implement the smallest real durability primitive around the existing commit paths, while treating a post-namespace-sync failure honestly as an **indeterminate commit outcome**, not as definite success and not as definite rollback.

The correction must preserve all accepted Round 5–8 behavior and must not turn an indeterminate filesystem outcome into automatic replay, duplicate publication, overwrite, or fake power-loss safety.

## 1. Frozen baseline

Start production work from exact accepted CODE:

`8129309c45b1db566385305e0db5a03f23c64e33`

Retain:
- `PreviewOwnership`;
- exact `taskId` / `inputHash` / `batchVersion` fencing;
- immutable `_once()` semantics;
- request / row receipt / terminal receipt / publication verifier authority;
- W2 multi-link ambiguity preservation;
- scoped temp cleanup only;
- no orphan temp adoption;
- no automatic replay;
- existing Windows sharing-violation fail-closed behavior.

Do not modify unrelated PRs or merge anything.

---

## 2. Minimal durability helper

Add only the minimum shared helper(s) needed by the existing persistence paths.

### 2.1 File content commit

For every temp file that can become state or immutable authority:

1. write complete bytes;
2. flush Python/runtime buffering;
3. execute the real platform file durability primitive on the still-open handle;
4. only after the file flush succeeds, perform the existing namespace mutation (`replace`, `link`, or the existing scoped unlink path).

If the file durability primitive fails **before** the namespace mutation, fail closed. The final authority must not be newly exposed by that call.

### 2.2 Namespace synchronization

After the actual namespace mutation, execute the real supported containing-directory / namespace synchronization for that platform and filesystem surface.

- POSIX/Linux: use the real directory-fd synchronization supported by the exercised platform.
- Windows: use only the real handle/flush behavior actually supported and exercised by the current Windows host/runner. Do not claim a blanket guarantee for every Windows filesystem.

Keep the platform implementation small and local. Do not create a storage subsystem.

---

## 3. Corrected post-namespace failure semantics

A failure **before** the namespace mutation and a failure **after** the namespace mutation are different states.

### A. Pre-commit failure

If complete-file durable flush fails before `replace/link`:
- caller fails;
- no new final authority is exposed;
- no success receipt/publication is emitted;
- fresh process must not replay or adopt temp debris.

This is a normal fail-closed failure.

### B. Post-namespace synchronization failure

If the namespace mutation has already happened and the following directory/namespace synchronization reports an error:

- propagate a typed/internal **COMMIT_INDETERMINATE** outcome (a narrowly scoped exception/result is allowed);
- do not emit a new success response from that failed call;
- do not delete/rollback a complete immutable final merely to manufacture a clean failure;
- do not create a second authority marker, WAL, DB, Redis store, replay log, or replacement object store;
- do not rewrite the existing publication verifier;
- do not replay the generation automatically.

On a later fresh-process read/recovery:

- if the immutable final is absent, remain failed/unpublished;
- if the immutable final exists but fails the existing full verifier, fail closed;
- if the immutable final exists and passes the existing full verifier, it may be observed as the already-existing immutable publication, but that observation must be classified **PARTIAL / COMMIT_INDETERMINATE_DURABILITY** for the Round 9 evidence. It is not proof that the namespace survived a future power loss;
- never create a duplicate publication or overwrite the verified immutable final;
- W2 multi-link ambiguity remains **PARTIAL / PRESERVED UNKNOWN** and must not be auto-cleaned/adopted.

This is reconciliation of an already-visible immutable final, not orphan-temp adoption and not replay.

The implementation must not silently relabel `COMMIT_INDETERMINATE` as `SUCCESS` in the same failing call.

---

## 4. Required Round 9B acceptance matrix

### D1 — Real file flush before namespace commit

Exercise actual Windows and Linux host file flush operations on the real persistence code path.

Required evidence:
- complete bytes written;
- real file durability primitive executed;
- induced file-flush failure prevents the namespace commit;
- final remains absent;
- fresh process does not treat temp as authority.

Classification:
- real successful host flush: **REAL_OS_IO_FLUSH**;
- injected failure: **MOCK / FAULT_INJECTION_LOGIC**.

### D2 — Namespace mutation + real namespace sync

Exercise the real `replace/link/unlink` commit sequences with the supported directory/namespace synchronization on both target platforms where available.

Record the exact API/mechanism and filesystem/OS context. Do not generalize beyond the tested surface.

### D3 — Post-namespace sync failure = indeterminate

Using the existing unmocked verifier and a copied accepted fixture or isolated real test workspace:

1. durable temp file flush succeeds;
2. real namespace mutation succeeds;
3. inject failure at the namespace-sync result boundary;
4. the originating call reports `COMMIT_INDETERMINATE` / error, not success;
5. a fresh process inspects the workspace;
6. if final exists and verifies, no duplicate/replay/overwrite occurs;
7. evidence label is **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
8. no claim of real device failure or power-loss survival.

The existing Issue #1 comment `5705499390` is the required negative baseline showing why definite-failure semantics are invalid after the mutation.

### D4 — `_once()` W2 retained

Retain Round 8 behavior:
- final + temp same-file hardlinks may remain after interruption;
- ambiguous multi-link candidate is preserved;
- no delete/adopt/replay;
- exact immutable final verifier remains authoritative;
- classification stays **PARTIAL / PRESERVED UNKNOWN**.

### D5 — Durable clean path + restart

After all file and namespace durability primitives report success:
- kill/terminate the owner process;
- fresh process reads request / row / terminal / publication consistently;
- no duplicate publication;
- no stale-writer overwrite;
- no implicit replay.

This is **REAL_PROCESS_RECOVERY** plus platform-specific **REAL_OS_IO_FLUSH** where actually exercised. It is not power-loss evidence.

### D6 — Retained regressions

Retain all accepted Round 5–8 gates:
- cross-process single writer;
- exact serialized identity (`true != 1`, absent != null);
- Windows sharing-handle behavior;
- abrupt process recovery;
- scoped Round 7 temp cleanup;
- Round 8 W1/W2/W3;
- immutable receipt/publication verification;
- no duplicate publication.

---

## 5. Forbidden shortcuts

Do not add or substitute:
- SQLite/PostgreSQL transaction journal;
- Redis;
- WAL subsystem;
- second queue/state store;
- durability marker that becomes a second publication authority;
- replay engine;
- broad `*.tmp` cleanup;
- mtime/PID stale heuristics;
- orphan temp adoption;
- delete-on-sync-error rollback intended only to make the test green;
- mocked flush reported as REAL;
- subprocess kill reported as power loss.

If a stronger definite-commit/definite-rollback contract truly requires a new transactional authority protocol, STOP and report that architectural requirement rather than implementing it in this round.

---

## 6. Evidence truth labels

Use only these meanings:

- **REAL_OS_IO_FLUSH** — an actually executed host-OS file or supported namespace flush on the named OS/filesystem surface.
- **REAL_PROCESS_RECOVERY** — real child process termination + fresh-process recovery.
- **REAL_LOGIC** — implemented persistence/reconciliation logic whose behavior is exercised without claiming hardware durability.
- **MOCK / FAULT_INJECTION_LOGIC** — injected EIO/flush/sync failure or ordinary CI/mock-render evidence.
- **PARTIAL / COMMIT_INDETERMINATE_DURABILITY** — namespace mutation occurred but subsequent namespace durability operation failed; final may be visible and valid, but survival across power loss is not proven.
- **PARTIAL / PRESERVED UNKNOWN** — retained W2 multi-link ambiguity.
- **BLOCKED / NOT_TESTED** — hardware power cut/reset survival without a destructive hardware harness.
- **REAL_RENDER** — only a clean Blender run with `usedMock=false`.

Never use `POWER_LOSS_SAFE`, `REAL_POWER_LOSS`, `CRASH_DURABLE`, `FULLY_DURABLE`, or global Production Ready without matching physical evidence.

The following remain false:
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`.

---

## 7. Evidence package and CI

If production persistence code changes:

1. freeze exact CODE SHA;
2. run exact CODE SHA CI on Ubuntu + Windows;
3. both jobs must SUCCESS and verify checkout SHA;
4. rerun clean `usedMock=false` Blender regression acceptance against the final CODE SHA;
5. update only the existing Round 9 truth package:
   - `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`;
   - `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`;
6. record D1–D6, exact APIs, OS/filesystem context, classifications, CODE SHA/run ID, REAL Blender run ID, DOCS SHA/run ID;
7. freeze exact DOCS SHA;
8. run exact DOCS SHA CI on Ubuntu + Windows;
9. leave exactly one new `[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE` Issue #1 handoff;
10. STOP.

Do **not** rewrite `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md`, or `CABINET_REAL_ACCEPTANCE.md` just to make them look newer. Change them only if an existing declared truth becomes factually false.

If the corrected scope still cannot be met without a new transactional authority protocol, leave one `[ROUND9_BLOCKED]` report with the exact failing invariant and STOP. Do not implement Round 10.

---

## 8. Frozen gates

- PR #15 remains DRAFT / OPEN / unmerged;
- PR #16 remains FROZEN DRAFT;
- PR #13 / #14 unchanged;
- Issue #6 gate unchanged;
- no merge / retarget / rebase-to-main / cherry-pick;
- no live H3 / LTX / Vision / CNC / LASER / PLC work;
- `MERGE_AUTHORIZED=false`;
- **Round 10 HOLD**.
