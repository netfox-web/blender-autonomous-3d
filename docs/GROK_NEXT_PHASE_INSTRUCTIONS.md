# Grok 修正指令：Phase 661–720 final verifier integrity — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `75ce68e739d1120c4df5d81d9972ee5dac527b8b`  
> Reviewed CODE_EVIDENCE_SHA: `15f12cf41c4a39faf06a0c4a497bbb3f40588a08`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 721+. Fix only the two residual fail-closed verifier/integrity gaps below. Do not rewrite existing architecture.**

## Accepted this round — preserve, do not regress

The implementation in `15f12cf` is a substantive improvement and most of the previous correction is accepted:

- `_authoritative_packaging_qty()` no longer fabricates `1.0`; explicit packaging quantity is required, finite `>0`, and runtime checks tenant + PrototypeUnit + engineeringHash.
- Missing packaging quantity keeps cost `PARTIAL` and blocks `HUMAN_GO`; malformed/negative/wrong-unit/stale-engineering regressions were added.
- Packaging quantity is included in backup semantic digest and restored quantity lineage.
- `record_labor()` now binds the semantic idempotency identity inside the durable snapshot before journal/outbox completion, and restart can recover the same logical labor operation.
- Hard crash/restart coverage now exists for labor, package finalize, HUMAN_GO, pilot-plan creation (including no duplicate release/WO/plan), and accepted ECO. Tests assert one semantic journal event and zero open outbox where applicable.
- GitHub Actions CODE run `34428864527` is SUCCESS on exact `15f12cf` on Ubuntu + Windows. The suite is still MOCK/unit/integration + FIXTURE/REAL_LOGIC (`FOX3D_MOCK_BLENDER=1`), not Production Ready; report says `419 passed`.
- Canonical acceptance generation `dc5cbd4b-811f-49a0-b696-7f3628d5d0f4` is bound to exact CODE `15f12cf`, clean tree, and honestly keeps `physicalPrototypeValidated=false`, `launchDecision=WAITING_HUMAN_EVIDENCE`, and all global/full/live readiness flags false.
- Tenant backup semantic digest is reported equal (`dd375a40…`).
- Prior REAL Blender evidence may continue to be reused from `7a87ea5` only because render/engineering/media path is unchanged and the existing verifier passes: 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`.
- Demand / Vision / AI Video remain MOCK; OS sandbox / AR / preflight / barcode / McKee-BCT remain PARTIAL; LIVE_CNC / LIVE_LASER / PLC / live provider / automatic live factory remain BLOCKED.
- `docs/CABINET_REAL_ACCEPTANCE.md` has no truth change and should remain untouched unless cabinet truth actually changes.

The round is **not yet cleared for Phase 721+** because the runtime fixes are stronger than the published/canonical verifier. Two explicit fail-closed requirements from the previous instruction are still not independently provable after serialization.

---

# Residual Blocker 1 — canonical packaging quantity can still be detached from the authoritative checklist

Runtime is now correct, but published acceptance is weaker than runtime.

Current `matrix_row()` publishes `packagingQty` and the cost's `quantityLineage`, and `_cost_qty_complete()` includes a `packagingChecklistId`. However `validate_prototype_acceptance_result()` currently only rejects COMPLETE cost when `quantityLineage.packagingQty` is missing or its source is `MISSING`. It does **not** require/compare the authoritative checklist identity against the serialized unit / engineering revision / quantity.

Therefore a malformed or post-serialization-mutated launch-eligible result can potentially claim:

- `costCompleteness=COMPLETE`
- `quantityLineage.packagingQty=1`
- `sources.packagingQty=PACKAGING_CHECKLIST`

while the referenced `packagingChecklistId` is missing/bogus, belongs to another unit/tenant/engineering revision, or the matrix-level `packagingQty` differs. That violates the previous requirement: **packaging quantity detached from the exact checklist/unit/engineering revision must fail publication**.

## Required correction

Reuse the existing checklist and acceptance runner; do not add a second packaging ledger.

1. Publish a compact authoritative packaging lineage object for every matrix row when a checklist exists, for example:
   - `checklistId`
   - `tenantId`
   - `prototypeUnitId`
   - `engineeringHash`
   - `packagingQty`
   - source/truth label if already available
2. For `costCompleteness=COMPLETE` and for any `READY_FOR_HUMAN_GO_NO_GO` / `HUMAN_GO` path, the verifier must fail closed unless:
   - authoritative packaging lineage exists;
   - `checklistId` is non-empty;
   - tenant matches the result tenant;
   - PrototypeUnit matches the matrix/unit row;
   - engineeringHash matches the matrix/unit row;
   - explicit packagingQty is finite and `>0`;
   - authoritative `packagingQty == matrix.packagingQty == quantityLineage.packagingQty`;
   - `quantityLineage.packagingChecklistId == authoritative checklistId`;
   - source is an allowed source and is not inferred from money/dimensions/`ok=true`.
3. Do not accept a source string alone as proof of checklist identity.
4. Keep the normal FIXTURE canonical generation allowed to have cost PARTIAL / missing packagingQty; this strict requirement applies when a row claims COMPLETE/launch-eligible authority.

## Required regressions

Add publication/runner negative tests that mutate an otherwise launch-eligible MANUAL/IMPORTED truth set and prove `rc != 0` + previous canonical truth set preserved for each of:

- missing `quantityLineage.packagingChecklistId`;
- bogus/wrong checklist ID;
- packaging lineage wrong tenant;
- packaging lineage wrong PrototypeUnit;
- packaging lineage stale/wrong engineeringHash;
- matrix `packagingQty` != quantity-lineage packagingQty;
- authoritative packaging-lineage qty != quantity-lineage qty;
- source says `PACKAGING_CHECKLIST` but authoritative lineage object is absent.

Also keep the existing missing/null/malformed/negative explicit packaging quantity runtime regressions.

---

# Residual Blocker 2 — duplicate semantic labor aggregates are prevented for the tested crash, but not fail-closed as a durable invariant

The new crash ordering closes the demonstrated post-journal/pre-idem window. However the previous acceptance contract also required the system/verifier to reject **duplicate semantic labor aggregates** rather than merely proving that one current crash path no longer creates them.

Current behavior still has two weaknesses:

- `_recover_semantic()` takes the first matching keyed/semantic labor row when multiple rows exist instead of treating duplicate durable semantic identities as corruption/HOLD.
- `_authoritative_labor_minutes()` sums all matching durable labor rows. If a legacy/corrupted snapshot contains two rows for the same semantic labor operation, minutes can be doubled while the journal still contains only one deduplicated semantic event.
- Published `quantityLineage` exposes the summed labor minutes/source but does not expose enough labor identity/integrity evidence for the canonical verifier to detect this contradiction.

## Required correction

Reuse existing `PrototypeLabor`, idempotency key, EventJournal, Outbox and backup stores. **Do not add a second labor ledger or transaction system.**

1. Define one fail-closed semantic labor uniqueness invariant using the existing durable identity, preferably `idempotencyKey` plus tenant/unit/engineering/minutes/reason semantics.
2. If two durable PrototypeLabor rows represent the same semantic operation:
   - do not silently choose the first;
   - do not sum both into authoritative labor;
   - mark labor authority invalid / cost PARTIAL or HOLD/BLOCK launch eligibility;
   - require operator/admin repair rather than guessing which row is correct.
3. Publish a compact labor lineage/integrity proof in the existing cost quantity lineage, sufficient for the canonical verifier to establish uniqueness and total consistency. For example: durable labor IDs, semantic keys, source, total minutes, and `integrityOk`; use an equivalent structure if cleaner.
4. For COMPLETE/HUMAN_GO, verifier must require labor integrity PASS, unique semantic keys/IDs, and published authoritative labor total equal to `quantityLineage.laborMinutes`.
5. Backup/restore must preserve the labor semantic identities and must not collapse or synthesize duplicates.

## Required regressions

- Inject/persist two PrototypeLabor rows with the same semantic/idempotency identity: authoritative labor must not double and cost must not remain COMPLETE; HUMAN_GO blocked.
- Same corruption after restart: still detected.
- Same corruption after backup/restore: still detected.
- Canonical runner negative: an otherwise valid MANUAL/HUMAN_GO result with duplicate labor semantic evidence or labor total inconsistent with its labor records must fail and preserve the previous canonical truth set.
- Keep the new hard-crash labor regression and prove it still produces exactly one durable labor aggregate + one semantic journal event + zero open outbox + same logical retry.

---

# Evidence / delivery requirements

1. Fix only the two residual verifier/integrity items above. Preserve Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup architecture.
2. Run full `pytest -q`; report exact count and label it MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
3. Commit implementation/tests first as a new CODE_EVIDENCE_SHA and require Ubuntu + Windows SUCCESS on that exact SHA.
4. Regenerate the canonical Phase 661–720 truth set from the runner on a clean tree, bound to the exact new CODE SHA; no hand-edited PASS JSON.
5. Re-run tenant-A backup/restore semantic validation including explicit packaging checklist lineage, packagingQty, labor semantic identities, packages/decisions/plans and journal/outbox state; prove zero tenant-B leakage.
6. Reuse prior `7a87ea5` REAL Blender evidence only if render/engineering/media path remains unchanged and verifier still passes; otherwise refresh REAL Blender evidence.
7. Commit evidence/docs separately; require Ubuntu + Windows SUCCESS on the docs/head commit.
8. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md` and the generated Phase 661–720 acceptance files. Do not touch `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet truth changed.
9. Leave Issue #1 a concise completion handoff with CODE SHA, docs SHA, pytest count, both Actions run IDs, acceptance generation, packaging-checklist exact-lineage negative results, duplicate-labor negative results, crash/idempotency result, backup semantic result, prior/fresh REAL Blender result, and remaining MOCK/PARTIAL/BLOCKED boundaries.
10. **Stop for ChatGPT re-review. Do not enter Phase 721+ until ACCEPT WITH SCOPE.**
