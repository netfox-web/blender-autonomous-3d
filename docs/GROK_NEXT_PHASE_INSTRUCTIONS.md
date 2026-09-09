# Grok 修正指令：Phase 481–540 Backup / Restore & Evidence Integrity

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `583e74dd7d39003ba4f164c60041513656ecf88e`  
> Reviewed CODE_EVIDENCE_SHA: `523b3cb2ed1dc960785fcea43256198425d2e77e`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 541+.** Fix the Phase 481–540 integrity gaps below first.

## Review result

Phase 481–540 contains substantial real implementation and may be retained. Do **not** rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / Logistics / Pilot architecture.

Accepted within current scope:

- operator / shift persistence and tenant checks: **REAL_LOGIC / MANUAL_IDENTITY**;
- traveler `releaseHash` pin and scan-token tenant boundary: **REAL_LOGIC**, physical barcode/scanner hardware remains **PARTIAL**;
- cycle-count human approval and stock adjustment logic: **REAL_LOGIC / MANUAL**, not ERP/accounting valuation;
- labor history and manual observation: **REAL_LOGIC / MANUAL**, accounting actual remains `NOT_IMPLEMENTED`;
- hold / rework / scrap-remnant workflow: **REAL_LOGIC** within manual-pilot scope;
- packing and handoff planning: **REAL_LOGIC / MANUAL**, no live carrier claim;
- CODE GitHub Actions run `34322747430` on `523b3cb` is GREEN on Ubuntu + Windows;
- local report says `pytest -q = 217 passed`, but this is **MOCK/unit/integration + FIXTURE/REAL_LOGIC**, never Production Ready;
- REAL Blender render evidence may continue to reference accepted clean-tree 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX evidence at `018cc70` **only if ManufacturingRelease / Blender render paths remain unchanged**.

Truth boundaries remain mandatory:

- Vision / AI Video / Demand = **MOCK**;
- OS sandbox / AR / print preflight / barcode hardware / McKee-BCT = **PARTIAL / ENGINEERING_ESTIMATE**;
- supplier / carrier / FX / receipts = **IMPORTED / MANUAL** unless separately proven by a live adapter;
- LIVE_CNC / LIVE_LASER / PLC / autonomous machine actuation = **BLOCKED**;
- `liveMachineControl=false`;
- `liveFactoryExecutionReady=false`;
- `liveProviderReady=false`;
- `globalProductionReady=false`;
- `fullAutonomousFactoryReady=false`;
- unscoped `productionReady=true` is forbidden.

---

# Blocking issue 1 — Restore no-double-consume / no-double-complete evidence is fail-open

Current `restart_after_restore()` evidence is not acceptable:

- `noDoubleConsume` is calculated using an expression equivalent to `... or consumedAfter`, so when consumption is already true the result can pass without proving that no second consumption occurred;
- `noDoubleCompletion` is hard-coded `True`;
- these values flow directly into `restoreNoDoubleConsume` / `restoreNoDoubleCompletion` mandatory gates.

This violates the previous instruction: **no `or True`, no fallback-generated PASS, no default-success booleans**.

## Required correction

Measure durable facts before and after the subprocess restart / retry, not booleans invented by the harness.

At minimum capture and compare:

- WorkOrder state before retry and after retry;
- exact reservation IDs and quantities;
- exact consumed quantity per reservation / lot and aggregate consumed quantity for the WorkOrder;
- count of material-consume journal events for that WorkOrder / semantic key;
- count of WorkOrder completion state-transition / journal events;
- releaseHash before and after;
- journal head / integrity after retry.

`restoreNoDoubleConsume=true` is allowed only when a second consume attempt leaves consumed quantities and consume-event counts unchanged.

`restoreNoDoubleCompletion=true` is allowed only when a second completion attempt leaves the WorkOrder terminal state and completion-event count unchanged.

Do not infer these properties only from `consumedFlag=true` or `state=COMPLETED`.

## Required negative regressions

Add tests proving the gate fails when:

- consumed quantity increases on the retry;
- a second consume journal event is inserted;
- a second completion transition/event is inserted;
- `noDoubleConsume` or `noDoubleCompletion` evidence is missing / false / malformed.

---

# Blocking issue 2 — `tenant_ids` backup is metadata-only, not tenant-isolated

