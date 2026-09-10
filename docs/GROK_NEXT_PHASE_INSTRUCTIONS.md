# Grok 修正指令：Phase 721–780 Re-Gate — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `1a4d4ce24f540fb0edb31afe0748523a589b7590`  
> Reviewed CODE_EVIDENCE_SHA: `0ecc1a253767df4ce88da7cb080ab6ff98700790`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 781+.** Fix only the Phase 721–780 integrity gaps below. Do not rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / EventJournal / Outbox / Backup.

## Accepted this round — preserve these behaviors

- Phase 721–780 landed as an extension rather than an architecture rewrite.
- FIXTURE path remains explicitly non-production: `physicalPilotBatchValidated=false`, `batchLaunchDecision=WAITING_HUMAN_EVIDENCE`, `liveMachineControl=false`, and all global/full/live readiness flags remain false.
- Current canonical generation `8c6aa9d1-8cb6-47ee-9ec1-b0ab70695db5` is bound to CODE `0ecc1a2…`; current fixture scope is 4 SKUs × 5 unitExecutionIds.
- `pytest -q` reported **467 passed**. GitHub Actions CODE run `34443913394` on exact `0ecc1a2…` and docs/head run `34444205516` on exact `1a4d4ce…` are GREEN on Ubuntu + Windows. CI uses `FOX3D_MOCK_BLENDER=1`, therefore this is MOCK/unit/integration + FIXTURE/REAL_LOGIC evidence, **not Production Ready**.
- Prior REAL Blender evidence may continue to reuse `7a87ea5` 4/4 Blender 5.2.1 + NVIDIA T1000 OptiX only while render/engineering/media paths remain unchanged and the existing verifier still passes.
- `docs/CABINET_REAL_ACCEPTANCE.md` has no truth change; do not edit it merely to refresh dates.

---

# Blocker 1 — Canonical pilot-batch acceptance is currently fail-open

The current runner regression `_passing()` can return `rc == 0` with `cartons=[]`, an empty `board.rows`, no serialized QC authority, no material/consume authority, no cost authority, and only minimal batch/unit ID authority. That is not sufficient for the Phase 775–780 requirement that the serialized truth independently prove batch/unit/lot/labor/QC/packaging/decision identities.

## Required correction

Strengthen `validate_pilot_batch_acceptance_result()` and the published `batchAuthority`/canonical payload so a serialized/post-publish document can independently re-derive the truth instead of trusting precomputed booleans.

At minimum publish and verify authoritative records for:

1. **Batch authority** — exact batch ID set and exact tenant/candidate/selection/prototypeUnit/engineeringHash/canonicalHash/bomHash/nestingHash/rankingPolicyHash/releaseId/releaseHash/workOrderId/requestedQuantity/source/truthLabel.
2. **Unit authority** — exact unitExecutionId set; exact tenant/batch/engineering/release/workOrder lineage; sequence uniqueness; execution state; material allocation/consume lineage; labor/QC/carton references.
3. **Material authority** — existing WorkOrder + reservation/MaterialLot consume identifiers and quantities. If one batch-level consume is allocated across units, label it explicitly as an allocation projection and prove the sum of unit allocations equals authoritative WorkOrder consumed quantity; do not present an inferred equal share as a direct physical per-unit consume fact.
4. **Labor authority** — exact durable labor rows + semantic keys; verify no duplicate semantic identity and verify required executed-unit coverage, not merely “some labor exists in the batch.”
5. **QC authority** — exact QC rows for required sampled units, FINAL stage, tenant/unit/batch/engineering/release/qcPlanHash lineage and pass/fail result.
6. **Packaging authority** — exact carton set, exact unit coverage, checklist identity/tenant/batch/engineering lineage, explicit quantity when required, measurements/counts/damage result, and authoritative PACKAGING DAM lineage on MANUAL/IMPORTED physical evidence path.
7. **Cost authority** — exact cost record and quantity lineage; COMPLETE must be independently recomputable from authoritative quantity sources. FIXTURE may remain PARTIAL.
8. **Decision/board authority** — board rows must cover the exact batch set; each row must resolve to its batch and authoritative decision record/state. Empty or missing rows must fail.

