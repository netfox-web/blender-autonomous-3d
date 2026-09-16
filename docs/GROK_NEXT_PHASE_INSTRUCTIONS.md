# Development Agent 指令：PR #15 Round 8 — Write-Once Immutable Temp Debris / Crash Window Gate

> Supervisor checkpoint: 2026-09-17
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR base: `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Accepted CODE: `0c6bb2a0e8ed8a8a7d23b8a938b5670e83f3b6c1`
> Accepted DOCS / PR head: `d36600e4831d7a86e29a4647cf72560b62b744d3`
> CODE Actions: `35135148177` — Ubuntu + Windows SUCCESS
> DOCS Actions: `35137747502` — Ubuntu + Windows SUCCESS
> Decision: **ACCEPT WITH SCOPE — Round 7 strict serialized outer-state identity closure accepted; GO Round 8**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Re-Gate result

Round 7 correction is accepted within scope.

Accepted evidence:
- old reviewed CODE `eaa4d683...` reproduced both required fail-open cases: `batchVersion=true` vs integer `1`, and absent `batchVersion` vs persisted `null`;
- `_same_state_identity()` now requires exact object/type/key-presence semantics for `taskId`, `inputHash`, and optional `batchVersion`;
- `_write_owned()` requires live held ownership and open stream; mismatch fails before write and preserves persisted bytes;
- exact CODE Actions `35135148177`: Windows 1236 PASS; Ubuntu 1232 PASS + 4 existing Windows-only skips;
- exact DOCS Actions `35137747502` on `d36600e...`: Ubuntu + Windows SUCCESS;
- retained Round 5 persistence, Round 6 cross-process ownership/fencing, and Round 7 scoped state-temp cleanup remain green;
- clean REAL acceptance `6e7d1d4f-17b2-48d4-abcb-518e878a5273`: Blender 5.2.1 LTS / OptiX / `usedMock=false`, but input remains synthetic static fixture.

Truth boundary remains unchanged:
- CI/unit/fault fixtures = **MOCK regression**;
- serialized fencing/scoped cleanup = **REAL_LOGIC**;
- actual independent process races = **REAL_PROCESS_CONCURRENCY** only where directly exercised;
- actual killed/fresh-process recovery = **REAL_PROCESS_RECOVERY** only where directly exercised;
- actual OS lock/delete-sharing/permission behavior = **REAL_OS_IO** only where directly exercised;
- Blender `usedMock=false` path = **REAL_RENDER** only;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`;
- generic/global temp cleanup remains **PARTIAL / UNCLAIMED**.

Do not relabel Mock as Production Ready.

---

## 1. Round 8 scope — immutable `_once()` crash debris only

Round 8 must stay inside the existing product-variant batch persistence path.

Target:
- `src/fox3d/model_batches.py::_once()`
- immutable request / row receipt / terminal record publication only
- crash debris created by the existing write-once publish sequence

Current pattern is conceptually:
1. create a temporary JSON file;
2. atomically materialize it;
3. `os.link(temp, final)` for write-once publish;
4. unlink temp in `finally`.

A hard kill can happen between these steps. The next gate is to prove exactly what remains on disk, whether any orphan can ever be interpreted as authority, and whether a narrowly scoped cleanup is needed.

Do **not** redesign the queue, state store, request/receipt authority model, publication verifier, DAM, Renderer, Product Master, or PreviewOwnership.

---

## 2. First reproduce on exact accepted CODE

Before production edits, use exact accepted CODE `0c6bb2a0e8ed8a8a7d23b8a938b5670e83f3b6c1` and real child processes.

Instrument only a test harness / fault hook so the child can be terminated at deterministic windows. Do not alter production behavior to manufacture the baseline.

Required crash windows:

### W1 — temp materialized, final not linked

Hard-kill after the outer temporary JSON is fully materialized but before `os.link(temp, final)`.

Record:
- exact directory inventory before/after kill;
- temp name/type/link count/bytes/SHA;
- whether final immutable path exists;
- fresh-process behavior;
- proof that orphan temp is never treated as request / row receipt / terminal authority;
- proof that no generation/replay is started automatically from the orphan.

### W2 — final linked, temp not yet unlinked

Hard-kill after `os.link(temp, final)` succeeds but before the temporary file is removed.

Record:
- final and temp inode/link relationship where available;
- exact bytes/SHA of both paths;
- fresh-process verification of the published final record;
- proof that duplicate publication remains impossible;
- proof that deleting only disposable debris would not alter the published immutable fact.

### W3 — nested atomic write interruption

If `atomic_json(temp, value)` itself can leave a nested target-specific temp on hard kill, reproduce one deterministic window and record it separately.

If W1/W2/W3 cannot be reproduced on accepted CODE, STOP and report the actual observed behavior. Do not invent a cleanup feature.

---

## 3. Required safety conclusion before any fix

Classify each leftover path into one of:
- immutable published authority;
- disposable unpublished debris;
- unknown / cannot-prove-safe.

A path may be deleted automatically only if the program can prove it is disposable debris by **name contract + exact directory scope + file type/link/reparse checks + existing workspace ownership**.

Never use:
- age / mtime;
- PID liveness;
- broad `*.tmp` glob;
- recursive sweep;
- file contents alone as authority;
- "looks unused" heuristics;
- adoption of orphan bytes into a final record.

Unknown = preserve and fail closed, not delete.

---

## 4. Minimal correction only if baseline proves orphan debris

If real W1/W2/W3 evidence proves durable orphan debris, apply the smallest local fix.

