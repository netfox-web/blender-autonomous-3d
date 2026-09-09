# Grok 修正指令：Phase 481–540 Final Backup Completeness / Snapshot Integrity

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `08212f4f3b3e59fd9608cc016623bf5adc1a07cc`  
> Reviewed CODE_EVIDENCE_SHA: `ff285a2f9ef82500b0c0f01caacd18bc1186113f`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 541+.** Do not rewrite existing architecture.

## Review result

This round is substantial and most of the prior integrity work is accepted within scope:

- durable before/after consume + completion counters: **REAL_LOGIC**;
- exact manifest file-set verification and restore-only-listed-files: **REAL_LOGIC**;
- 8-file staged/rollback publication: **REAL_LOGIC**;
- runner-bound `evidenceCodeCommit=ff285a2...`, `workingTreeClean=true`;
- local report: `pytest -q = 226 passed` — **MOCK/unit/integration + FIXTURE/REAL_LOGIC only**, never Production Ready;
- GitHub Actions CODE `34328790268`: Ubuntu + Windows GREEN;
- GitHub Actions docs/head `34329200409`: Ubuntu + Windows GREEN;
- ManufacturingRelease / Blender render path did not change, so previously accepted clean-tree 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX evidence at `018cc70` may continue to be referenced. Do not fabricate a refresh.

Truth boundaries remain unchanged:

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

The remaining problems are **backup semantic completeness and snapshot evidence integrity**, not a request for new architecture.

---

# Blocking issue 1 — Tenant-scoped backup can silently lose valid tenant-owned child state

The new tenant filter is directionally correct, but the current implementation is not yet a complete tenant backup contract.

`_filter_payload()` filters every list in shared JSON by `tenantId`. However some records in those lists do not carry an authoritative `tenantId`:

- `LogisticsService.palletize()` creates pallet-plan records without `tenantId` even though they are derived from tenant-owned cartons;
- `import_carrier_quote()` creates quote records without tenant ownership and currently shares the same durable logistics file.

Under `TENANT_SCOPED` export those records are silently dropped because `_tenant_of(record)` returns `None`. A backup that excludes tenant B but also silently loses tenant A state is not a valid tenant backup.

The current acceptance proof is also incomplete: `b_absent` checks only B lots, operators, WorkOrders, journal and stations. The previous exit criterion required the tenant boundary to be proven across all tenant-bearing durable domains, and also requires **A's required state to survive**, not only B to be absent.

## Required correction

Do not redesign storage. Add explicit ownership/derivation rules at the backup boundary:

1. For every shared durable collection, define one of these semantics:
   - `TENANT_OWNED`: record has authoritative `tenantId` and is filtered directly;
   - `TENANT_DERIVED`: ownership is derived from a verified parent ID (for example pallet plan -> carton IDs -> one tenant); cross-tenant parent sets must fail closed;
   - `GLOBAL_REFERENCE`: intentionally global/reference data, not claimed as tenant state; copy/exclude only under an explicit documented policy;
   - `AMBIGUOUS`: backup must fail closed instead of silently dropping/copying it.
2. Pallet plans must preserve tenant-A plans when all referenced cartons belong to A. A cross-tenant pallet plan must be rejected.
3. Carrier quote semantics must be explicit. If quotes are global imported reference data, label them `GLOBAL_REFERENCE` and do not count them as tenant-restored state. If they are tenant-owned, persist/derive tenant ownership and filter accordingly.
4. Preserve ManufacturingRelease packets, WorkOrder operations/travelers, idempotency namespaces and every child record needed to reopen the restored A workflow.
5. Add a machine-verifiable tenant backup matrix to acceptance with at least:
   - MaterialLots;
   - remnants;
   - ManufacturingRelease + packet + idempotency;
   - WorkOrder + operations/traveler + idempotency;
   - receipts;
   - stations + leases;
   - operators + shifts;
   - cycle counts;
   - cartons + pallet plans + shipment + checklist + handoff;
   - QC + exceptions;
   - journal + outbox/tx;
   - required DAM assets.
6. The gate must prove both:
   - `tenantLeakageAbsent=true` — B has zero restored tenant-owned state;
   - `tenantRequiredStatePreserved=true` — A's required records and lineage still exist and can be reopened after restore.
7. `crossTenantRestoreRejected=true` alone is not sufficient evidence.

## Required regressions

Create meaningful A and B records in every domain above before backup. Restore A and assert:

- no B tenant-owned record is accessible/restored anywhere;
- A's release, packet, WO, operations, lot/remnant, station/lease, identity, QC, logistics, journal/outbox and DAM dependencies are present;
- A idempotency retry still resolves to A's existing object and never to B's;
- tenant-derived pallet ownership is retained correctly;
- ambiguous/cross-tenant child ownership fails closed instead of being silently omitted.

