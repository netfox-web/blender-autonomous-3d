# Grok 下一輪開發指令：Phase 721–780 Manual Pilot Batch Execution & Commercial Launch Readiness V1 — ACCEPT WITH SCOPE

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `d3f4694be8e5e9f072bb73c008e2870a31f42c72`  
> Reviewed CODE_EVIDENCE_SHA: `70600377a94c1acf0d5dbbda79304c90c58076a0`  
> Review result: **ACCEPT WITH SCOPE**  
> Phase 661–720 canonical packaging/labor authority blockers are accepted. **You may enter Phase 721–780.**

## Accepted from Phase 661–720 — preserve and do not regress

- Canonical `packagingChecklistAuthority` now provides serialized existence proof. COMPLETE / launch-eligible rows resolve exactly one checklist by ID and fail closed on coordinated bogus IDs, missing/duplicate authority, blank/wrong tenant, wrong unit/hash, invalid/mismatched qty, or contradictory source.
- Canonical `laborAuthority` publishes durable labor authority. Verifier independently rebuilds semantic identities and totals; fake lineage, missing authority, duplicate semantic/idempotency identity, duplicate labor ID, wrong tenant/unit/hash, semantic mismatch, minutes mismatch, and unverifiable WorkOrder fallback fail closed.
- `_cost_qty_complete.ok` cannot be true when labor integrity is false; packaging quantity remains explicit and never falls back to an invented `1.0`.
- Existing hard-crash/idempotency behavior remains required: no duplicate durable labor semantic operation, no duplicate journal success, no open orphan outbox after reconciliation.
- Canonical generation `627491fc-5853-4c4d-8325-71d0eb406d5c` is clean-tree and bound to CODE `70600377…`; fixture path remains `physicalPrototypeValidated=false`, `launchDecision=WAITING_HUMAN_EVIDENCE`, cost PARTIAL.
- `pytest -q` = **451 passed**. GitHub Actions CODE run `34440014565` on exact `7060037…` and docs/head run `34440405392` on exact `d3f4694…` are GREEN on Ubuntu + Windows. CI uses `FOX3D_MOCK_BLENDER=1`; this is MOCK/unit/integration + FIXTURE/REAL_LOGIC evidence, **not Production Ready**.
- Prior REAL Blender evidence remains scoped-valid from `7a87ea5`: 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`. Reuse only while render/engineering/media paths remain unchanged and verifier still passes.
- Demand / Vision / AI Video = **MOCK**. OS sandbox / AR / preflight / barcode / McKee-BCT = **PARTIAL**. LIVE_CNC / LIVE_LASER / PLC / live provider / automatic live factory = **BLOCKED**.
- `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `liveMachineControl=false` remain mandatory.
- Do not touch `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet truth actually changes.

## Architecture rule

Extend the existing platform. **Do not rewrite or fork** Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / EventJournal / Outbox / Backup. Add only the minimum batch-level aggregates, projections, validators, adapters, API/view surfaces, and tests required below.

Automated fixture acceptance may prove software behavior, but it must never manufacture physical evidence or authorize production. No fixture may become `HUMAN_BATCH_GO` or global Production Ready.

---

# Phase 721–726 — PilotBatchSpec + exact launch gate

Create a durable tenant-scoped `PilotBatch` / `PilotBatchSpec` using existing persistence conventions.

Required fields should include at least:
- batchId, tenantId, source candidate/SKU identity;
- exact selectionId / prototypeUnitId lineage where applicable;
- engineeringHash, canonicalHash, bomHash, nestingHash, rankingPolicyHash;
- accepted ECO revision / engineering revision;
- source Human Launch Decision ID and evidence package IDs;
- requested quantity, createdBy operator/shift, timestamps;
- truth/evidence label and state.

Creation must fail closed unless the source SKU is genuinely eligible under existing Human Launch governance. For MANUAL/IMPORTED production-like path require `HUMAN_GO`, exact current engineering/ECO lineage, finalized authoritative evidence, and no stale/superseded release. FIXTURE may create an explicitly FIXTURE pilot batch only for software acceptance, but must not inherit `HUMAN_GO`, authorize machine control, or set physical validation true.

Batch states should be explicit, e.g. `PLANNED`, `WAITING_HUMAN_RELEASE`, `RELEASED_FOR_MANUAL_PILOT`, `IN_PROGRESS`, `HOLD`, `REWORK`, `COMPLETED_PENDING_REVIEW`, `READY_FOR_HUMAN_BATCH_GO_NO_GO`, `HUMAN_BATCH_GO`, `HUMAN_BATCH_NO_GO`. Do not overload existing WorkOrder status.

# Phase 727–732 — Batch material / hardware / packaging plan with exact lineage

Reuse MaterialLot, existing strict stock rules, Nesting/Remnant and WorkOrder reservations. Add a batch projection/plan, not a second inventory system.

For each batch/unit prove:
- exact material/spec compatibility (SKU/material/thickness/grain/size as applicable);
- reservation IDs and consumed quantities;
- no double reservation/consume after retry/restart;
- partial shortage rolls back cleanly;
- reusable remnant vs true scrap remains conserved;
- explicit hardware quantity and packaging quantity authority, never inferred defaults;
- tenant isolation for lots, remnant, checklist and WorkOrder references.

Batch aggregate totals must recompute from authoritative unit/lot data rather than trusting cached booleans.

# Phase 733–738 — MANUAL_STATION batch execution

Reuse Operator/Shift, traveler, scan, ManufacturingRelease and WorkOrder paths. This phase is **manual station orchestration only**.

Add durable unit execution identity for every batch quantity (serial/unitExecutionId). Require unique IDs and exact batch/SKU/release lineage. Persist state transitions and semantic idempotency so process restart cannot duplicate unit starts, material consume, labor, QC, packing, or completion.

No path may call or imply LIVE_CNC, LIVE_LASER, PLC, autonomous machine dispatch, or booked external production. `liveMachineControl` remains false.

# Phase 739–744 — Unit genealogy + QC sampling / full-unit exceptions

Build batch genealogy from existing WorkOrder/QC data:
- batchId → unitExecutionId → material lot/reservation/consume → operator/shift → labor → QC → packaging → evidence package;
- pin QC plan/hash to exact engineering/release revision;
- configurable sampling plan may reduce which units receive full checks, but every rejected/exception unit must remain individually traceable;
- missing required sampled result, failed FINAL QC, unresolved hold, or stale QC plan blocks batch readiness;
- record defect/rework/scrap/remnant outcome per affected unit.

Label the sampling plan as operational/configuration logic unless backed by a real certification/statistical program. Do not claim ISO/AQL certification or process capability merely because sampling code exists.

# Phase 745–750 — Packaging / carton / handoff execution

Reuse packaging checklist, DAM and shipment-draft/logistics boundaries.

For packed units/cartons capture durable:
- carton/package ID;
- unitExecutionIds contained;
- explicit packaging quantity;
- measured L/W/H and packed weight;
- part/hardware expected vs observed count;
- damage/defect check;
- authoritative PACKAGING DAM evidence for real/manual evidence path;
- packaging checklist ID + tenant/unit/batch/engineering lineage.

Prevent duplicate unit placement in multiple active cartons and cross-tenant/cross-batch injection. Carrier data remains IMPORTED/MANUAL unless a real provider exists. Shipment remains DRAFT/HANDOFF; do not call it booked or delivered without authority.

# Phase 751–756 — Actual batch cost & variance

Aggregate actual cost only from existing authoritative quantity sources:
- MaterialLot consumed quantity / true scrap / remnant credit;
- durable labor authority and rework labor;
- hardware quantity;
- packaging quantity;
- approved external processing where evidence exists;
- shipping/provider costs only when MANUAL/IMPORTED/REAL_PROVIDER authority is present.

Store currency/source/truth label. Separate quantity from money. Missing required quantity or amount => `PARTIAL`, never zero/inferred. Produce estimate-vs-actual variance per unit and per batch. Do not allow four manually supplied monetary totals alone to make the batch COMPLETE.

# Phase 757–762 — Nonconformance / CAPA / ECO feedback loop

Extend existing Hold/Rework/Scrap/ECO behavior; do not introduce a second engineering source of truth.

Record nonconformance categories and evidence. Root-cause text is MANUAL/IMPORTED unless there is real authoritative analysis; AI suggestions must not become engineering facts automatically.

If a physical issue requires design change:
- create/accept ECO through the existing path;
- generate a new engineeringHash/revision;
- invalidate stale batch/release/QC/packaging lineage as appropriate;
- require revalidation before further release;
- never silently edit an approved engineering definition in place.

# Phase 763–768 — Human batch decision board

Add a tenant-scoped Human Batch Decision board with explicit states:
- `WAITING_HUMAN_EVIDENCE`
- `HOLD_REWORK`
- `READY_FOR_HUMAN_BATCH_GO_NO_GO`
- `HUMAN_BATCH_GO`
- `HUMAN_BATCH_NO_GO`

Readiness must be recomputed from authoritative batch truth: lineage current, requested vs executed counts, inventory conservation, labor integrity, QC/sample completion, unresolved holds, packaging completeness, actual-cost completeness, DAM evidence requirements, accepted ECO state, and no stale release.

Only an authorized human/manual actor may issue GO/NO-GO. Fixture/Mock path can exercise the decision engine but must remain waiting/hold and cannot produce `HUMAN_BATCH_GO`.

`HUMAN_BATCH_GO` means only “human-approved manual pilot batch result within this scoped workflow.” It does **not** mean live factory, regulatory certification, commercial shipment booked, or global Production Ready.

# Phase 769–774 — Durability, crash recovery, backup/restore, tenant isolation

All new batch state must follow the existing durable EventJournal/Outbox/idempotency conventions.

Add subprocess `os._exit` crash/restart regressions at critical boundaries, including at minimum:
- batch creation/release;
- unit start and material reservation/consume;
- labor/operation completion;
- QC result persist;
- carton assignment/packing;
- Human Batch GO decision.

For each, cover crash after durable business persist before journal completion and after journal/outbox completion before outer idempotency return where applicable. Restart/retry must reconcile to exactly one semantic operation, no duplicated stock consume, no duplicated unit/carton/labor/QC, and zero orphan open outbox after recovery.

Extend tenant backup/restore digest/exact-set checks to batches, unit genealogy, QC, cartons, decisions and new semantic keys. Prove tenant-A restoration has zero tenant-B data leakage and corruption remains detectable rather than silently normalized.

# Phase 775–780 — Canonical acceptance, CI, truthful readiness

Add runner-generated canonical acceptance artifacts, suggested names:
- `docs/PILOT_BATCH_EXECUTION_ACCEPTANCE.md` + `.json`
- `docs/COMMERCIAL_LAUNCH_READINESS_ACCEPTANCE.md` + `.json`

Use a clean-tree CODE_EVIDENCE_SHA and atomic/fail-closed publication consistent with existing canonical acceptance architecture. The serialized truth itself must contain enough authoritative lineage to independently verify batch/unit/lot/labor/QC/packaging/decision identities after serialization.

Automated acceptance should exercise at least the 4 selected SKU families through a nontrivial FIXTURE pilot batch (e.g. 5–10 units per selected SKU) to prove logic and restart/integrity behavior. Clearly label it FIXTURE/REAL_LOGIC; it is not factory throughput or a real physical batch.

Scoped readiness flags may include:
- `pilotBatchExecutionReady = FIXTURE / REAL_LOGIC` for automated acceptance;
- `commercialLaunchGovernanceReady = FIXTURE / REAL_LOGIC` for software governance;
- `physicalPilotBatchValidated = false` unless genuine authoritative physical/manual evidence is actually supplied.

Always retain:
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`
- `liveProviderReady=false`
- `liveMachineControl=false`

