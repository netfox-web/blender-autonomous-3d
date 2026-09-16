# Development Agent 下一輪指令：PR #15 Round 4 — Windows Durable Atomic Persistence Gate

> Supervisor checkpoint: 2026-09-16
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Reviewed CODE: `6b118898ebd430592e293c04c5cabe4bc30f37d8`
> Reviewed DOCS / PR head: `1e70faa99088e5a6f0189f5a19a6ffa8d903285c`
> Decision: **Round 3 ACCEPT WITH SCOPE / GO Round 4**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Re-Gate result

Round 3 serialized identity correction is accepted within its declared scope.

Accepted evidence:

- exact CODE `6b118898ebd430592e293c04c5cabe4bc30f37d8`;
- CODE Actions `35076940707`: Ubuntu + Windows SUCCESS, 1069 tests each, exact checkout SHA verified;
- exact DOCS `1e70faa99088e5a6f0189f5a19a6ffa8d903285c`;
- DOCS Actions `35079241314`: Ubuntu + Windows SUCCESS, 1069 tests each, exact checkout SHA verified;
- clean REAL acceptance `0af30671-aa63-44a6-9d6f-39de99892b35`: Blender 5.2.1 LTS + OptiX, `usedMock=false`, two synthetic static variants;
- prior 30 durable-lineage + 21 authority outcomes remain PASS;
- 35 serialized-type/restoration outcomes PASS;
- request/service/receipt/publication integer identity now rejects bool/float/string coercion;
- CI remains **MOCK regression only**;
- render is **REAL_RENDER** but input is `SYNTHETIC_STATIC_FIXTURE`;
- physical geometry / print / manufacturing / global readiness remain false/BLOCKED.

The first Round 3 correction acceptance attempt `02c928e7-06ec-4001-859a-844e21c6d82e` failed on Windows with `WinError 5` while atomically replacing a mutable batch progress JSON. The later isolated run passed on unchanged CODE, and the report correctly did **not** claim the Windows contention was fixed.

Round 4 therefore addresses that observed durability/reliability gap only. Do not add product features. Do not open a new PR. Do not rewrite Queue / Renderer / DAM / Product Master / authority / publication architecture.

---

## 1. Reproduce the Windows replace contention before changing code

Use the exact accepted CODE `6b118898ebd430592e293c04c5cabe4bc30f37d8` as the pre-fix baseline.

Create a focused test/harness proving the existing `recipe_3d.atomic_json()` behavior when the destination is temporarily non-replaceable on Windows.

Required reproduction:

1. destination already contains valid JSON A;
2. a real Windows file handle prevents replace/delete sharing for a bounded interval;
3. `atomic_json(destination, JSON B)` encounters the real access-denied/`WinError 5` replace path;
4. record that the old implementation fails immediately rather than tolerating a short transient lock;
5. verify destination remains valid JSON A after the failed attempt;
6. record whether the old implementation leaves orphan `*.tmp` files.

Prefer a Windows-only integration test using an actual OS handle (`CreateFileW`/equivalent) with delete sharing disabled. A monkeypatch-only test may supplement this, but must not be the sole evidence for the observed Windows behavior.

Do not fabricate a WinError if the real Windows runner cannot reproduce it. If the real lock harness behaves differently, report the actual result and stop for Re-Gate rather than broadening scope.

---

## 2. Minimal atomic persistence hardening

If the reproduction is real, harden the existing `atomic_json()` path with minimal semantics change.

Required behavior:

- continue writing the new JSON to a unique temp file in the same directory;
- replace the target atomically;
- retry **only** transient replace contention that is demonstrably appropriate for Windows access-denied / sharing violations;
- retry budget must be bounded; no infinite loops;
- use a short bounded backoff;
- do not silently swallow the final failure;
- on final failure, raise the original/typed error and leave the previous destination intact;
- always clean the temp file after success or terminal failure;
- do not treat ENOSPC, invalid path, permission policy, serialization failure, or unrelated I/O faults as retryable;
- do not weaken `_once()` immutable request/receipt/terminal semantics;
- do not turn mutable progress into publication authority.

If a generic `atomic_json()` change would alter unrelated storage semantics, instead add the smallest reusable helper needed to preserve the current contract and update only the existing callers that need replace-contension resilience. Do not introduce a second storage architecture.

---

## 3. Required regression matrix

Add focused tests that prove:

### 3.1 Transient contention

- first replace attempt(s) receive the same Windows sharing/access-denied condition;
- lock is released within the retry budget;
- final replace succeeds;
- destination becomes exact JSON B;
- no orphan temp files remain.

### 3.2 Sustained contention

