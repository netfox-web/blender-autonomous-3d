# Grok 修正指令：Phase 481–540 Final Tenant Backup Fail-Closed Proof

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `3a080097f6daf102801334de084b759320f8e920`  
> Reviewed CODE_EVIDENCE_SHA: `1fc86cff1101c8a8e66df59950a8accc7f527d76`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 541+.** Do not rewrite existing architecture.

## Review result

The `ead6653` round contains substantial real fixes and most prior blockers are accepted within scope:

- tenant ownership is now explicit as `TENANT_OWNED / TENANT_DERIVED / GLOBAL_REFERENCE`;
- pallet ownership is derived from carton parents and cross-tenant/orphan pallet plans fail closed;
- carrier quotes are explicitly `GLOBAL_REFERENCE` and excluded from tenant-scoped backups;
- snapshot identity now re-discovers the selected tenant's relevant path set and hashes before/after copy;
- A-only DAM/remnant create/delete races retry/fail and B-only churn does not leak into A;
- post-restore health is computed from `restored_plat` and contradictory health/gate evidence fails closed;
- exact manifest file-set verification and restore-only-listed-files remain intact;
- runner evidence is bound to clean CODE `1fc86cf...`, acceptance generation `59bd2549-3cec-4d90-9401-3f6968a0885f`;
- local report: `pytest -q = 234 passed` — **MOCK/unit/integration + FIXTURE/REAL_LOGIC only**, never Production Ready;
- GitHub Actions CODE run `34337838018`: Ubuntu + Windows GREEN;
- GitHub Actions docs/head run `34338258033`: Ubuntu + Windows GREEN;
- ManufacturingRelease / Blender render paths were not changed, so previously accepted 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX evidence at `018cc70` may continue to be referenced. Do not fabricate a refresh.

Truth boundaries remain unchanged:

- Vision / AI Video / Demand = **MOCK**;
- OS sandbox / AR / print preflight / barcode hardware / McKee-BCT = **PARTIAL / ENGINEERING_ESTIMATE**;
- supplier / carrier / FX / receipts = **IMPORTED / MANUAL** unless separately proven live;
- LIVE_CNC / LIVE_LASER / PLC / autonomous machine actuation = **BLOCKED**;
- `liveMachineControl=false`;
- `liveFactoryExecutionReady=false`;
- `liveProviderReady=false`;
- `globalProductionReady=false`;
- `fullAutonomousFactoryReady=false`;
- unscoped `productionReady=true` is forbidden.

There are still two evidence-integrity gaps in the tenant backup contract. Fix these only; do not expand scope.

---

# Blocking issue 1 — Malformed shared collection types can bypass tenant filtering

`src/fox3d/backup.py::_filter_payload()` currently starts with `filtered = dict(payload)` and then does:

```python
rows = payload.get(key) or []
if not isinstance(rows, list):
    continue
```

For a declared shared collection such as `logistics.cartons`, `workorders.operations`, `qc.checks`, etc., a malformed non-list value therefore remains in `filtered` unchanged. In a TENANT_SCOPED backup that can copy malformed/unfiltered shared state instead of failing closed. This contradicts the explicit `AMBIGUOUS => BLOCKED` contract.

Related helpers also need the same strictness:

- if `idem` is present but is not a dict, `_filter_idem()` must not silently return `{}`;
- if `releases.packets` is present but is not a dict, it must fail even when the malformed value is empty/falsy;
- declared tenant-owned / tenant-derived collections missing their expected container type must never be silently copied, silently emptied, or skipped.

## Required correction

1. For every key declared in `MIXED_SPEC`, if the key is present and its value is not a list, raise `BackupError("BLOCKED", ...)`.
2. If a required/declared collection is absent, preserve existing valid empty semantics only where the runtime schema legitimately permits absence; do not use type coercion (`or []`) to hide malformed non-list values.
3. Make `_filter_idem()` fail closed when `idem` is present and is not a dict.
4. Make `releases.packets` fail closed whenever present and non-dict, including `[]`, `""`, `0`, etc.
5. Keep GLOBAL_REFERENCE policy explicit; do not solve this by copying unknown data wholesale.
6. Whole-root backup behavior may remain byte-for-byte; this correction is specifically required for TENANT_SCOPED filtering.

## Required negative regressions

At minimum, corrupt one shared state file at a time and prove TENANT_SCOPED backup fails with no successful manifest:

- `logistics.cartons` = object/dict instead of list, containing A/B-like rows;
- `workorders.operations` = object/dict instead of list;
- `qc.checks` = string/object instead of list;
- `idem` = list/string instead of dict;
- `releases.packets` = list instead of dict;
- one declared TENANT_DERIVED collection malformed.

The regression must prove that malformed schema cannot result in `consistentSnapshot=true`, `tenantLeakageAbsent=true`, or a successful restore.

---

# Blocking issue 2 — `tenantRequiredStatePreserved` is still mostly count-based

`evaluate_tenant_restore_matrix()` currently compares integer counts for most domains. Count equality is useful, but it does not prove that the same tenant-A records and lineage survived. A lost record plus a different duplicate/replacement can preserve the count and still make `tenantRequiredStatePreserved=true`.

The previous exit criterion required A's required records **and lineage** to survive, not only the same number of rows.

## Required correction

Without changing storage architecture, add deterministic semantic fingerprints/identity sets for the selected tenant and compare live-A vs restored-A for the backup matrix.

Minimum evidence by domain:

- MaterialLots: `lotId` + quantities/state digest;
- remnants: `remnantId` + material/size/source lineage digest;
- ManufacturingRelease: `releaseId`, `releaseHash`, packet hash/size, productVersion;
- WorkOrders: `workOrderId`, `releaseHash`, state, traveler/operation IDs and status digest;
- idempotency: exact tenant-scoped key set and referenced object IDs;
- receipts/stations/leases/operators/shifts/cycleCounts: exact record identity sets + essential state;
- cartons/pallet plans/shipments/checklists/handoffs: exact IDs + parent/tenant/release lineage;
- QC/exceptions: exact IDs + workOrder/release linkage;
- journal: exact selected event ID set (already partly implemented) plus sequence/head integrity;
- outbox/tx: exact selected transaction IDs or path+hash set;
- DAM: exact selected relative path + sha256 set.

`tenantRequiredStatePreserved=true` must require semantic equality for every required domain, not merely `restored_count >= live_count`.

The acceptance JSON should expose a compact `tenantStateDigest` / `identityMismatch` section so the claim is machine-verifiable.

## Required regressions

Add at least these negative tests:

1. after producing a valid A backup, replace one restored A record with another same-count record -> semantic preservation gate must fail;
2. mutate one restored A releaseHash / WO releaseHash / pallet parent / idempotency target while keeping row counts identical -> fail;
3. alter one restored A DAM file byte without changing file count -> fail;
4. alter one restored journal event ID or transaction file while keeping counts equal -> fail;
5. the normal A restore must still pass with zero B tenant-owned state and exact A semantic equality.

---

# Re-acceptance sequence

1. Fix only the two issues above. **Do not start Phase 541+.**
2. Do not rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / Logistics architecture.
3. Run `pytest -q`; report the exact count and keep MOCK/FIXTURE/REAL_LOGIC labels honest.
4. Commit code/tests as a new **CODE_EVIDENCE_SHA**.
5. Push and require GitHub Actions Ubuntu + Windows GREEN on that exact code SHA.
6. From a clean committed tree run `scripts/run_manual_pilot_e2e.py --expected-commit <CODE_EVIDENCE_SHA>`.
7. Runner must self-bind exact code SHA, clean tree, one acceptance generation, strict schema validation, exact A semantic preservation, zero B leakage, snapshot path-set/hash consistency, restored-root health and existing no-double-consume/complete gates.
8. Keep existing 8-file atomic publication + rollback. Any negative integrity case must exit non-zero and leave the prior valid 8-file bundle unchanged.
9. If ManufacturingRelease / Blender render code remains unchanged, continue referencing REAL Blender `018cc70` with an explicit reason. If those paths change, rerun clean-tree 4/4 REAL Blender evidence on the new code SHA.
10. Commit docs/evidence separately and require docs/head Ubuntu + Windows GREEN.
11. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, `docs/PILOT_BACKUP_RESTORE_ACCEPTANCE.*` and the Phase 481–540 truth set. Update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet evidence actually changes.
12. Leave Issue #1 a concise completion handoff with code SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, strict-schema negative test summary, semantic tenant-state digest result, snapshot result, restored-health result and REAL/MOCK/PARTIAL/BLOCKED matrix.

## Exit gate

Phase 481–540 remains **CHANGES REQUIRED** until TENANT_SCOPED backup rejects malformed shared schemas and `tenantRequiredStatePreserved` proves exact tenant-A semantic state/lineage rather than count-only equality.

Do not call this Production Ready. LIVE_CNC / LIVE_LASER / PLC / autonomous machine execution remain BLOCKED.