---

## Required negative regressions

At minimum prove fail-closed behavior for:

1. Pilot batch creation without valid `HUMAN_GO` on real/manual path.
2. Stale/superseded engineeringHash, ECO revision, ManufacturingRelease or evidence package.
3. Duplicate batch ID / unitExecutionId / semantic operation identity.
4. Partial material shortage with full rollback and no phantom consume.
5. Crash/restart cannot double reserve/consume material or reuse a consumed reservation incorrectly.
6. Cross-tenant lot, WorkOrder, labor, QC, carton, DAM, checklist or batch reference.
7. Duplicate semantic labor / duplicate operation completion does not double actual cost.
8. Missing required QC sample, failed FINAL QC or unresolved hold prevents batch GO.
9. Packaging qty/checklist authority missing, stale or contradictory prevents COMPLETE/GO.
10. Same unit assigned to two active cartons or carton from wrong batch/tenant.
11. Cost money present without authoritative quantities remains PARTIAL.
12. Fixture/Mock evidence cannot be upgraded to physical validation or `HUMAN_BATCH_GO`.
13. Accepted ECO invalidates stale batch/release/QC/packaging lineage until revalidated.
14. Hard crash around business persist / journal / outbox / idempotency reconciles to exactly one semantic result.
15. Backup/restore exact-set mismatch, duplicate semantic keys or tenant leakage fails closed.

