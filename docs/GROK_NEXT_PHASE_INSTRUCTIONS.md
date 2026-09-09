# Grok 下一輪開發指令：Phase 421–480 Pilot Deployment Hardening / Operator Control Plane V1

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `527634dd5413ba41c009e5f02d7a614198aea9f2`  
> Reviewed CODE_EVIDENCE_SHA: `997db345183367709597738c12c65bbf6800ae4c`  
> ChatGPT review result: **ACCEPT WITH SCOPE**  
> Phase 361–420 final integrity blockers are accepted within the evidence scope below. You may start **Phase 421–480**.

## Review decision / accepted evidence

The prior `1129ae6` correction round is accepted with the following scope boundaries:

- `main` advanced from `1129ae6` through implementation commits `4c30151` and `997db34`, then evidence/docs commit `527634d`.
- Local `pytest -q`: **175 passed** according to the handoff. This remains **MOCK/unit/integration + FIXTURE evidence**, never global Production Ready evidence.
- GitHub Actions code run `34299148581` on `997db34`: **ubuntu-latest SUCCESS + windows-latest SUCCESS**.
- GitHub Actions docs/head run `34299272260` on `527634d`: **ubuntu-latest SUCCESS + windows-latest SUCCESS**.
- Acceptance hook no longer replaces missing/None/empty/incomplete reliability evidence with an implicit passing stress object. Direct runner regressions exist for omitted / `None` / empty / incomplete reliability data, and failed gates do not publish canonical acceptance.
- STRICT_STOCK now enforces frozen ManufacturingRelease `sheetSku`, thickness, sheet length/width, and required grain when present. Wrong/missing geometry or grain is unavailable rather than silently compatible.
- MANUAL/IMPORTED receipts can preserve lot length/width/grain, and expected-geometry/grain mismatches are quarantined.
- WorkOrder / ManufacturingRelease / carton caller-supplied idempotency keys are tenant-scoped; carton and shipment namespaces are separated; same-tenant retry remains idempotent.
- Reliability partial-shortage test is isolated from durable leftover stock using unique tenant/SKU and requires an actual `StockShortage` plus unchanged lot quantities.
- Clean-tree REAL acceptance is **4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX**, `usedMock=false`, exact `commitSha=997db34`, verifier PASS, and non-null matching ManufacturingRelease `releaseHash`.
- `PILOT_RELIABILITY_ACCEPTANCE.json` is correctly **FIXTURE**, with 50 WorkOrders / 652 operation transitions and explicit reliability booleans/negative cases. It is not factory throughput evidence.
- `CABINET_REAL_ACCEPTANCE.md` did not change this round and remains scoped cabinet evidence only.

Truth labels remain mandatory:

- Vision / AI Video / Demand = **MOCK** unless a real authenticated provider is actually connected and exercised.
- OS sandbox / AR / print preflight / barcode / McKee-BCT = **PARTIAL / ENGINEERING_ESTIMATE** unless separately proven.
- Supplier/carrier/FX/receipts = **IMPORTED / MANUAL**, not LIVE_PROVIDER.
- LIVE_CNC / LIVE_LASER / PLC / machine actuation / live factory execution = **BLOCKED**.
- `globalProductionReady=false`.
- `liveFactoryExecutionReady=false`.
- `liveProviderReady=false`.
- `fullAutonomousFactoryReady=false`.

Do not use the unscoped word `productionReady=true`.

---

# Global constraints for Phase 421–480

Do **not** rewrite the existing Scheduler, Queue, DAM, Recipe, TwinStore, CabinetSpec, MaterialLot, ManufacturingRelease, WorkOrder, QC, Logistics, Receipt, or Pilot service architecture. Extend the current services/adapters and their durable stores.

Do not create a second ERP/WMS/MES/QMS/scheduler/inventory engine. The objective is to make the existing Pilot boundary safer and deployable for **human-controlled pilot operations**, not to replace company systems.

Do not add any command path that can actuate a CNC, laser, spindle, relay, PLC, robot, conveyor, cutter, heater, or other machine. No G-code execution, serial/Modbus/PLC writes, spindle/laser enable, or automatic machine start. Manufacturing packets/travelers may be generated/exported, but actual machine execution remains human-controlled and **BLOCKED** in Fox3D.

Every state transition introduced in this phase must preserve:

- tenant isolation;
- exact ManufacturingRelease / `releaseHash` lineage;
- idempotency;
- stale/superseded release blocking;
- append-only QC/rework history where applicable;
- material quantity conservation;
- no mock fallback on REAL acceptance paths;
- fail-closed acceptance behavior.

---