---

# Blocking issue 2 — Snapshot fingerprint does not detect newly created/deleted source files

Current `backup_pilot()` calls `_source_files(root)` once, then fingerprints only that original list before and after copy.

If a relevant durable file is created after the initial scan — for example a new selected-tenant DAM object or remnant file in a domain not covered by the small lock set — that path is not in the original `sources` list. The before/after hashes can therefore remain equal and the manifest can still claim `consistentSnapshot=true` while the new file was omitted.

The current concurrent regression mutates `lots.json`, which is protected by `lots.lock`; it does not prove file-set consistency for unlocked/per-file domains.

## Required correction

Reuse the existing storage model; do not introduce a new database.

1. Snapshot identity must bind **both path set and content hashes**.
2. For each attempt:
   - discover the relevant source file set before copy;
   - normalize/filter it according to backup scope;
   - capture `{relativePath -> sha256}`;
   - copy/filter the snapshot;
   - rediscover the relevant source file set after copy;
   - capture the second `{relativePath -> sha256}`;
   - require exact path-set equality and hash equality.
3. A relevant file created, deleted or renamed during collection must cause retry/fail closed.
4. For tenant-scoped backup, compare the **selected tenant's relevant source set** so unrelated B-only churn does not invalidate A forever.
5. `consistentSnapshot=true` may only be emitted after that full path+hash equality check.
6. Continue to use deterministic existing locks where available; the re-scan is required even when locks are used.

## Required regressions

At minimum:

- concurrently create a new tenant-A DAM file during backup -> backup must include a consistent version or retry/fail;
- concurrently create/update a tenant-A remnant file -> include consistently or retry/fail;
- delete/rename a relevant source file during backup -> retry/fail;
- unrelated tenant-B file creation during A-scoped backup must not leak into A and should not cause false tenant-A PASS with mixed state;
- no test may accept `consistentSnapshot=true` merely because `lots.json` stayed unchanged.

---

# Blocking issue 3 — Runner health evidence must come from the restored root and fail closed

`run_manual_factory_scenario()` currently returns `health = plat2.pilot.health(tenant_id=a)`, where `plat2` points to the original live root, not the restored root. The runner's health check also only appends a failure when `journalHealthyAfterRestore` is already false, so a contradictory `health.journalIntegrity.ok=false` plus gate=true can still pass.

## Required correction

- compute post-restore health from `restored_plat`;
- if post-restore health is part of acceptance evidence, `journalIntegrity.ok` must be true independently of the boolean gate;
- contradictory health/gate evidence must fail closed;
- keep `liveCnc`, `liveLaser`, provider and global readiness false/BLOCKED.

Required regression: inject `journalHealthyAfterRestore=true` but restored health `journalIntegrity.ok=false`; runner must exit non-zero and preserve the prior valid 8-file bundle.

---

# Re-acceptance sequence

1. Fix only the three issues above. Do not start Phase 541+ and do not rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / Logistics architecture.
2. Add focused regressions for full tenant backup completeness and dynamic source-file-set snapshot races.
3. Run `pytest -q` and report exact count with correct MOCK/FIXTURE/REAL_LOGIC labels.
4. Commit code/tests as a new **CODE_EVIDENCE_SHA**.
5. Push and require GitHub Actions Ubuntu + Windows GREEN on that exact code SHA.
6. From a clean committed tree run `scripts/run_manual_pilot_e2e.py --expected-commit <CODE_EVIDENCE_SHA>`.
7. Runner must self-bind exact commit, clean tree and one acceptance generation; all mandatory gates must fail closed.
8. Keep the existing 8-file atomic publication + rollback behavior and add the new tenant/snapshot/health gates into the JSON truth set.
9. If ManufacturingRelease / Blender render code remains unchanged, continue referencing REAL Blender `018cc70` with explicit reason. If those paths change, rerun clean-tree 4/4 REAL Blender evidence on the new code SHA.
10. Commit docs/evidence separately and require docs/head Ubuntu + Windows GREEN.
11. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md` and Phase 481–540 scoped acceptance files. Update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet evidence actually changed.
12. Leave Issue #1 a concise completion handoff with code SHA, docs SHA, pytest count, both CI run IDs, generation, tenant backup matrix result, source-set snapshot result, restored-health result, and REAL/MOCK/PARTIAL/BLOCKED matrix.

## Exit gate

Phase 481–540 remains **CHANGES REQUIRED** until tenant backup proves both no leakage and no required-state loss, snapshot evidence binds the complete selected source file set, and restored-root health is fail-closed.

Do not call this Production Ready. LIVE_CNC / LIVE_LASER / PLC / autonomous machine execution remain BLOCKED.