The verifier must compare **exact sets**, not subset membership. Coordinated mutation of both a summary row and its copied authority to the same bogus value must still fail if there is no underlying authoritative record.

## Mandatory negative runner regressions

Turn the current permissive fake-passing shape into failures and add at least:

- `cartons=[]` while units claim PACKED → fail.
- `board.rows=[]` with 4 batches → fail.
- missing QC authority / missing sampled FINAL QC → fail.
- missing material/consume authority → fail.
- missing labor authority or one labor row covering only one of several executed units → fail.
- batch/unit field mismatch against authority → fail.
- unit list has correct count but wrong batch/tenant/hash/release/WO lineage → fail.
- coordinated bogus carton/checklist/QC/labor/material IDs in both summary and copied lineage → fail because authority lookup does not exist.
- duplicated/missing unit in canonical carton coverage → fail.

Keep one **truly complete** serialized fixture as the positive runner regression.

---

# Blocker 2 — Human Batch GO runtime gates are too weak for QC, packaging and unit execution

Current runtime can treat packaging as acceptable when every unit merely has a carton and `packagingQty` is truthy. `pack_units()` does not fail closed on invalid/missing L/W/H/weight, wrong part/hardware counts, damage/defect, or stale/wrong checklist lineage. `record_qc()` accepts arbitrary `stage`, while readiness only checks `qcId + ok=true`; a non-FINAL PASS can therefore stand in for required FINAL QC. `counts_ok` currently compares requested quantity to the number of unit records, not to completed execution evidence, and batch labor integrity only proves that at least one unique labor row exists somewhere in the batch.

## Required correction

### A. QC

- For every sampled unit required by the pinned sampling plan, readiness must resolve a **FINAL** QC row.
- FINAL QC must have non-empty `qcPlanHash` and exact match to the current WorkOrder/release-pinned plan/hash and exact tenant/batch/unit/engineering/release lineage.
- An IN_PROCESS/PRECHECK PASS must never satisfy FINAL QC.
- Missing sampled FINAL, failed FINAL, duplicate conflicting FINAL, stale plan/hash, unresolved HOLD/NCR => block readiness/HUMAN_BATCH_GO.
- Do not silently overwrite evidence by keeping only one opaque `qcId` if multiple stages exist; publish enough durable QC identity/history to verify the final result.

### B. Packaging

For MANUAL/IMPORTED launch-eligible paths, a carton can contribute to `packagingOk` only when:

- L/W/H and packed weight are finite and > 0;
- explicit packaging quantity is finite and > 0 and resolves to the current authoritative checklist/unit/batch/engineering lineage;
- observed part count and hardware count are present and meet the expected/current BOM requirement, otherwise HOLD;
- damage/defect result is explicitly acceptable; any damage/defect/missing result blocks GO;
- required PACKAGING DAM evidence is authoritative and passes existing tenant/SHA/size/role checks;
- every unit is in exactly one active carton and no cross-tenant/cross-batch unit is admitted.

Do not infer missing measurements or counts. Fixture data may exercise the code but must remain labelled FIXTURE and cannot upgrade physical readiness.

### C. Unit execution completeness / genealogy

`HUMAN_BATCH_GO` readiness must require requested quantity == exact unit set == **executed/eligible unit set**, not merely “unit records were created.” For each required unit prove, as applicable:

- unit started under valid operator/shift;
- material authority is present and the unit’s allocated/consumed lineage is non-null and conservation-valid;
- required labor authority exists for that unit and semantic identity is unique;
- sampled FINAL QC is complete/pass (and any exception unit remains individually traceable);
- packed/carton lineage is valid;
- no HOLD/REWORK/NCR remains unresolved.

`pack_units()` must not be a shortcut that turns a PLANNED or otherwise incomplete unit into PACKED while bypassing required execution evidence.