# Phase 421–428 — Durable Pilot Event Journal V1

Add a durable, append-only event journal around the existing pilot aggregates. Do not move business state into a new event-sourcing system; the journal is an audit/recovery evidence layer around the current stores.

## Required events

At minimum journal these existing actions when they actually succeed:

- ManufacturingRelease create / validate / submit approval / approve / stale / supersede / cancel;
- receipt imported/manual accepted or quarantined;
- MaterialLot reserve / rollback / consume / release reservation / quarantine;
- WorkOrder create / release-for-execution / reserve / operation start / operation complete / rework / complete / cancel;
- QC record / FINAL gate result;
- carton instantiate / measured capture;
- shipment draft create;
- manual station dispatch events added later in this phase.

## Event contract

Each journal record must include at least:

- `eventId`;
- `eventType`;
- `tenantId`;
- `aggregateType`;
- `aggregateId`;
- `sequence` or monotonic aggregate version;
- `actor` / source;
- UTC timestamp;
- `releaseHash` when the event belongs to a release/work order/product execution lineage;
- payload hash;
- `previousEventHash`;
- `eventHash`.

Persist under the existing Fox3D durable root. Use atomic append/replace semantics appropriate to the current persistence model. Do not require Kafka, Redis, Postgres, or another infrastructure service just for this phase.

## Required behavior

- restart must preserve the journal;
- tenant A cannot read/export tenant B events;
- duplicate/idempotent retries must not create duplicate semantic events;
- tampering or broken hash chain must be detected and reported as `PARTIAL/BLOCKED_EVIDENCE`, never silently accepted;
- journal failure must not fabricate a successful audit record;
- do not mark a business mutation successful if its required durable audit append cannot be committed consistently.

## Tests

Add restart, tenant-isolation, duplicate retry, tamper, sequence, and hash-chain regressions.

---

# Phase 429–436 — Cross-process Material Reservation / Crash Safety

The current thread/concurrency tests are useful but do not prove separate-process safety. Harden the existing `MaterialLotRegistry` persistence boundary without replacing it.

## Required behavior

- multi-lot STRICT_STOCK allocation must be atomic from the caller’s perspective;
- two OS processes attempting to reserve the same scarce stock must never oversell;
- reserve/rollback/consume must survive process termination/restart without losing quantity conservation;
- durable writes must be temp/stage + atomic replace or equivalent fail-safe pattern;
- introduce deterministic store generation/version/CAS semantics where needed;
- stale writers must fail/retry rather than overwrite newer lot state;
- partial multi-lot reservations must roll back after an injected crash/failure before commit;
- quarantined and incompatible lots remain unavailable under concurrent access;
- no FIXTURE auto-seed in normal STRICT_STOCK paths.

Use a small cross-platform lock abstraction compatible with both GitHub Actions Windows and Linux. Keep lock scope narrow. Do not create a database just to solve locking.

## Mandatory regressions

- subprocess race: scarce stock 10 sheets, multiple processes request >10 total -> consumed/reserved total never exceeds 10;
- two-process same WO idempotent retry -> one semantic reservation;
- injected failure after first lot staging -> restart shows all-or-nothing state;
- stale generation writer cannot overwrite a newer commit;
- restart conservation: `sheetCount == available + reserved + consumed` for every lot;
- tenant isolation remains true during concurrent races.

Label these as **REAL persistence/concurrency logic tests** but not factory throughput.

---

# Phase 437–444 — Manual Station Dispatch Boundary V1

Reuse the existing Scheduler/Queue. Add a **MANUAL_STATION** capability boundary for pilot execution. This is a dispatch/traveler workflow only, not machine control.

## Station model

A station may represent examples such as:

- PANEL_CUTTING_MANUAL;
- EDGE_BANDING_MANUAL;
- DRILLING_MANUAL;
- ASSEMBLY_MANUAL;
- PACKING_MANUAL;
- QC_MANUAL.

Required fields:

- `stationId`;
- `tenantId`;
- capabilities;
- status ONLINE/OFFLINE/PAUSED;
- heartbeat;
- current lease/job;
- operator/actor if supplied;
- no actuator endpoint.

## Dispatch contract

Reuse the existing queue/lease concepts:

- dispatch a WorkOrder traveler operation only when WorkOrder state permits it;
- dispatch item must pin `workOrderId`, `releaseId`, exact `releaseHash`, operation, and required material/QC lineage;
- stale/superseded release or cancelled WO cannot dispatch;
- offline station cannot receive a new lease;
- lease timeout/recovery must return the operation to a safe queue state without duplicating completion;
- ACK / START / COMPLETE are explicit human/operator acknowledgements;
- operation completion remains governed by WorkOrder state machine and QC requirements;
- no station adapter may execute machine commands.

