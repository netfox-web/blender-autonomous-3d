# Grok 修正指令：Phase 661–720 final integrity — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `2b23ea0bde57b0235ef76597ea9b986eef572dc0`  
> Reviewed CODE_EVIDENCE_SHA: `39208fbf86c51f897fecf9190deb6225797df76d`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 721+. Fix Phase 661–720 gaps only. Do not rewrite existing architecture.**

## Evidence accepted in this review

Keep the following as the baseline; do not regress it:

- `pytest -q` is reported as **404 passed**. GitHub Actions CODE run `34386596466` is GREEN on Ubuntu + Windows on exact CODE `39208fb`; docs/head run `34387090520` is GREEN on Ubuntu + Windows on exact docs head `2b23ea0`.
- Canonical generation `78560c82-9909-44e7-b868-677c88875d20` is clean-tree/head-bound and honestly says `label=FIXTURE/REAL_LOGIC`, `physicalPrototypeValidated=false`, `launchDecision=WAITING_HUMAN_EVIDENCE`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `liveMachineControl=false`.
- Four selected SKUs have exact selected/unit/package lineage; four FIXTURE evidence packages are FINALIZED; fixture evidence does not self-upgrade to HUMAN_GO.
- Tenant backup semantic digest currently matches for A and no Production Ready claim is made.
- Prior REAL Blender evidence remains verified as 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX on `7a87ea5`, `usedMock=false`. Render/engineering/media path did not change, so it may continue to be reused if its fail-closed verifier still passes.
- HUMAN_GO remains a human decision; MOCK demand cannot upgrade GO; pilot planning remains MANUAL_STATION with LIVE_CNC/LIVE_LASER/PLC/live provider/live factory blocked.

The current acceptance is valid as **software-gate FIXTURE evidence**, but the manual/physical route still has three integrity gaps below. Therefore Phase 661–720 is not cleared for Phase 721+ yet.

---

# Blocker A — Required physical DAM evidence is not actually required for MANUAL_EVIDENCE / HUMAN_GO

Current behavior validates DAM refs when the caller supplies them, but `record_as_built(... source="MANUAL")` can have zero `dam_refs`; packaging can also have zero photo/document refs. A manual actor can then PASS_AS_BUILT, supply monetary amounts, reach HUMAN_GO, and create a pilot plan without authoritative physical photo/document evidence.

This does not satisfy the Phase 669–676 / 685–692 evidence contract.

## Required correction

Extend the existing PhysicalEvidencePackage/DAM path; do **not** create a second asset store.

1. Add a pinned, explicit required-DAM-evidence policy for launch-eligible physical evidence. Minimum practical contract:
   - at least one authoritative `AS_BUILT` photo/document evidence asset;
   - at least one authoritative `PACKAGING` photo/document evidence asset;
   - same tenant as PrototypeUnit;
   - asset must exist in current DAM;
   - SHA-256 and size must be read/verified from authoritative DAM state, not trusted from caller metadata;
   - non-empty bytes/size;
   - package stores the verified asset identity/hash/size and evidence role.
2. `PASS_AS_BUILT` for `MANUAL_EVIDENCE` / `IMPORTED_EVIDENCE` must fail closed or remain HOLD/WAITING when required as-built DAM evidence is absent.
3. `READY_FOR_HUMAN_GO_NO_GO` / `HUMAN_GO` must require both the required as-built and packaging evidence roles. Zero DAM refs must never qualify.
4. Correction/supersession remains append-only. A corrected evidence package must not silently inherit stale DAM evidence across a changed engineering/ECO revision unless the exact evidence is explicitly valid for the same pinned revision.
5. FIXTURE may create real local DAM bytes to test the policy, but it remains `FIXTURE`, `physicalPrototypeValidated=false`, and cannot HUMAN_GO.
6. Certified/ISTA claims keep the existing stricter certified-report requirement; manual photos are not certification.

## Required negative regressions

- MANUAL as-built with complete measurements/QC but zero DAM refs cannot PASS_AS_BUILT / cannot become physical validated.
- MANUAL packaging with zero required packaging DAM evidence cannot become launch-ready.
- wrong tenant / missing asset / wrong hash / wrong size / zero-byte required evidence blocks.
- stale DAM evidence after accepted engineering ECO cannot validate the new engineeringHash.
- serializer/canonical publication that drops required evidence role/id/hash/size fails post-publication validation and preserves the prior good truth set.

---

# Blocker B — `costCompleteness=COMPLETE` can be reached with four money numbers but without authoritative material/labor quantity lineage