## Evidence / delivery requirements

1. Implement only Phase 721–780 on top of existing architecture. No architecture rewrite.
2. Run full `pytest -q`; report exact count and explicitly label it MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
3. Commit implementation/tests first as a new CODE_EVIDENCE_SHA. Require Ubuntu + Windows GitHub Actions SUCCESS on that exact SHA.
4. Generate canonical Phase 721–780 evidence from the runner on a clean tree, bound to that exact CODE SHA. No hand-edited PASS JSON.
5. Reuse prior REAL Blender `7a87ea5` only if render/engineering/media code paths remain unchanged and verifier still passes. If those paths change, refresh REAL Blender evidence instead.
6. Run tenant-A backup/restore semantic and exact-set validation for all new batch state; prove zero tenant-B leakage.
7. Commit evidence/docs separately and require Ubuntu + Windows SUCCESS on the docs/head commit.
8. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, plus the new Phase 721–780 acceptance docs. Do not touch `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet truth changes.
9. Issue #1 completion handoff must include CODE SHA, docs SHA, pytest count, both Actions run IDs, acceptance generation, batch counts, key crash/idempotency results, backup/tenant result, REAL Blender reused/refreshed result, and remaining REAL/MOCK/PARTIAL/BLOCKED boundaries.
10. **Stop for ChatGPT re-review after Phase 780. Do not enter Phase 781+ until the next ACCEPT WITH SCOPE.**
