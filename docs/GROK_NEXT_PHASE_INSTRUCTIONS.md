# Grok 修正指令：Phase 421–480 Integrity Correction — Restart Recovery / Audit Commit Consistency

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `6646298669ad40a59527c288c973b993f9b3e0e1`  
> Reviewed CODE_EVIDENCE_SHA: `4069cef05d33112e8166c357e29459254bdf2ae8`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 481+ yet.** Fix only the integrity gaps below. Do not rewrite existing Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / Logistics / Pilot architecture.

## What is accepted in this round

Phase 421–480 contains substantive implementation and is not rejected wholesale:

- durable tenant-scoped journal with hash-chain verification and tamper detection;
- cross-process MaterialLot locking / generation-CAS logic;
- STRICT_STOCK no-oversell/conservation tests;
- MANUAL_STATION boundary using the existing Queue rather than a second scheduler;
- tenant-authoritative scan/operator APIs and explicit human confirmation;
- exception inbox, versioned MANUAL/IMPORTED contracts and pilot health view;
- local `pytest -q` handoff reports **191 passed**, but this remains **MOCK/unit/integration + FIXTURE evidence**, never Production Ready;
- GitHub Actions run `34305663843` on `4069cef` is GREEN on both `ubuntu-latest` and `windows-latest`;
- clean-tree render evidence is acceptable for its narrow render/release scope: 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, exact `commitSha=4069cef`, non-null matching ManufacturingRelease `releaseHash`;
- `PILOT_RELIABILITY_ACCEPTANCE` remains FIXTURE and `PILOT_DEPLOYMENT_ACCEPTANCE` remains FIXTURE/CHAOS;
- LIVE_CNC / LIVE_LASER / live provider / live factory execution remain BLOCKED, which is correct.

Truth labels remain mandatory:

- Vision / AI Video / Demand = **MOCK** unless a real authenticated provider is actually connected and exercised.
- OS sandbox / AR / print preflight / barcode / McKee-BCT = **PARTIAL / ENGINEERING_ESTIMATE** unless separately proven.
- Supplier/carrier/FX/receipts = **IMPORTED / MANUAL**, not LIVE_PROVIDER.
- LIVE_CNC / LIVE_LASER / PLC / machine actuation / live factory execution = **BLOCKED**.
- `globalProductionReady=false`.
- `liveFactoryExecutionReady=false`.
- `liveProviderReady=false`.
- `fullAutonomousFactoryReady=false`.
- Unscoped `productionReady=true` remains forbidden.

---

# Blocking gap 1 — Business mutation and journal commit are not transactionally consistent

Current MaterialLot mutation flow changes in-memory lot state and calls the durable journal **before** the outer `_transaction()` persists `lots.json`. If journal append succeeds and the later lot persist/CAS/atomic-replace fails, the journal can contain a successful `material.reserve`, `material.consume`, or rollback event for state that never committed. Reloading the lot file cannot roll that journal record back.

That violates the Phase 421 requirement that journaled actions represent mutations that actually succeeded and that audit failure/business failure cannot silently diverge.

## Required correction

Keep the current JSON durable-root architecture. Do **not** introduce Kafka/Postgres/event sourcing just for this fix. Implement a minimal crash-recoverable commit protocol around required business+journal changes.

Acceptable shapes include either:

1. **PREPARED -> durable business commit -> COMMITTED** audit semantics, where PREPARED is never treated as a successful business event and startup reconciliation deterministically resolves/blocks incomplete transactions; or
2. an equivalent staged transaction/outbox/commit-marker scheme under the existing durable root.

Whatever implementation is chosen must guarantee all of the following:

- no **COMMITTED/success** audit event exists for a business state change that did not durably commit;
- a durably committed business mutation cannot be reported as fully successful without its required committed audit record;
- retry after crash is idempotent and does not create two committed semantic events;
- startup can detect incomplete PREPARED/in-flight records and either reconcile safely or return `BLOCKED_EVIDENCE`; never silently mark them successful;
- tenant isolation and `releaseHash` lineage remain intact;
- reserve / release-reservation / consume / quarantine / receipt and other journal-required pilot mutations use the same integrity rule.