Current `record_actual_cost()` treats the required monetary fields (`materialAmount`, `hardwareAmount`, `laborAmount`, `packagingAmount`) as sufficient for COMPLETE. Existing tests demonstrate a human path that supplies only those four amounts and then successfully HUMAN_GO, without consuming MaterialLot inventory and without deriving labor from the existing append-only labor records.

This does not satisfy Phase 677–684. Quantity truth and monetary truth must both be present; minutes/counts must never be invented or inferred from money.

## Required correction

Reuse existing MaterialLot / WorkOrder / labor / packaging records. Do **not** create a second cost or labor ledger.

For launch eligibility, define `costCompleteness=COMPLETE` only when all required categories have both valid quantity lineage and required money evidence:

1. **Material quantity**: must come from authoritative MaterialLot reservation/consume lineage for the exact tenant + PrototypeUnit/work-order + engineering requirement. `materialConsumed=true` and exact `inventoryLineage`/reservation identity must be present when claiming an actual physical material quantity. Caller-only `sheetsConsumed` is not authoritative.
2. **Labor quantity**: derive actual labor minutes from the existing append-only labor segment/correction source already used by the manual-factory pilot. Pin exact tenant/work-order/unit lineage. Do not accept a caller-only `laborMinutes` as authoritative when no matching durable labor record exists. If the existing source has no matching physical-prototype labor evidence, stay PARTIAL.
3. **Hardware quantity**: require an observed/verified hardware quantity from QC/packing/evidence package or another existing authoritative manual record; do not treat `hardwareAmount` alone as hardware actual completeness.
4. **Packaging quantity**: derive from the existing packaging checklist/evidence package and exact unit lineage; do not let a packaging money amount alone satisfy the category.
5. Monetary values may remain explicit MANUAL/IMPORTED observations and must retain currency/source labels. Quantity and currency stay separate.
6. A monetary exception may be shown as a human exception/HOLD reason, but it must not silently relabel missing authoritative quantity lineage as COMPLETE.
7. Human launch decision and manual pilot approval must re-check this stronger completeness contract, not only `cost.get("completeness") == "COMPLETE"` generated from four amounts.

## Required regressions

- four required money amounts + no MaterialLot consume lineage => PARTIAL and HUMAN_GO blocked.
- four amounts + no durable labor record => PARTIAL and HUMAN_GO blocked.
- caller-supplied labor minutes with no matching append-only labor lineage => not authoritative / PARTIAL.
- material quantity mismatch, wrong lot/SKU/thickness/grain/size, stale WO/unit/engineering lineage => blocked.
- complete authoritative qty lineage + explicit required money fields may become COMPLETE, but only with MANUAL/IMPORTED truth labels and never Production Ready.
- backup/restore preserves exact cost quantity-source identity and does not turn PARTIAL into COMPLETE.

---

# Blocker C — Prototype evidence/launch durability still has business-state-before-outbox crash windows

The shared `journal.emit()` helper has the correct PREPARED-outbox → business persist → journal COMMITTED → outbox complete pattern when it owns persistence. However several new prototype paths persist business state **before** calling `_emit()`.

Concrete example: `create_evidence_package()` persists the new package/unit pointer, then hits `after-package-prepare`, and only afterward calls `_emit()`. On restart `_active_package()` can return that durable package immediately, so the create event can remain permanently absent from the journal. The current crash regression only proves “one package exists”; it does not prove a committed journal event/outbox reconciliation.

Similar state-changing paths must be audited: package create/attach/supersede/finalize, launch decision, accepted ECO, pilot plan, and any other Phase 661–720 mutation that claims journal durability.

## Required correction

Use the **existing** CommitOutbox/EventJournal/reconcile machinery; do not build another transaction system.

1. Ensure no Phase 661–720 business mutation that is required to be journaled becomes durably visible before a durable PREPARED transaction exists.
2. Prefer routing the mutation through the existing `emit()`/outbox transaction boundary, or add a small pre-intent using that same mechanism. Do not simply add another `persist()`.
3. Startup reconciliation must deterministically finish or block an interrupted transaction using `_business_committed`; it must not leave business-only state with no semantic journal event.
4. Idempotent retry after restart must produce exactly one semantic event and exactly one business aggregate, with no duplicate side effects.
5. Package field attachments (measurement/cost/checklist/DAM evidence) must have auditable durable state transitions. They may be represented as dedicated events or as a versioned package update event, but silent durable mutation is not sufficient for the “every state-changing action is journaled” contract.

## Required crash regressions

Use real subprocess `os._exit` where practical, not only caught exceptions. At minimum cover:

- evidence package create: crash after outbox PREPARED and crash after business persist/before journal append;
- evidence-package finalize/supersede or attachment update: same durability boundary;
- HUMAN_GO launch decision: crash in the business/journal window;
- pilot plan creation: crash in the business/journal window (must not duplicate release/WO/plan on retry);
- accepted ECO mutation if it is covered by the Phase 661–720 journal contract.