## Tests

Cover same-tenant dispatch, cross-tenant denial, stale release, duplicate ACK, duplicate COMPLETE, offline station, lease expiry, restart/recovery, and one-operation-only ownership.

---

# Phase 445–452 — Operator Control Plane / Scan Workflow V1

Extend the existing Admin/API rather than building a second frontend stack.

Provide a tenant-scoped operator view for:

- WorkOrders waiting for manual operation;
- active station leases;
- required material lots and release hash;
- traveler steps;
- FINAL/in-process QC requirements;
- cartons / packing status;
- exceptions and rework state;
- audit journal link/export.

## Scan identifiers

Support deterministic scan tokens for at least:

- WorkOrder;
- MaterialLot;
- ManufacturingRelease packet;
- carton.

A scan token may be QR/barcode-friendly text, but barcode rendering/reader hardware itself remains **PARTIAL** unless real hardware is exercised.

Scanning must never mutate another tenant’s object. A token must resolve to an authoritative tenant/object pair; body-provided tenant must not override the authenticated/authoritative request tenant boundary already used by the Pilot API.

## Human confirmation

Destructive/irreversible pilot actions (consume material, complete final operation, finalize QC, complete WO) require an explicit operator action. Do not add unattended auto-complete.

Record actor/source in the journal.

---

# Phase 453–460 — Exception / Recovery State Machine V1

Use the existing WorkOrder/QC/MaterialLot states and add explicit recovery handling, not a parallel engine.

Required exception classes / deterministic recovery paths:

- material shortage;
- wrong material / thickness / dimensions / grain;
- quarantined receipt;
- stale/superseded ManufacturingRelease;
- QC FINAL failure;
- rework required;
- duplicate scan/idempotent retry;
- station offline/lease expired;
- partial packing / wrong carton count;
- process restart during reservation or operation acknowledgement.

For each class, define:

- error code;
- whether retry is safe;
- whether human intervention is required;
- allowed next WorkOrder states;
- what event is journaled;
- whether release/QC/material lineage remains valid.

No error path may silently flip to success.

Add an operator exception inbox in the existing Admin view with tenant filtering and stable identifiers.

---

# Phase 461–468 — Versioned Import / Export Contracts

Do not connect live providers in this phase. Build safe, versioned file/API contracts for later company-system integration.

## Imports

Keep the existing MANUAL/IMPORTED truth labels and add schema-versioned validation for:

- material receipts;
- supplier quote snapshots;
- carrier quote snapshots;
- optional inventory adjustment request that **must require explicit human approval** before changing lot state.

Invalid rows go to a rejected/quarantine result; no partial silent import.

## Exports

Provide deterministic tenant-scoped export bundles for:

- ManufacturingRelease packet metadata + checksums;
- WorkOrder traveler;
- reserved/consumed MaterialLot lineage;
- QC report/rework history;
- packing/carton manifest;
- shipment draft;
- audit journal slice.

Include schema version, export timestamp, tenant, releaseHash, content hashes, and truth labels.

Exports are documents/data only. They do not submit carrier bookings or machine jobs.

## Idempotency

Same import file/key retry must not double receive stock or duplicate supplier/carrier snapshots when the semantic idempotency key matches.

---

# Phase 469–474 — Pilot Observability / Reliability Dashboard V1

Add lightweight observability from the existing services. Do not require a new observability platform.

Expose tenant-safe counters/health for at least:

- queued/manual operations;
- active/expired station leases;
- WorkOrders by state;
- reservation conflict/shortage count;
- stale/superseded release rejects;
- QC pass/fail/rework counts;
- packing exceptions;
- journal integrity status;
- last successful REAL acceptance commit/generation;
- LIVE_CNC/LIVE_LASER = BLOCKED badges.

Where latency is measured, clearly label it local/runtime measurement. Do not describe FIXTURE timing as real factory SLA.

Add a deterministic `/api/pilot/health` or equivalent existing-admin endpoint with no cross-tenant data leakage.

---

# Phase 475–480 — Deployment Acceptance / Chaos Fixture / REAL Evidence Refresh

Create the new acceptance package without weakening or replacing the existing canonical evidence.

Suggested files:

- `docs/PILOT_DEPLOYMENT_ACCEPTANCE.md`
- `docs/PILOT_DEPLOYMENT_ACCEPTANCE.json`
- `docs/OPERATOR_CONTROL_ACCEPTANCE.md`
- `docs/OPERATOR_CONTROL_ACCEPTANCE.json`