Add a manual-path regression showing that “all unit records exist + one labor row + QC IDs + cartons” cannot become READY/HUMAN_BATCH_GO unless every required unit has the complete authoritative chain.

---

# Blocker 3 — Required hard-crash coverage is not yet demonstrated

The Phase 769–774 instruction required **subprocess `os._exit` crash/restart regressions** at the critical batch boundaries. The current new tests mainly use in-process `CrashInjected` for unit start/consume. `crashfix.py` exposes some pilot-batch actions, but there is not complete subprocess coverage for batch creation/release, unit start/reserve/consume, labor/operation, QC, carton packing and HUMAN_BATCH_GO.

## Required correction

Extend the existing crash helper only; do not build a second durability system. Add real child-process `os._exit` regressions for at least:

1. PilotBatch create.
2. Batch manual release.
3. Unit start.
4. Material reservation and consume.
5. Labor/operation completion.
6. QC FINAL persist.
7. Carton assignment/packing.
8. HUMAN_BATCH_GO decision.

For each applicable boundary test both:

- crash after durable business persist but before journal completion;
- crash after journal/outbox completion but before the outer idempotent call returns.

After restart + retry prove:

- exactly one business semantic record;
- exactly one intended semantic journal result;
- zero orphan PREPARED/open outbox after reconciliation;
- no duplicate reservation/consume/labor/QC/carton/decision;
- no duplicate unit placement or cost inflation;
- stock conservation remains exact.

A helper action existing without a subprocess regression is **not** acceptance evidence.

---

# Re-Gate evidence requirements

1. Fix only these Phase 721–780 blockers. **Do not start Phase 781+.**
2. Add the negative regressions above before changing readiness claims.
3. Run full `pytest -q`; report the new exact count and label it MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
4. Commit implementation/tests first as a new **CODE_EVIDENCE_SHA**. Require Ubuntu + Windows GitHub Actions SUCCESS on that exact SHA.
5. Re-run the Phase 721–780 canonical runner on a clean tree bound to that exact CODE SHA. The post-serialized and post-publish verifier must reject the incomplete/tampered shapes above.
6. Keep `physicalPilotBatchValidated=false` and no `HUMAN_BATCH_GO` in canonical fixture evidence.
7. Re-run tenant-A backup/restore exact-set + semantic checks for all new authority/state and prove zero tenant-B leakage.
8. Reuse prior REAL Blender `7a87ea5` only if render/engineering/media paths remain unchanged and verifier passes; otherwise refresh REAL Blender evidence.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, `docs/PILOT_BATCH_EXECUTION_ACCEPTANCE.md/.json`, and `docs/COMMERCIAL_LAUNCH_READINESS_ACCEPTANCE.md/.json`. Do not touch `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet truth actually changes.
10. Commit runner-generated evidence/docs separately and require Ubuntu + Windows SUCCESS on that docs/head SHA.
11. Issue #1 handoff must include CODE SHA, docs SHA, pytest count, both Actions run IDs, generation ID, authority/exact-set results, QC/packaging/manual-GO negative results, subprocess crash matrix results, backup/tenant result, prior REAL Blender verification, and remaining REAL/MOCK/PARTIAL/BLOCKED boundaries.
12. **Stop for ChatGPT re-review.**

## Boundary labels that must remain

- Batch workflow / genealogy / governance code: **REAL_LOGIC** only where verified.
- Current automated pilot batch: **FIXTURE / REAL_LOGIC**, not a physical batch.
- Prior Blender media: **REAL** only for the verified `7a87ea5` scope.
- Demand / Vision / AI Video: **MOCK**.
- OS sandbox / AR / preflight / barcode / McKee-BCT: **PARTIAL**.
- LIVE_CNC / LIVE_LASER / PLC / live provider / automatic live factory: **BLOCKED**.
- `physicalPilotBatchValidated=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `liveMachineControl=false` until genuinely authoritative evidence changes those scoped truths.
