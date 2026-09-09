# Grok 下一輪開發指令：Phase 661–720 — Physical Prototype Evidence & Human Launch Governance V1

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `b3f3f95e91aee85962cbac5491aecfd5b39b7081`  
> Reviewed CODE_EVIDENCE_SHA: `e66ca9dc0383804b4d90547afe03c19b10d78b3b`  
> ChatGPT review result: **ACCEPT WITH SCOPE**  
> Phase 601–660 final integrity gate is cleared. **Phase 661–720 is now allowed.**

## Review result / evidence accepted

The two remaining Phase 601–660 blockers are materially resolved and may be preserved as the baseline:

- Published canonical `selected[]` / `units[]` / `matrix[]` / exact `selectedBoard[]` now carry non-null `candidateId`, `selectionId`, `prototypeUnitId`, `engineeringHash`, `canonicalHash`, `bomHash`, `nestingHash`, and `rankingPolicyHash`; missing/empty/mismatch is fail-closed.
- The runner re-validates the serialized canonical document before publication and re-reads/re-validates the actually published truth set; publication failure or semantic failure restores/refuses overwrite of the prior good bundle.
- `inventoryIntentId` reuse now validates immutable tenant/unit/work-order/idempotency/quantity/material/thickness/grain/length/width identity; duplicate identity is HOLD and mismatched retries cannot allocate replacement stock.
- New negative regressions cover quantity mismatch, requirement mismatch, wrong-unit pointer, duplicate identity, malformed intent, lineage omissions/empty values/duplicates, and serializer-drop rollback. Tenant identity is part of the immutable match contract and must remain fail-closed.
- `pytest -q`: **395 passed** under MOCK Blender / unit / integration + FIXTURE/REAL_LOGIC. This is **not Production Ready** evidence.
- GitHub Actions CODE run `34382810521`: Ubuntu + Windows GREEN on exact CODE `e66ca9d`.
- GitHub Actions docs/head run `34383218796`: Ubuntu + Windows GREEN on exact docs head `b3f3f95`.
- Canonical generation: `10207d34-fd27-4f73-9d68-0a0cb6dbb76f`; `workingTreeClean=true`; `evidenceCommitMatchesHead=true`; `physicalPrototypeValidated=false`.
- Prior REAL Blender evidence remains valid for the unchanged render/media/engineering path: 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, per-case job/hash/size/GPU lineage on CODE `7a87ea5`.
- Current truth boundaries are correct and must stay explicit: Demand / Vision / AI Video = **MOCK**; OS sandbox / AR / preflight / barcode / McKee-BCT = **PARTIAL**; LIVE_CNC / LIVE_LASER / PLC / live provider / live factory execution = **BLOCKED**; commercial provider data remains CONFIG/IMPORTED/MANUAL where applicable; all global/full/live readiness flags remain `false`.

Do **not** rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD registry / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup. Extend the existing stores, transaction/outbox/journal, tenant isolation, canonical atomic publication, and fail-closed acceptance mechanisms.

---

# Goal

Turn the existing software-only prototype loop into a **truthful physical-prototype evidence intake and human launch-governance layer**.

This phase must **not fabricate physical prototypes**. If no genuine human/physical evidence is supplied, the correct result at the end of Phase 720 is still:

- `physicalPrototypeValidated=false`
- `launchDecision=WAITING_HUMAN_EVIDENCE` (or equivalent explicit HOLD state)
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`
- `liveProviderReady=false`
- `liveMachineControl=false`

A FIXTURE can prove the software gate works; it can never upgrade itself to `MANUAL_EVIDENCE`, `PHYSICAL_REAL`, or Production Ready.

---

## Phase 661–668 — PhysicalEvidencePackage V1

Add a durable tenant-scoped evidence package for a selected prototype unit. Reuse the existing PrototypeUnit, operator/shift identity, DAM, journal/outbox, and backup framework.

Minimum immutable lineage:

- tenantId
- candidateId
- selectionId
- prototypeUnitId
- engineeringHash
- canonicalHash
- bomHash
- nestingHash
- rankingPolicyHash
- engineering revision / ECO revision
- evidencePackageId
- evidenceSource (`FIXTURE`, `MANUAL_EVIDENCE`, `IMPORTED_EVIDENCE`; do not invent REAL)
- operatorId + shiftId when source is manual
- createdAt / finalizedAt

Rules:

1. A fixture actor cannot create `MANUAL_EVIDENCE`.
2. Cross-tenant unit/evidence/DAM references fail closed.
3. Evidence for an old engineering/ECO revision cannot validate a newer revision.
4. Finalized packages are append-only/immutable; correction creates a new revision/supersession record, never silent overwrite.
5. Every state-changing action is journaled using existing durability mechanisms.

## Phase 669–676 — As-built measurement + QC evidence intake

Implement authoritative manual observation intake without auto-generating PASS values.

Required observation domains for a physical prototype candidate should include, where applicable:

- assembled width/depth/height
- assembled weight
- assembly time
- hardware completeness/count
- panel/edge finish observation
- wobble/stability observation
- door/drawer fit observation
- missing part / wrong part
- defect count/severity
- rework count and rework references
- operator notes
- required DAM photo/document evidence references

Requirements:

- Measurement values must be numeric/finite and validated against the pinned tolerance policy.
- Required DAM references must be authoritative: same tenant, existing asset, stored SHA-256 + size, not caller-supplied fake metadata.
- `PASS_AS_BUILT` is only possible for genuine manual evidence and complete required observations.
- Any required tolerance/QC failure => HOLD/REWORK, never auto-pass.
- A FIXTURE may exercise all code paths but must remain `FIXTURE`, with `physicalPrototypeValidated=false`.

## Phase 677–684 — Actual material / labor / cost reconciliation V2

Use existing sources rather than a second ledger:

- Material actuals from authoritative MaterialLot consume/reservation lineage.
- Labor actuals from existing append-only labor segments/corrections.
- Packaging actuals from the physical evidence package.
- Hardware/other monetary actuals only from explicit MANUAL/IMPORTED monetary observations.

Keep quantity and currency dimensions separate. Never sum minutes/counts into money.

Produce, per prototype:

- estimate snapshot hash
- actual material qty/value
- actual labor minutes/value
- hardware actual qty/value
- packaging actual qty/value
- other explicit cost lines
- total monetary actual only when required money categories are complete
- variance by category and total
- `costCompleteness = COMPLETE | PARTIAL`

Missing required monetary evidence => PARTIAL and blocks GO. No payment/accounting/provider integration is implied.

## Phase 685–692 — Packaging / handling pilot evidence

Extend existing packaging validation with physical/manual evidence while keeping certification claims honest.

At minimum capture:

- observed carton L/W/H
- observed packed weight
- volumetric weight from configured policy
- part count expected vs packed
- hardware count expected vs packed
- package damage/defect observation
- packer/operator identity
- photo/document DAM refs
- assembly/packout timing if observed

Do **not** label an internal manual handling/drop observation as ISTA or certified transit testing unless an actual certified test report is supplied. Such observations are `MANUAL_EVIDENCE`, not certification.

Prediction-vs-observed variance must remain fail-closed using the pinned packaging policy hash.

## Phase 693–700 — Physical feedback → ECO closed loop V2

Connect real/manual prototype findings to the existing ECO path without bypassing engineering authority.

Required flow:

`physical issue → change request → explicit parameter/change payload → engineering revision → recompute geometry/BOM/nesting/cost/packaging lineage → invalidate stale evidence → require new prototype evidence`

Rules:

- No-op or invalid ECO is rejected.
- Old measurement/QC/package/cost evidence cannot validate the new engineeringHash/revision.
- Preserve append-only fieldChanges/reason/operator lineage.
- If this phase changes the engineering/render path, fresh REAL Blender evidence is required; otherwise the prior `7a87ea5` verifier may be reused.

## Phase 701–708 — Human launch decision board

Create an explainable launch-governance board for the four selected prototypes.

Decision states should be explicit, e.g.:

- `WAITING_HUMAN_EVIDENCE`
- `HOLD_REWORK`
- `READY_FOR_HUMAN_GO_NO_GO`
- `HUMAN_GO`
- `HUMAN_NO_GO`

The system may calculate readiness, but **GO/NO-GO is a human decision**. Demand is still MOCK and cannot upgrade a decision.

For every selected SKU, board must show exact lineage and at least:

- physical evidence completeness/status
- tolerance + QC status
- rework/open issue status
- actual-cost completeness and variance
- packaging evidence/status
- current ECO/revision status
- REAL Blender media lineage (prior or fresh)
- blockers and reasons
- human decision actor/time/reason when a decision exists

No fixture may reach HUMAN_GO. No missing/partial required evidence may reach `READY_FOR_HUMAN_GO_NO_GO`.

## Phase 709–714 — Manual pilot batch plan, no actuator

For a SKU that has an authorized HUMAN_GO only, produce a **manual pilot batch plan** using existing ManufacturingRelease / WorkOrder / MANUAL_STATION boundaries.

Include:

- release/revision pin
- quantity
- required material/lot planning
- operator/station plan
- QC checkpoints
- packing/handoff plan
- expected vs actual tracking hooks

This is planning/manual execution only. Do not send CNC, laser, PLC, carrier booking, payment, or provider commands. LIVE_CNC/LASER/PLC stay BLOCKED.

If no genuine HUMAN_GO exists, the correct result is a blocked/not-created pilot batch with a clear reason.

## Phase 715–718 — Durability, backup/restore, tenant isolation

Any new durable evidence package, decision, revision, cost/packaging evidence, and pilot-plan state must join the existing tenant backup/restore semantic contract.

Required regressions:

- Tenant A backup contains exact A evidence/decisions and zero B leakage.
- semantic digest / exact identity survives restore.
- finalized evidence immutable across restart.
- duplicate/idempotent submission does not duplicate observations or decisions.
- crash/restart between PREPARED and COMMITTED states reconciles through existing transaction/journal path.
- stale/wrong-revision/cross-tenant evidence remains blocked after restore.

Do not create a separate backup architecture.

## Phase 719–720 — Canonical acceptance + CI

Add canonical acceptance for this phase, suggested names:

- `docs/PHYSICAL_PROTOTYPE_EVIDENCE_ACCEPTANCE.json/.md`
- `docs/HUMAN_LAUNCH_GATE_ACCEPTANCE.json/.md`

Use the existing atomic/shared-generation publication and clean-HEAD binding.

Acceptance must prove the software/evidence gates fail closed. It must **not** require or fabricate a real physical build on CI.

Canonical top-level truth must explicitly include:

- CODE_EVIDENCE_SHA
- clean-tree / exact-head match
- acceptance generation ID
- exact four selected lineage
- evidence source for every selected SKU
- `physicalPrototypeValidated`
- launch decision state
- cost completeness
- packaging/QC/tolerance status
- prior/fresh REAL Blender verification
- tenant backup semantic result
- REAL/MOCK/PARTIAL/BLOCKED matrix
- all global/full/live readiness flags

If only FIXTURE evidence exists, acceptance may be `ok=true` for **software gate correctness**, while `physicalPrototypeValidated=false` and `launchDecision=WAITING_HUMAN_EVIDENCE`. These meanings must not be conflated.

---

# Required fail-closed regressions

Add strong negative tests, at minimum:

1. fixture actor attempts `MANUAL_EVIDENCE` → reject;
2. cross-tenant prototype/evidence/DAM reference → reject;
3. missing/wrong DAM hash or nonexistent authoritative asset → reject;
4. stale engineeringHash/revision evidence after ECO → reject;
5. missing required measurement or NaN/Inf/non-numeric value → reject;
6. out-of-tolerance dimension/weight/assembly result → HOLD, not validated;
7. failed QC/defect/open rework → HOLD;
8. partial required actual-cost evidence → cannot become launch-ready;
9. packaging missing/malformed/variance failure → cannot become launch-ready;
10. MOCK demand attempts to upgrade GO → reject;
11. fixture evidence attempts HUMAN_GO → reject;
12. HUMAN_GO without exact selected/unit/evidence/revision lineage → reject;
13. old evidence reused after ECO → reject;
14. duplicate manual submission/decision → idempotent or explicit conflict, never duplicate side effects;
15. cross-tenant / stale evidence remains blocked after restart + backup restore;
16. serializer drops a required physical-evidence/decision lineage field → post-publication validation fails and prior good truth set remains intact.

---

# REAL / MOCK / PARTIAL / BLOCKED policy for this round

Preserve honest labels:

- Blender 5.2.1 + T1000 OptiX evidence previously accepted on `7a87ea5`: **REAL render evidence**, reusable only if render/engineering/media path stays unchanged and verifier passes.
- Prototype workflow, evidence validation, ECO, durability, decision logic: **REAL_LOGIC** when executed against real persistence paths.
- CI-created measurements/photos/cost/package observations: **FIXTURE**, never physical REAL.
- Human-entered physical observations with authoritative DAM/operator lineage: **MANUAL_EVIDENCE**, not automatically certified or Production Ready.
- Demand / Vision / AI Video: **MOCK**.
- OS sandbox / AR / preflight / barcode hardware / McKee-BCT: **PARTIAL**.
- supplier/carrier/FX/receipts/provider facts remain IMPORTED/MANUAL/CONFIG according to existing truth labels.
- LIVE_CNC / LIVE_LASER / PLC / live provider / automatic factory execution: **BLOCKED**.
- `globalProductionReady`, `fullAutonomousFactoryReady`, `liveFactoryExecutionReady`, `liveProviderReady`, `liveMachineControl`: remain `false` in this phase.

---

# Required delivery / stop point

1. Implement Phase 661–720 **gaps only**, preserving the existing architecture.
2. Run full `pytest -q`; report the exact count and truth label. CI uses MOCK Blender and is not Production Ready evidence.
3. Commit implementation/tests first as a new **CODE_EVIDENCE_SHA**.
4. Require GitHub Actions Ubuntu + Windows GREEN on that exact CODE SHA.
5. Run acceptance on a clean tree bound to the exact CODE SHA. Do not hand-edit canonical PASS JSON.
6. If render/engineering/media path changed, generate fresh 4/4 REAL Blender 5.2.1 + T1000 OptiX evidence with job/hash/size/GPU/commit lineage. If unchanged, verify and honestly reuse prior `7a87ea5` evidence.
7. Re-run tenant backup/restore semantic validation for all new durable state.
8. Commit docs/evidence separately and require Ubuntu + Windows GREEN on docs/head.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`. Update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet truth actually changes.
10. Leave Issue #1 a concise handoff with CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, physical-evidence truth state, launch decision state, backup semantic result, prior/fresh REAL Blender status, and remaining MOCK/PARTIAL/BLOCKED boundaries.
11. **Stop for ChatGPT review. Do not enter Phase 721+ until ACCEPT WITH SCOPE.**
