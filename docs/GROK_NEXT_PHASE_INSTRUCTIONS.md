# Grok 修正指令：Phase 661–720 final integrity — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `5294848082a1e513c0c482d46907285f9291ee4a`  
> Reviewed CODE_EVIDENCE_SHA: `8f3bbdae8690b532c01aed74539b61e36a412e89`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 721+. Fix only the residual Phase 661–720 integrity gaps below. Do not rewrite existing architecture.**

## Accepted evidence — preserve, do not regress

- `pytest -q` reported **409 passed** and remains **MOCK/unit/integration + FIXTURE/REAL_LOGIC**, not Production Ready.
- GitHub Actions CODE run `34398508992` is SUCCESS on exact CODE `8f3bbda` on Ubuntu + Windows.
- GitHub Actions docs/head run `34399015958` is SUCCESS on exact docs head `5294848` on Ubuntu + Windows.
- Canonical generation `feefa00a-ac2f-44ee-91bc-3e28531d8485` is clean-tree/code-bound and honestly keeps `physicalPrototypeValidated=false`, `launchDecision=WAITING_HUMAN_EVIDENCE`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `liveMachineControl=false`.
- Required DAM roles are materially improved: MANUAL/IMPORTED PASS_AS_BUILT requires authoritative AS_BUILT DAM; HUMAN_GO requires AS_BUILT + PACKAGING DAM; DAM tenant/SHA/size/non-empty bytes are checked from the authoritative DAM object. FIXTURE remains FIXTURE and cannot HUMAN_GO.
- Material quantity now comes from exact MaterialLot consume lineage; durable prototype labor records exist; hardware quantity is checked through QC/packaging; four money amounts alone initially remain PARTIAL.
- Package-create outbox ordering is materially improved: PREPARED outbox precedes durable business persist; startup reconciliation can recover the after-business-persist/before-journal window; package-create subprocess `os._exit` evidence exists.
- Tenant backup digest includes prototype labor and the reported tenant digest remains equal.
- Prior REAL Blender evidence remains verified 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX on `7a87ea5`, `usedMock=false`. Render/engineering/media path did not change, so reuse is acceptable only while the verifier continues to pass.
- Demand / Vision / AI Video remain MOCK; OS sandbox / AR / preflight / barcode / McKee-BCT remain PARTIAL; LIVE_CNC / LIVE_LASER / PLC / live provider / automatic live factory remain BLOCKED.

The round is **not cleared for Phase 721+** because Blocker B still contains a real fail-open and Blocker C is only partially proven.

---

# Residual Blocker B — packaging quantity lineage is still fabricated by fallback `1.0`

Current `PrototypeService._authoritative_packaging_qty()` returns `1.0` whenever an `ok=true` packaging checklist exists but `observed.packagingQty` is absent. `packaging_checklist()` does not require `packagingQty`.

This means the stronger quantity contract is not actually closed: a checklist with dimensions/weight/counts/observations but **no explicit observed packaging quantity** can be treated as authoritative packaging quantity evidence.

The current positive HUMAN_GO regression demonstrates the gap: the test creates a valid packaging checklist using `_pack_obs(...)` without `packagingQty`, then consumes MaterialLot, records durable labor, supplies the four required monetary amounts, and successfully reaches HUMAN_GO. That success currently depends on the implicit `packagingQty=1.0` fallback.

## Required correction

Reuse the existing packaging checklist/evidence package. Do not create a new packaging ledger.

1. Remove the implicit `return 1.0` authority fallback for launch/cost completeness.
2. `costCompleteness=COMPLETE` must require an **explicit observed packaging quantity** that is:
   - finite and valid (`>0` for an actually packed unit/batch unless an existing domain rule explicitly allows zero);
   - stored durably in the existing packaging checklist/evidence record;
   - exact tenant + PrototypeUnit + engineeringHash lineage;
   - tied to the same checklist used for launch readiness;
   - labeled MANUAL/IMPORTED/FIXTURE correctly.
3. If explicit packaging quantity is missing/null/malformed/stale/wrong-unit/wrong-engineering, packaging quantity source must be `MISSING`/invalid, cost remains PARTIAL, and HUMAN_GO/manual pilot approval stays blocked.
4. Do not infer packaging quantity from `packagingAmount`, carton dimensions, `ok=true`, expected unit quantity, or a constant.
5. Preserve existing hardware-count verification, MaterialLot consume lineage, labor lineage, currency separation, and remnant rules.

## Required regressions

- valid AS_BUILT + valid PACKAGING DAM + MaterialLot consumed + durable labor + correct hardware count + four required money amounts, but **no explicit packagingQty** => cost PARTIAL and HUMAN_GO blocked;
- explicit packagingQty = null / malformed / negative / wrong-unit or stale engineering => PARTIAL/BLOCKED as appropriate;
- explicit valid packagingQty with all other authoritative qty lineage + required money fields may become COMPLETE and pass the human launch software gate;
- backup/restore preserves exact packaging quantity/source/checklist identity and does not synthesize a default after restart;
- canonical runner negative test: launch-eligible MANUAL/IMPORTED evidence with COMPLETE cost but missing explicit packaging quantity must fail publication and preserve the previous canonical truth set.

---

# Residual Blocker C — crash proof is incomplete, and additive labor still has a post-journal/pre-idem duplication window