After restart assert all of:

- exact one business aggregate;
- exact one semantic committed journal event;
- zero unresolved outbox tx after reconciliation;
- `pilot.journal.verify(tenant)["ok"] == true`;
- tenant isolation intact;
- retry is idempotent;
- a business-only orphan with missing event is detected/fixed, never treated as a successful completed transaction.

The existing `test_package_crash_prepare_reconciles` must be strengthened to assert journal/outbox semantics, not only package count/state.

---

# Canonical acceptance corrections

Update the existing Phase 661–720 canonical truth set only through the runner; do not hand-edit PASS JSON.

The acceptance verifier must fail closed if a launch-eligible MANUAL/IMPORTED scenario is missing any of:

- required authoritative DAM evidence roles + assetId + authoritative SHA/size;
- authoritative material consume quantity lineage;
- authoritative durable labor quantity lineage;
- hardware and packaging quantity evidence;
- required monetary fields/currency/source;
- exact selected → unit → package → measurement/cost/packaging → launch decision lineage;
- journal/outbox integrity for all new state-changing actions.

CI may continue to finish with only FIXTURE evidence and `ok=true` for **software-gate correctness**, but in that case it must still say:

- `physicalPrototypeValidated=false`
- `launchDecision=WAITING_HUMAN_EVIDENCE` (or HOLD)
- physical/cost evidence truth remains FIXTURE/PARTIAL as applicable
- no HUMAN_GO / no real physical pilot claim
- all global/full/live readiness flags false.

Add negative runner tests proving that removing required DAM evidence, forging COMPLETE cost without authoritative qty lineage, or dropping journal integrity makes acceptance fail and preserves the prior good canonical bundle.

---

# Truth labels / boundaries that must remain

- Prototype/evidence/decision/durability code path: **REAL_LOGIC** only when the real persistence/outbox/journal path is used.
- CI measurements/photos/cost/package observations: **FIXTURE**, never physical REAL.
- Human-entered evidence with authoritative operator/DAM lineage: **MANUAL_EVIDENCE**, not certification and not Production Ready by itself.
- Prior Blender 5.2.1 + T1000 OptiX evidence on `7a87ea5`: **REAL render evidence** only; reuse only if the render/engineering/media path stays unchanged and verifier passes.
- Demand / Vision / AI Video: **MOCK**.
- OS sandbox / AR / preflight / barcode hardware / McKee-BCT: **PARTIAL**.
- Supplier/carrier/FX/receipts/provider facts: keep existing IMPORTED/MANUAL/CONFIG labels.
- LIVE_CNC / LIVE_LASER / PLC / live provider / automatic factory execution: **BLOCKED**.
- `globalProductionReady`, `fullAutonomousFactoryReady`, `liveFactoryExecutionReady`, `liveProviderReady`, `liveMachineControl`: remain `false`.

# Required delivery / stop point

1. Fix **only** the three blockers above; preserve Scheduler/Queue/DAM/Recipe/TwinStore/CabinetSpec/KD/MaterialLot/Nesting/Remnant/ManufacturingRelease/WorkOrder/QC/Logistics/Backup architecture.
2. Run full `pytest -q`; report the exact pass count and truth label. MOCK Blender CI is not Production Ready.
3. Commit implementation/tests first as a new CODE_EVIDENCE_SHA and require Ubuntu + Windows GREEN on that exact SHA.
4. Regenerate clean-tree canonical Phase 661–720 acceptance bound to exact CODE SHA; no hand-edited PASS JSON.
5. Re-run tenant A backup/restore semantic validation including evidence assets/roles, stronger cost lineage, decisions/plans, and journal/outbox identities; prove zero B leakage.
6. Reuse prior `7a87ea5` REAL Blender evidence only if render/engineering/media path remains unchanged and verifier passes; otherwise generate fresh 4/4 REAL Blender evidence.
7. Commit evidence/docs separately; require Ubuntu + Windows GREEN on docs/head.
8. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`. Do not touch `CABINET_REAL_ACCEPTANCE.md` unless cabinet truth actually changes.
9. Leave Issue #1 a concise handoff with CODE SHA, docs SHA, pytest count, both Actions run IDs, acceptance generation, DAM-evidence result, authoritative-cost-lineage result, journal/outbox crash result, backup semantic result, prior/fresh REAL Blender result, and remaining MOCK/PARTIAL/BLOCKED boundaries.
10. **Stop for ChatGPT review. Do not enter Phase 721+ until ACCEPT WITH SCOPE.**