- destination remains locked beyond the retry budget;
- operation fails closed;
- existing destination stays byte-valid / parse-valid and unchanged;
- temp file is cleaned;
- caller receives failure; no false success state.

### 3.3 Non-retryable error

- non-contention I/O error is not repeatedly retried;
- error propagates;
- previous destination is preserved where replacement never occurred.

### 3.4 Existing batch truth gates

All accepted Round 3 behavior must remain green:

- 1069 existing tests retained;
- 30 durable-lineage outcomes retained;
- 21 authority outcomes retained;
- 35 serialized-type/restoration outcomes retained;
- `MEASURED_OR_CAD_AUTHORITY` still rejected without reviewed evidence provider;
- fixture/reference inputs cannot become physical or manufacturing truth.

---

## 4. Exact CODE gate

After the minimal fix:

1. freeze a new CODE SHA on existing PR #15;
2. run exact CODE GitHub Actions;
3. Ubuntu SUCCESS;
4. Windows SUCCESS;
5. verify actual checkout SHA equals the new CODE SHA;
6. report total tests plus the Windows persistence-focused test count;
7. distinguish normal MOCK/unit regression from the **real Windows filesystem integration** result.

GitHub CI remains non-Blender regression evidence. A real Windows filesystem lock test may be labeled **REAL_OS_IO**, but it is not REAL render and not Production Ready.

If CI fails, fix only that failure and repeat with a new exact CODE SHA.

---

## 5. Clean REAL acceptance on the hardened CODE

After exact CODE dual-platform SUCCESS, rerun the existing `scripts/run_model_batches_e2e.py --round3` path from a clean tree on the new exact CODE. Do not create a new acceptance architecture.

Required:

- Blender 5.2.1 LTS;
- OptiX / `realOptix=true`;
- `usedMock=false`;
- at least two synthetic/reference variants;
- artifact SHA/bytes, finite nonuniform image checks and `.blend` reopen;
- restart/history/download checks;
- 30 durable-lineage + 21 authority + 35 serialized-type matrices still PASS;
- batch progress writes complete without ignored persistence errors;
- report any new Windows contention observed; do not hide failed attempts.

Truth remains:

- batch/authority/publication verifier: **REAL_LOGIC**;
- filesystem lock integration: **REAL_OS_IO** if executed on an actual Windows runner;
- render execution: **REAL_RENDER**;
- fixture geometry/input: **SYNTHETIC / REFERENCE**;
- normal CI pytest: **MOCK regression**;
- physical geometry truth: **BLOCKED / false**;
- physical print: **BLOCKED / false**;
- manufacturing readiness: **BLOCKED / false**;
- global Production Ready: **false**.

---

## 6. DOCS closure

Only after CODE CI + real Windows persistence check + clean REAL Blender acceptance PASS:

- update the existing `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md` and `.json`;
- explicitly record old WinError reproduction, fix behavior, retry policy, sustained-lock failure behavior, and temp-file cleanup;
- do not rewrite unrelated historical audit files merely to make them look current;
- commit DOCS after evidence exists;
- run exact DOCS SHA Ubuntu + Windows CI;
- both must be SUCCESS before `READY_FOR_RE_GATE`.

---

## 7. Existing gates stay frozen

- PR #15 remains DRAFT / OPEN on PR #12; **no merge, retarget, rebase-to-main or cherry-pick**.
- PR #16 remains **FROZEN DRAFT**.
- PR #14 remains unmerged and without merge authorization.
- Issue #6 remains `BLOCKED_PR14_NOT_ON_MAIN`.
- PR #13 Round 3B remains blocked; no articulation authority copy and no DOOR_OPEN promotion.
- No live H3/LTX/Vision/CNC/LASER/PLC work.
- `MERGE_AUTHORIZED=false`.

---

## 8. Final handoff

When all gates pass, leave one concise Issue #1 `READY_FOR_RE_GATE` handoff with:

- this instruction SHA;
- exact CODE SHA + CODE CI run/jobs;
- pre-fix real Windows contention reproduction result;
- exact retryable error classification and bounded retry policy;
- transient-lock / sustained-lock / non-retryable test results;
- temp-file cleanup result;
- total/focused test counts;
- clean REAL acceptance ID and Blender/OptiX/usedMock fields;
- retained 30 + 21 + 35 matrices;
- exact DOCS SHA + DOCS CI run/jobs;
- REAL/MOCK/PARTIAL/BLOCKED matrix;
- `physicalProductGeometryTruth=false`;
- `physicalPrintValidated=false`;
- `manufacturingReady=false`;
- `globalProductionReady=false`;
- PR #16 frozen / Issue #6 blocked / `MERGE_AUTHORIZED=false`.

Then STOP for Supervisor Re-Gate. Do not start Round 5 automatically.