Do not weaken `EventJournal.verify()`. Extend the journal record/status contract only as needed and preserve hash-chain verification.

## Mandatory regressions

Add tests that inject each failure boundary independently:

- journal prepare/write fails before durable business commit -> business state unchanged;
- business store stage/persist fails after audit preparation -> restart shows no successful/COMMITTED ghost event;
- process exits after business staging but before final commit -> restart resolves to one deterministic state;
- journal finalization fails after business commit -> startup reconciliation must not silently present a healthy complete transaction; recover deterministically or block evidence;
- same semantic retry after recovery -> one committed semantic event only;
- material conservation remains true after every failure/restart case.

---

# Blocking gap 2 — MANUAL_STATION restart/recovery is still in-memory

`StationRegistry` persists stations/currentLease, but `StationDispatcher.leases` is in-memory, and the existing `JobQueue` adapter is also in-memory. `WorkOrderService.orders` / operations are likewise in-memory. A process restart can therefore reload a station with a non-null `currentLease` while the dispatcher has no corresponding lease/job, or lose the WorkOrder operation state needed to recover safely.

The current lease-expiry test only modifies an in-memory heartbeat and calls recovery in the same process. That is useful, but it does **not** prove the required process restart/recovery boundary.

## Required correction

Do not build a second scheduler or MES. Keep the current Queue/WorkOrder/Station services and add the **minimum durable recovery snapshot/reconciliation layer** necessary for MANUAL_STATION pilot execution.

Required behavior:

- the state needed to recover an active manual station operation survives process restart: at minimum tenant, stationId, lease/job id, workOrderId, releaseId/releaseHash, operation, lease state, timestamps, idempotency/completion marker;
- the WorkOrder state needed to decide whether ACK/START/COMPLETE is legal also survives/reloads from the existing durable root or an existing service snapshot adapter;
- startup reconciliation handles a persisted `station.currentLease` whose lease/job is missing, expired, stale, cancelled, or already completed;
- an orphaned/expired lease must be cleared/requeued to a safe manual state or surfaced as a deterministic exception; it must not strand the station forever;
- a STARTED operation recovered after restart cannot be completed twice;
- duplicate ACK / START / COMPLETE after restart remain idempotent;
- stale/superseded `releaseHash` remains blocked;
- no machine actuation path is added.

The journal is an audit layer, **not event sourcing**. Do not reconstruct the whole WorkOrder solely by replaying journal events.

## Mandatory restart regressions

Use a durable temp root and actually recreate the service/platform/process from that same root:

- create/release/reserve WO -> dispatch lease -> recreate platform -> lease is safely reconciled;
- dispatch + ACK -> recreate -> retry ACK is idempotent;
- dispatch + START -> recreate -> COMPLETE once -> recreate -> duplicate COMPLETE produces no second operation completion;
- persisted station `currentLease` + missing lease -> startup clears/blocks deterministically and station can recover;
- expired lease across restart returns operation to safe queue/manual state;
- cross-tenant restart recovery cannot attach tenant A lease/WO to tenant B station;
- restart preserves exact `releaseHash` binding.

---

# Blocking gap 3 — “crash-restart” acceptance must include a real separate-process boundary

Current `CrashInjected` + object reconstruction is a useful logic test but is not equivalent to process termination/restart. Phase 421–480 acceptance explicitly asked for process restart during reservation / operation acknowledgement.

Add deterministic subprocess fixtures that:

- start a child process against a shared durable root;
- terminate/exit the child at a controlled boundary after staging or during acknowledgement;
- start a new process against the same root;
- verify material conservation, no oversell, journal/business consistency, lease recovery, tenant isolation, and no double completion.

This remains **FIXTURE/REAL-LOGIC process evidence**, not real factory throughput.