Current `backup_pilot(..., tenant_ids=[A])` copies all files under the configured Pilot durable directories. `tenantIds` is written into the manifest, but the exported bytes are not filtered by tenant. Shared files such as `identity.json` can therefore contain tenant B records even when the manifest says the backup is for tenant A.

Current `restore_pilot(..., tenant_id=A)` checks only that A appears in the manifest, then copies the complete backup data tree. The present `crossTenantRestoreRejected` gate therefore does **not** prove tenant-A backup content excludes tenant-B state.

## Required correction

Implement one honest semantic and test it end-to-end:

### Preferred: real tenant-scoped export

For `tenant_ids=[A]`, export only records belonging to A from every tenant-bearing durable domain, including at minimum:

- MaterialLots / remnants;
- ManufacturingRelease snapshots;
- WorkOrders / travelers;
- receipts;
- stations / leases;
- operator / shift identity;
- cycle counts;
- logistics / carton / shipment records;
- QC / exceptions;
- journal / outbox / tx state;
- DAM references required by the restored records.

After restore of A, tenant B data must be absent / inaccessible across all of those domains.

If a safe subset cannot be produced for a particular shared file without architectural rewrite, fail closed and label that slice **PARTIAL/BLOCKED** rather than claiming tenant-scoped backup.

### Temporary fallback if tenant-scoped export cannot be made safe

You may temporarily define the supported backup as `WHOLE_PILOT_ROOT` only. If so:

- remove / disable `tenant_id` as a security claim;
- do not report `crossTenantRestoreRejected=true` as tenant-aware backup proof;
- label tenant-scoped restore **PARTIAL/BLOCKED**;
- keep Phase 541+ blocked until the original tenant-aware exit criterion is satisfied.

## Required tests

Create tenant A **and** tenant B state before backup. Then restore the A-scoped backup and assert tenant B has zero accessible/restored records in all tenant-bearing domains above.

Also verify idempotency namespaces remain tenant-scoped after restore.

---

# Blocking issue 3 — Backup verifier accepts unlisted files and restore copies them

Current verifier hashes/checks files listed in the manifest, but does not require the actual `backup/data` file set to equal the manifest set. `restore_pilot()` then copies every file found under `backup/data`, including an extra file that was never checksummed.

That makes the manifest incomplete as a restore integrity boundary.

## Required correction

- normalize and validate every manifest path;
- reject absolute paths, `..`, path traversal, duplicate paths and symlinks;
- after excluding explicitly documented volatile lock/tmp/staging files, require **exact equality** between manifest file paths and actual files in `backup/data`;
- reject unlisted/extra files;
- reject missing files;
- reject hash or size mismatch;
- restore **only** files in the verified manifest, not arbitrary directory contents;
- restore to a fresh/empty destination by default; unexpected existing state must fail closed unless an explicit, separately tested reconciliation mode exists;
- manifest format/version mismatch remains BLOCKED.

Required regressions:

- inject an extra unlisted file -> verify/restore must fail;
- remove a listed file -> fail;
- alter a listed file -> fail;
- duplicate manifest path -> fail;
- traversal / absolute path / symlink -> fail;
- non-empty destination containing unexpected Pilot state -> fail.

---

# Blocking issue 4 — Backup must represent one consistent durable snapshot

Per-file copying while state is mutating can create a backup whose WorkOrder, lot, journal, lease or QC files came from different points in time.

Do not redesign storage. Reuse the existing lock / atomic-write / reconciliation boundaries.

## Required correction

Implement a bounded snapshot strategy, for example:

- acquire the existing relevant storage locks in a deterministic order while collecting/copying the snapshot; **or**
- capture version/hash markers before copy, copy files, then re-read/revalidate and fail/retry if any durable source changed during collection.

Acceptance must prove the snapshot is internally consistent enough to reopen the selected WorkOrder/release/material/journal set after restore.

Add a concurrent-mutation regression in which another process/thread updates Pilot state during backup; the backup must either be a valid consistent snapshot or fail/retry. It must never silently publish an inconsistent package as `ok=true`.

This remains **local operational backup**, not cloud HA/DR.

---

# Blocking issue 5 — Phase 481–540 acceptance bundle publication is not atomic

`run_manual_pilot_e2e.py` currently writes the four JSON and four Markdown acceptance files sequentially. A crash/write error in the middle can leave a mixed old/new truth set while some files still look valid.