Do not silently add new files to the existing canonical six-file reader unless the reader/version contract is explicitly migrated with backward/failure regressions. New Phase 421–480 acceptance can be an additional scoped truth set.

## Required FIXTURE stress

Run a deterministic **FIXTURE/CHAOS** test, not factory throughput, including at least:

- 100 WorkOrders;
- multiple tenants;
- multi-process scarce-stock contention;
- station offline/lease expiry;
- injected process restart during reservation;
- duplicate ACK/COMPLETE retries;
- QC fail -> rework -> final pass;
- stale release rejection;
- packing mismatch rejection;
- journal tamper detection negative test.

Acceptance must explicitly report:

- no oversell;
- material conservation;
- no cross-tenant object exposure;
- no duplicate semantic completion;
- journal integrity;
- stale release protection;
- human approval/control boundary intact;
- LIVE_CNC/LIVE_LASER still blocked.

Label this **FIXTURE/CHAOS**, not REAL factory throughput.

## REAL evidence refresh

Because the code SHA will change, rerun the existing clean-tree REAL Blender acceptance on the final code commit:

- 4/4 families;
- Blender 5.2.1 LTS + NVIDIA T1000 OptiX on the currently detected host, unless hardware legitimately changes;
- `usedMock=false`;
- exact final CODE_EVIDENCE_SHA;
- verifier PASS;
- non-null exact matching ManufacturingRelease `releaseHash`;
- artifact hash/size;
- shared acceptance generation where required by the existing runner.

If Blender/OptiX is unavailable at execution time, mark the REAL render slice BLOCKED; do not fall back to Mock and do not publish it as REAL.

---

# Required test / commit / evidence sequence

1. Implement Phase 421–480 without rewriting existing architecture.
2. Add targeted unit/integration/process-concurrency tests.
3. Run `pytest -q`; report exact count and label it MOCK/unit/integration/FIXTURE/REAL-logic as appropriate, never global Production Ready.
4. Commit code/tests first as a new **CODE_EVIDENCE_SHA**.
5. Push and require GitHub Actions ubuntu + windows GREEN on the code commit.
6. From a **clean committed tree**, run the scoped Phase 421–480 acceptance plus existing REAL 4-family Blender acceptance.
7. Commit evidence/docs separately where practical.
8. Require current-head GitHub Actions GREEN.
9. Update:
   - `docs/GROK_PROGRESS_REPORT.md`;
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`;
   - `docs/REAL_E2E_ACCEPTANCE.md` only with facts actually re-proven;
   - `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet evidence itself changes.
10. Leave Issue #1 a concise completion comment with CODE_EVIDENCE_SHA, docs SHA, pytest count, code/head CI run IDs, FIXTURE/CHAOS summary, REAL Blender summary, and unchanged truth labels.

---

# Phase 421–480 exit criteria

Do not claim this phase accepted unless all applicable items are true:

- durable tenant-scoped audit journal exists and restart/tamper tests pass;
- successful required business mutations cannot silently omit required audit evidence;
- multi-process STRICT_STOCK contention does not oversell;
- crash/restart preserves material conservation and atomic allocation semantics;
- stale writers cannot overwrite newer lot state;
- MANUAL_STATION dispatch uses the existing Queue/Scheduler boundary and has lease/recovery/idempotency tests;
- dispatch and operator actions pin exact `releaseHash`;
- no stale/superseded/cancelled WorkOrder can dispatch or complete;
- operator scan/control paths are tenant-safe;
- exception paths are fail-closed and journaled;
- imports are MANUAL/IMPORTED, versioned, validated, idempotent, and do not create live-provider claims;
- exports are deterministic/hashable and never actuate machines or book carriers;
- observability has tenant-safe status and no fake factory SLA claims;
- FIXTURE/CHAOS acceptance passes with explicit negative cases;
- code CI and current-head CI are GREEN on Ubuntu + Windows;
- clean-tree 4/4 REAL Blender evidence is bound to the final code SHA and exact release hashes;
- Vision / AI Video / Demand remain MOCK unless truly connected and proven;
- OS sandbox / AR / barcode / preflight / McKee remain PARTIAL unless separately proven;
- LIVE_CNC / LIVE_LASER / PLC / machine actuation remain BLOCKED;
- `globalProductionReady=false`;
- `liveFactoryExecutionReady=false`;
- `liveProviderReady=false`;
- `fullAutonomousFactoryReady=false`;
- no second Scheduler / ERP / WMS / MES / QMS / inventory engine is introduced.

When complete, stop and report to GitHub for re-review. Do not automatically start Phase 481+.