The common `emit()` path now correctly does PREPARED outbox → business persist → journal append → outbox complete for the tested package-create path. However the previous correction explicitly required crash/restart proof for other Phase 661–720 state-changing paths, and the current committed tests only substantively exercise evidence-package create.

There is also a concrete remaining idempotency window in additive prototype labor:

- `record_labor()` uses `_idem(key, _make)`;
- `_make()` creates the new labor row and calls `_emit()`;
- `_emit()` may fully persist the business row, append/deduplicate the semantic journal event, and complete the outbox;
- only **after `_make()` returns** does `_idem()` persist `self.idem[key]`.

If the process dies after the journal/outbox transaction completes but before the idempotency index is persisted, retry can create a second labor business row. `EventJournal.append()` deduplicates the semantic event by semanticKey, but that does not automatically delete the duplicate labor aggregate. Because authoritative labor minutes sum durable labor rows, this can double observed labor/cost while journal verification still looks healthy.

## Required correction

Use the existing CommitOutbox/EventJournal/idempotency machinery; do not add a second transaction system and do not rewrite the architecture.

1. Close the **post-journal / pre-idempotency-index** window for `record_labor()` so one semantic labor operation can produce exactly one durable labor aggregate and one semantic journal event across crash/retry.
   - Persist the idempotency identity inside the same durable business snapshot/outbox boundary, or reconcile by semantic business identity on restart/retry.
   - Do not solve this by merely ignoring the second journal event; business aggregate uniqueness is required.
2. Audit other Phase 661–720 additive/idempotent mutations for the same ordering issue. At minimum verify launch decision and pilot-plan semantics; do not change unrelated older architecture unless the same helper fix is safely shared.
3. Add a crash hook/test for the window **after journal append/outbox completion but before the outer idempotency mapping would otherwise be persisted**, or an equivalent real `os._exit` point that proves the same failure mode.
4. After restart/retry assert:
   - exactly one labor aggregate for the semantic operation;
   - exact labor minutes are not doubled;
   - exactly one semantic journal event;
   - zero unresolved outbox transactions;
   - `pilot.journal.verify(tenant)["ok"] == true`;
   - retry returns/reuses the same logical labor operation.
5. Finish the previously required crash coverage for Phase 661–720 state mutations. Add real subprocess `os._exit` regressions (or equivalent hard process death) for at least:
   - evidence package finalize or attachment update;
   - HUMAN_GO launch decision;
   - pilot-plan creation (must not duplicate release / WorkOrder / plan);
   - accepted ECO if it is claimed under this journal durability contract.
6. Each crash test must prove **one business aggregate + one semantic event + no open outbox + idempotent retry**, not merely that restart succeeds.

---

# Canonical / acceptance requirements for this correction round

Do not hand-edit PASS JSON. Regenerate through the existing runner after code/tests are fixed.

The Phase 661–720 verifier must fail closed when a launch-eligible MANUAL/IMPORTED case has any of:

- missing explicit packaging quantity lineage;
- packaging quantity detached from the exact checklist/unit/engineering revision;
- duplicate semantic labor aggregates;
- labor minutes changed by crash/retry duplication;
- unresolved outbox transaction or business/journal semantic mismatch;
- missing required AS_BUILT/PACKAGING DAM evidence;
- missing MaterialLot consume lineage or durable labor/hardware quantity lineage;
- stale selected → unit → package → measurement/cost/packaging → launch lineage.

CI may continue to publish a **FIXTURE/REAL_LOGIC software-gate acceptance** with `ok=true`, but it must continue to state:

- `physicalPrototypeValidated=false`;
- `launchDecision=WAITING_HUMAN_EVIDENCE` or HOLD;
- fixture cost/evidence truth stays FIXTURE/PARTIAL where appropriate;
- no HUMAN_GO physical claim;
- all global/full/live readiness flags remain false.

---

# Required delivery / stop point

1. Fix only the residual Blocker B + C items above; preserve Scheduler/Queue/DAM/Recipe/TwinStore/CabinetSpec/KD/MaterialLot/Nesting/Remnant/ManufacturingRelease/WorkOrder/QC/Logistics/Backup architecture.
2. Run full `pytest -q`; report exact count and keep MOCK/FIXTURE labeling honest.
3. Commit implementation/tests first as a new CODE_EVIDENCE_SHA; require Ubuntu + Windows GREEN on exact CODE SHA.
4. Regenerate clean-tree canonical Phase 661–720 acceptance bound to exact CODE SHA; no hand-edited PASS JSON.
5. Re-run tenant A backup/restore semantic validation including explicit packaging quantity lineage, labor identity, packages/decisions/plans, and journal/outbox state; prove zero tenant-B leakage.
6. Reuse prior `7a87ea5` REAL Blender evidence only if render/engineering/media path remains unchanged and verifier passes; otherwise refresh REAL Blender evidence.
7. Commit evidence/docs separately; require Ubuntu + Windows GREEN on docs/head.
8. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, and `docs/REAL_E2E_ACCEPTANCE.md`. Do not touch `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet truth actually changes.
9. Leave Issue #1 a concise handoff with CODE SHA, docs SHA, pytest count, both Actions run IDs, acceptance generation, explicit packaging-quantity result, post-journal/idempotency crash result, other required crash results, backup semantic result, prior/fresh REAL Blender result, and remaining MOCK/PARTIAL/BLOCKED boundaries.
10. **Stop for ChatGPT review. Do not enter Phase 721+ until ACCEPT WITH SCOPE.**
