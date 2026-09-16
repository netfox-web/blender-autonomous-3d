# Development Agent 指令：PR #15 Round 9B — FINAL CI + REAL EVIDENCE CLOSURE ONLY

> Supervisor checkpoint: 2026-09-17
> Reviewed repo: `netfox-web/blender-autonomous-3d`
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 8 CODE: `8129309c45b1db566385305e0db5a03f23c64e33`
> Accepted Round 8 DOCS: `85ecad41da13bcd14140a7dd373fed4e09012a4f`
> Current Round 9B final candidate CODE: `87ea4d3ba753c811f693cec8f4a3f465aca94364`
> Prior Round 9B CODE: `fa6afd48e08b11f2e9eaf2de9df3684c5cd6d5ba`
> Current Issue #1 progress report: `5705961718`
> Decision: **PARTIAL / EVIDENCE CLOSURE REQUIRED — ROUND 10 HOLD**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Supervisor result

Round 9B implementation direction is accepted provisionally, but the round is **not accepted yet** because the final candidate has not closed its exact CI + clean REAL + docs evidence gates.

Do **not** add new feature scope and do not rewrite architecture.

Current reviewed facts:

- `fa6afd48e08b11f2e9eaf2de9df3684c5cd6d5ba` added the minimum shared durability helper around existing file publication paths:
  - runtime buffer flush + real host file flush;
  - existing `replace/link/unlink` namespace mutations;
  - supported directory / namespace flush;
  - typed `CommitIndeterminate` after a namespace mutation when the following namespace synchronization fails.
- Exact Actions `35159595918` for `fa6afd48...` completed SUCCESS on Ubuntu + Windows. This CI remains regression evidence; it is not REAL_RENDER and not power-loss proof.
- The subsequent clean REAL attempt `b940339a-eb0c-443a-9ba8-25f911421e5e` failed before artifacts because active status polling observed the newly widened initial request/progress flush window and returned 422. **Retain this failure as negative evidence. Do not relabel it PASS.**
- `87ea4d3ba753c811f693cec8f4a3f465aca94364` narrowly corrects that window: while the real workspace owner is live, no terminal/row facts exist, and committed identities remain valid, the active read may return pending/no-batch only. It must not write, reconstruct, adopt debris, replay work, or hide corruption.
- New focused tests cover request committed/uncommitted initial windows and corruption/identity/terminal/row controls. These are useful **REAL_LOGIC / regression** tests, but final full-suite and exact-CODE CI are still required.
- Exact final candidate Actions `35161605399` is still **in progress** at this checkpoint. It is not accepted evidence until both Ubuntu and Windows jobs complete SUCCESS against exact SHA `87ea4d3...`.
- D3 copied-artifact reconciliation on the final candidate may be kept as:
  - real host file/namespace calls actually exercised: **REAL_OS_IO_FLUSH** on the named runner/filesystem surface only;
  - injected sync-error boundary: **MOCK / FAULT_INJECTION_LOGIC**;
  - already-visible verified final after post-namespace sync failure: **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
  - not a new render and not power-loss evidence.

The existing Round 8 truth boundaries remain unchanged:

- `physicalProductGeometryTruth=false`
- `physicalPrintValidated=false`
- `manufacturingReady=false`
- `globalProductionReady=false`
- `MERGE_AUTHORIZED=false`
- W2 multi-link ambiguity remains **PARTIAL / PRESERVED UNKNOWN**
- hardware reset / real power-loss survival remains **BLOCKED / NOT_TESTED**

`docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, and `docs/CABINET_REAL_ACCEPTANCE.md` remain historical/canonical lanes. Do not rewrite them merely to make them look current. Update them only if an existing declared truth becomes factually false.

---

# 1. Freeze production code now

Freeze exact CODE candidate:

`87ea4d3ba753c811f693cec8f4a3f465aca94364`

Do not make another production-code commit merely because CI is still running.

Only change production code again if one of the required final gates actually fails and a concrete defect is reproduced. Any correction must be minimal and local; after a correction, freeze a new exact CODE SHA and restart the exact-CODE closure sequence from the beginning.

Do not add DB / SQLite / PostgreSQL / Redis / WAL / second authority marker / replay engine / new queue / new state store / new publication protocol.

---

# 2. Required final CODE gate

Wait for exact Actions run:

`35161605399`

Required before any READY_FOR_RE_GATE claim:

1. run head SHA is exactly `87ea4d3ba753c811f693cec8f4a3f465aca94364`;
2. Ubuntu job completes SUCCESS;
3. Windows job completes SUCCESS;
4. full final suite completes with no hidden failure/cancelled job;
5. record the exact PASS / skip counts from each OS job;
6. CI remains labeled **MOCK / regression** for renderer/artifact paths unless a test explicitly exercises a real OS primitive, in which case only that primitive receives the narrower **REAL_OS_IO_FLUSH** label.

If this run fails, do not rerun until the failure is classified. Reproduce, fix narrowly, create one new CODE SHA, and run a fresh exact-CODE dual-platform CI. Cancelled/superseded runs are not evidence.

---

# 3. Clean REAL acceptance after final CODE CI only

Only after exact CODE CI is dual-platform SUCCESS, rerun the existing clean acceptance against the exact final CODE SHA.

Required:

- clean working tree bound to exact CODE SHA;
- Blender 5.2.1 LTS + OptiX;
- `usedMock=false`;
- existing synthetic/static fixture scope only;
- actual artifacts emitted and verified;
- `.blend` reopen / bytes-SHA-size / finite image checks retained;
- request / row / terminal / publication verification retained;
- restart/history/download/lineage checks retained;
- no duplicate publication;
- no automatic replay/adoption;
- Round 5–8 retained gates still PASS;
- Round 9B durability path exercised without claiming physical geometry, physical print, manufacturing readiness, or power-loss safety.

The failed run `b940339a-eb0c-443a-9ba8-25f911421e5e` must stay recorded as a failed pre-final attempt. Do not overwrite or erase it from provenance.

Classification:

- clean `usedMock=false` Blender artifact path: **REAL_RENDER**;
- actual child kill/fresh-process path if exercised: **REAL_PROCESS_RECOVERY**;
- actual host flush calls: **REAL_OS_IO_FLUSH** on the named OS/filesystem only;
- injected EIO/sync failures: **MOCK / FAULT_INJECTION_LOGIC**;
- post-namespace error with a later verifier-accepted immutable final: **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
- W2 retained hardlink ambiguity: **PARTIAL / PRESERVED UNKNOWN**;
- physical power cut/reset: **BLOCKED / NOT_TESTED**.

---

# 4. Evidence package

After the clean REAL acceptance passes, update only the existing Round 9 truth package unless another existing truth document is now factually wrong:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Record at minimum:

- accepted baseline CODE/DOCS references;
- final Round 9B CODE SHA;
- exact CODE Actions run ID and per-OS results;
- failed REAL attempt `b940339a-eb0c-443a-9ba8-25f911421e5e` as retained negative evidence;
- final successful clean REAL acceptance ID;
- D1–D6 results from the controlling Round 9B contract;
- exact Windows/Linux API/mechanism and tested filesystem context;
- `COMMIT_INDETERMINATE` semantics;
- no same-call success after post-namespace sync failure;
- no replay / overwrite / duplicate publication;
- W2 preserved ambiguity;
- all REAL/MOCK/PARTIAL/BLOCKED classifications;
- all unchanged false readiness flags.

Do not claim:

- `POWER_LOSS_SAFE`
- `REAL_POWER_LOSS`
- `CRASH_DURABLE`
- `FULLY_DURABLE`
- global Production Ready

---

# 5. Exact DOCS gate

After evidence docs are complete:

1. freeze one exact DOCS SHA on PR #15;
2. run GitHub Actions on that exact DOCS/head SHA;
3. Ubuntu + Windows must both complete SUCCESS;
4. verify run head SHA equals exact DOCS SHA;
5. record exact pass/skip counts;
6. do not treat docs CI as REAL_RENDER.

No READY_FOR_RE_GATE before this completes.

---

# 6. Final handoff

When and only when all required gates above pass, leave exactly one new Issue #1 comment headed:

`[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE`

Include:

- final CODE SHA;
- exact CODE Actions run ID + Ubuntu/Windows result/counts;
- successful clean REAL acceptance ID;
- failed REAL attempt ID retained as negative evidence;
- exact DOCS SHA;
- exact DOCS Actions run ID + Ubuntu/Windows result/counts;
- concise D1–D6 classification summary;
- `globalProductionReady=false`;
- `MERGE_AUTHORIZED=false`;
- PR #15 DRAFT / OPEN / unmerged;
- PR #16 FROZEN;
- Round 10 HOLD.

Then STOP for Supervisor Re-Gate.

If a new concrete blocker appears instead, leave one precise `[ROUND9B_BLOCKED]` comment with the failing invariant/evidence and STOP. Do not start Round 10.

---

# 7. Frozen gates

- PR #15 remains DRAFT / OPEN / unmerged;
- PR #16 remains FROZEN DRAFT;
- PR #13 / #14 unchanged;
- Issue #6 gate unchanged;
- no merge / retarget / rebase-to-main / cherry-pick;
- no live H3 / LTX / Vision / CNC / LASER / PLC work;
- no architecture rewrite;
- no Mock/FIXTURE promotion to Production Ready;
- `MERGE_AUTHORIZED=false`;
- `globalProductionReady=false`;
- **Round 10 HOLD**.