Preferred constraints:
1. future `_once()` temporary names become target-specific and machine-recognizable, e.g. bind the temp name to the intended final basename plus a bounded random token;
2. cleanup may run only while the existing `PreviewOwnership` for that exact product workspace is held;
3. cleanup must be given the exact immutable target(s) it is allowed to service; no directory-wide generic temp sweep;
4. exact published final path must never be deleted or rewritten;
5. if final exists, duplicate `_once()` still fails closed exactly as today;
6. no orphan temp may be promoted/adopted into a final record;
7. symlink/reparse/non-regular/multi-link or otherwise ambiguous candidates must not be deleted automatically;
8. cleanup failure must surface before creating a replacement immutable write;
9. do not change request/receipt/terminal schemas or authority hashes unless the baseline proves a schema bug;
10. do not touch Round 7 `state.json.<token>.tmp` cleanup except shared helper extraction that is provably semantics-preserving.

Do not attempt a repository-wide or global temp cleanup. Round 8 is only the `_once()` write-once persistence path.

---

## 5. Required regressions

At minimum:
- W1 hard-kill -> orphan remains non-authoritative; fresh process does not replay/adopt;
- W2 hard-kill -> final immutable record verifies; duplicate publication remains blocked;
- W3 nested-temp hard-kill -> nested debris is either narrowly cleaned or explicitly preserved as unknown;
- live competing process holding workspace ownership -> fresh competitor performs zero cleanup and zero immutable write;
- unknown `.tmp`, nested directories, symlink/reparse candidate, and unrelated sentinel files remain byte-identical;
- final `request.json`, row receipt `N.json`, and `terminal.json` remain byte-identical through cleanup;
- cleanup failure blocks the next immutable write before publication;
- process restart does not transform interrupted work into succeeded work;
- no automatic replay after crash;
- Round 5 persistence 30 PASS;
- Round 6 ownership 21 PASS;
- Round 7 state-temp cleanup 35 PASS;
- strict serialized identity 71 PASS.

Classification rules:
- pure helper/fixture tests = **MOCK / unit regression**;
- write-once publication/cleanup logic = **REAL_LOGIC**;
- child-process kill/restart = **REAL_PROCESS_RECOVERY** only when actual processes are killed and restarted;
- lock/link/delete-sharing/permission behavior = **REAL_OS_IO** only when actual OS behavior is exercised;
- CI is not REAL_RENDER and not Production Ready.

---

## 6. Exact CODE gate

After the minimal correction (or after proving no production change is needed):

1. freeze one exact CODE SHA on PR #15;
2. full pytest on exact code;
3. GitHub Actions Ubuntu + Windows SUCCESS on that exact SHA;
4. verify actual checkout SHA for both jobs;
5. report total tests and focused Round 8 counts;
6. retain baseline W1/W2/W3 evidence from accepted CODE;
7. cancelled/superseded runs are not PASS evidence.

If any old Round 5/6/7 gate regresses, fix only the regression; do not expand scope.

---

## 7. Clean REAL acceptance

If production code changes, rerun the existing clean product-variant REAL acceptance after exact CODE CI is green:

- Blender 5.2.1 LTS;
- OptiX / `realOptix=true`;
- `usedMock=false`;
- at least two synthetic/reference variants;
- artifact SHA/size + finite pixels + `.blend` reopen;
- restart/history/download verification;
- retained 30 + 21 + 35 process/authority/cleanup matrices;
- retained strict identity matrix;
- Round 8 actual process/OS cases recorded separately from renderer evidence.

Still declare:
- `inputTruth=SYNTHETIC_STATIC_FIXTURE`;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`.

If production code does not change because baseline proves no actionable orphan problem, do not fabricate a new REAL render requirement; report evidence-only closure and STOP for Re-Gate.

---

## 8. DOCS closure

Update only the necessary acceptance evidence, primarily:
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Record:
- W1/W2/W3 exact old-CODE observations;
- exact classification of each leftover path;
- any minimal production correction and why it is safe;
- focused process/OS regression results;
- exact CODE SHA + CODE CI run;
- clean REAL generation if production changed;
- exact DOCS SHA + DOCS CI run;
- unchanged truth boundaries.

Do not rewrite `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md`, or `CABINET_REAL_ACCEPTANCE.md` unless their declared truth actually changes.

---

## 9. Frozen gates

- PR #15 remains **DRAFT / OPEN / unmerged**;
- Round 9 HOLD until Supervisor Re-Gate;
- PR #16 remains **FROZEN DRAFT**;
- PR #13 / #14 unchanged;
- Issue #6 remains `BLOCKED_PR14_NOT_ON_MAIN`;
- no merge / retarget / rebase-to-main / cherry-pick;
- no live H3 / LTX / Vision / CNC / LASER / PLC work;
- `MERGE_AUTHORIZED=false`.

---

## 10. Final handoff

When complete, leave one `READY_FOR_RE_GATE` comment on Issue #1 containing:
- accepted baseline CODE and W1/W2/W3 reproduction result;
- new exact CODE SHA, or explicit evidence-only/no-code-change result;
- CODE Actions run ID + Ubuntu/Windows totals;
- Round 8 focused process/OS counts;
- retained Round 5/6/7 + strict-identity counts;
- clean REAL acceptance generation if production changed;
- DOCS SHA + DOCS Actions run ID + dual-platform result;
- REAL / MOCK / PARTIAL / BLOCKED truth matrix;
- `MERGE_AUTHORIZED=false`.

Then STOP. **Do not start Round 9 automatically.**