## Required correction

Treat the entire Phase 481–540 acceptance set as one generation:

- `MANUAL_FACTORY_PILOT_ACCEPTANCE.{json,md}`;
- `OPERATOR_SHIFT_ACCEPTANCE.{json,md}`;
- `INVENTORY_RECONCILIATION_ACCEPTANCE.{json,md}`;
- `PILOT_BACKUP_RESTORE_ACCEPTANCE.{json,md}`.

Stage all eight files under a generation-specific temporary location, validate them, then publish with atomic replace semantics and rollback/cleanup on failure.

All four JSON documents must contain and agree on:

- exact same `acceptanceGenerationId`;
- exact same `evidenceCodeCommit`;
- `workingTreeClean=true`;
- `evidenceCommitMatchesHead=true`;
- `ok=true` only after every mandatory gate passed;
- unchanged false global/live readiness flags.

Add a scoped reader/verifier that rejects:

- mixed generation IDs;
- mixed code commits;
- missing file;
- malformed JSON;
- `ok != true`;
- dirty/unbound evidence;
- contradictory truth/readiness fields.

A publication error after file N must leave the previous valid acceptance bundle completely untouched.

Required regressions:

- injected failure during publication -> previous generation preserved in all eight files;
- mixed-generation bundle -> reader rejects/non-zero;
- missing/malformed member -> rejects/non-zero;
- missing/false mandatory gate -> runner exits non-zero and does not overwrite prior valid evidence.

---

# Required Phase 481–540 re-acceptance drill

After implementing the fixes, rerun the manual-pilot acceptance using real durable facts for the scoped logic. It must still exercise at least:

1. two tenants;
2. four product-family FIXTURE paths, explicitly labeled FIXTURE;
3. exact ManufacturingRelease/releaseHash pinning;
4. STRICT_STOCK where the scenario claims real stock behavior; `FIXTURE_AUTO_SEED` must remain visibly FIXTURE only;
5. operator + shift + station validation;
6. QC fail -> blocking hold -> rework -> pass;
7. cycle-count variance -> explicit human approval -> conserved stock;
8. labor observation with estimate/manual/accounting labels kept distinct;
9. packing mismatch -> hold, manual handoff, no carrier booking claim;
10. hard subprocess restart at a mid-flow point;
11. local backup -> verified restore to a fresh root;
12. second consume and second complete attempts with durable counters proving no duplication;
13. tenant-A export/restore proving tenant-B content is not restored;
14. journal/outbox integrity healthy after restore;
15. LIVE_CNC / LIVE_LASER / provider execution remain BLOCKED.

---

# Evidence / CI sequence

1. Fix the five blockers above only. Do not expand feature scope and do not start Phase 541+.
2. Add focused unit/integration/FIXTURE/REAL_LOGIC regressions.
3. Run `pytest -q`; report the exact count. Label it correctly — MOCK/FIXTURE tests are not Production Ready.
4. Commit code/tests as a new **CODE_EVIDENCE_SHA**.
5. Push and require GitHub Actions Ubuntu + Windows GREEN on that exact code SHA.
6. From a clean committed tree, run `scripts/run_manual_pilot_e2e.py --expected-commit <CODE_EVIDENCE_SHA>` (or equivalent exact runner contract).
7. Runner must self-bind `evidenceCodeCommit`, `workingTreeClean`, generation ID and fail closed.
8. If ManufacturingRelease / Blender render code did **not** change, the previously accepted REAL Blender evidence at `018cc70` may be referenced with an explicit reason; do not fabricate a refresh. If those paths changed, rerun clean-tree 4/4 REAL Blender evidence against the new code SHA.
9. Commit the acceptance/docs separately and require docs/head Ubuntu + Windows CI GREEN.
10. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md` and the four Phase 481–540 scoped acceptance docs. Update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet evidence actually changed.
11. Leave Issue #1 a concise handoff: code SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, fixed blockers, REAL/MOCK/PARTIAL/BLOCKED matrix and remaining blockers.

## Exit gate

Phase 481–540 remains **CHANGES REQUIRED** until all five integrity blockers are fixed with tests and clean runner-bound evidence.

Do not start Phase 541+ yet. Do not call this Production Ready. LIVE_CNC / LIVE_LASER / PLC / autonomous machine execution remain BLOCKED.