---

# Blocking gap 4 — FIXTURE/CHAOS rows must not be labeled plain REAL

`scripts/run_pilot_deploy_e2e.py` runs a `Platform(..., mock_blender=True)` FIXTURE/CHAOS harness, but several harness-derived rows currently emit status `REAL` when their booleans pass.

Correct the truth labels:

- harness business-E2E rows generated from MOCK/FIXTURE Platform data -> **FIXTURE** (preferred) or an explicitly named **REAL_LOGIC** only where the evidence is an actual OS/process/persistence property and the scope is stated;
- do not use plain `REAL` for a mock-platform fixture merely because a boolean is true;
- actual clean-tree Blender/OptiX EvidenceBundles can remain **REAL** because they are separately executed with `usedMock=false`;
- imported supplier/carrier/FX/receipt data remains IMPORTED/MANUAL;
- barcode hardware remains PARTIAL;
- all global/live-factory readiness flags remain false.

Update `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md`, and the new deployment/operator acceptance files so the wording is consistent. `CABINET_REAL_ACCEPTANCE.md` only changes if cabinet evidence itself changes.

---

# Acceptance must fail closed on these integrity properties

Extend Phase 421–480 acceptance with explicit machine-readable booleans such as:

- `journalBusinessCommitConsistent`;
- `noCommittedGhostJournalEvents`;
- `processRestartRecovery`;
- `stationRestartRecovered`;
- `workOrderRestartRecovered`;
- `noDoubleCompletionAfterRestart`;
- `releaseHashPreservedAfterRestart`;
- `materialConservedAfterCrash`;
- `tenantIsolationAfterRestart`.

The runner `ok` / exit code must require every mandatory property. Missing/None/malformed evidence must fail closed; do not synthesize a passing default. Failed acceptance must not overwrite a previously valid successful acceptance package as if it were current success.

---

# Required evidence sequence after correction

1. Fix only the Phase 421–480 integrity gaps above. **Do not start Phase 481+.**
2. Add targeted transaction-failure, separate-process restart, lease/workorder recovery, tenant, and truth-label regressions.
3. Run `pytest -q` and report the exact count. Label it MOCK/unit/integration/FIXTURE/REAL-logic as appropriate, never Production Ready.
4. Commit code/tests first as a new **CODE_EVIDENCE_SHA**.
5. Push and require GitHub Actions `ubuntu-latest` + `windows-latest` GREEN on that code commit.
6. From a clean committed tree, run the revised Phase 421–480 FIXTURE/process-restart acceptance.
7. Because code SHA changes, rerun clean-tree REAL Blender evidence: 4/4 families, Blender 5.2.1 LTS + currently detected real NVIDIA OptiX device, `usedMock=false`, exact new CODE_EVIDENCE_SHA, verifier PASS, non-null matching ManufacturingRelease `releaseHash`, artifact hash/size.
8. Commit evidence/docs separately where practical and require current-head CI GREEN.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, deployment/operator acceptance files; update cabinet acceptance only if cabinet evidence changed.
10. Leave Issue #1 a concise completion comment with code SHA, docs SHA, pytest count, code/head CI runs, restart evidence, truth labels, and remaining BLOCKED/PARTIAL/MOCK boundaries.

## Exit gate for next ChatGPT review

Phase 481+ remains blocked until all of the following are true:

- no successful audit record can survive for an uncommitted business mutation;
- process restart can recover manual station + required WorkOrder execution state without stranded leases or duplicate completion;
- separate-process crash/restart regressions pass on Linux and Windows CI where applicable;
- FIXTURE/CHAOS acceptance no longer labels mock-platform business checks as plain REAL;
- clean-tree 4/4 REAL Blender evidence is rebound to the new code SHA;
- CI is GREEN on code and evidence/docs head;
- `globalProductionReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `fullAutonomousFactoryReady=false` remain true boundaries;
- LIVE_CNC / LIVE_LASER remain BLOCKED.
