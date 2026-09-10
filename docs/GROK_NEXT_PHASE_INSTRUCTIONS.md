# Grok 修正指令：Phase 661–720 canonical authority binding final gap — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `c1856ae87cefba9c5a2614d048ef93d4d1ec8d9b`  
> Reviewed CODE_EVIDENCE_SHA: `92ec8f3c785836e774561a851b3d65ecfd0f4f26`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 721+. Fix only the residual canonical authority-binding gaps below. Do not rewrite existing architecture.**

## Accepted this round — preserve, do not regress

The `92ec8f3` implementation is a substantive improvement and the runtime-side work from `8ccb803` is accepted:

- Packaging quantity is explicit, finite `>0`, and bound at runtime to checklist tenant + PrototypeUnit + engineeringHash; no fabricated `1.0` fallback.
- Matrix now publishes `packagingLineage` and cost `quantityLineage` carries `packagingChecklistId`.
- Duplicate PrototypeLabor semantic/idempotency rows are detected as corruption/HOLD; authoritative minutes are not silently doubled; cost becomes PARTIAL and HUMAN_GO is blocked.
- Restart and backup/restore preserve duplicate-labor corruption so it remains detectable rather than being silently collapsed.
- `record_labor()` crash/idempotency regression still proves one durable labor row + one semantic journal event after retry.
- Full local suite reports `pytest -q -> 430 passed`, explicitly MOCK/unit/integration + FIXTURE/REAL_LOGIC, **not Production Ready**.
- GitHub Actions CODE run `34431835320` on exact `92ec8f3` is SUCCESS on Ubuntu + Windows.
- GitHub Actions docs/head run `34432157061` on exact `c1856ae` is SUCCESS on Ubuntu + Windows.
- Canonical generation `891e4c20-a0b3-4b14-91e5-c41eb92d0c4c` is runner-bound to `92ec8f3`, clean tree, and honestly keeps `physicalPrototypeValidated=false`, `launchDecision=WAITING_HUMAN_EVIDENCE`, and all global/full/live readiness flags false.
- Prior REAL Blender evidence remains scoped-valid from `7a87ea5`: 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`; render/engineering/media path did not change.
- Demand / Vision / AI Video remain MOCK; OS sandbox / AR / preflight / barcode / McKee-BCT remain PARTIAL; LIVE_CNC / LIVE_LASER / PLC / live provider / automatic live factory remain BLOCKED.
- `docs/CABINET_REAL_ACCEPTANCE.md` has no truth change and must remain untouched unless cabinet truth actually changes.

The remaining issue is narrower: the runtime authority is stronger than the **serialized canonical proof**. An internally self-consistent row can still claim authority without proving that its IDs correspond to the actual serialized durable source records.

---

# Residual Blocker 1 — packaging checklist canonical proof is cross-field consistency, not authoritative existence

Current verifier correctly compares `packagingLineage.checklistId` with `quantityLineage.packagingChecklistId`, unit/hash/qty fields, but the canonical truth set does not publish an authoritative checklist collection/index that the verifier can resolve by ID.

Therefore a coordinated post-serialization mutation can change **both** checklist IDs to the same bogus non-empty value while keeping tenant/unit/hash/qty internally consistent. The current `bogus checklist ID` regression changes only one copy of the ID, so it proves mismatch detection, not existence of the referenced checklist.

There is also a fail-open detail: packaging tenant mismatch is currently checked only when both tenant values are truthy. A missing/blank authoritative tenant must fail for COMPLETE/launch-eligible rows.

## Required correction

Reuse the existing `PrototypeFactory.checklists` store. **Do not create a second packaging ledger.**

1. Publish a compact authoritative checklist snapshot/index in the canonical result for the selected 4 units, e.g. `packagingChecklistAuthority` (name may differ), with exactly the fields needed to prove authority:
   - `checklistId`
   - `tenantId`
   - `prototypeUnitId`
   - `engineeringHash`
   - explicit `packagingQty`
   - source / truth label
   - optionally a deterministic record hash if useful, but do not invent a new source of truth.
2. Each COMPLETE or `READY_FOR_HUMAN_GO_NO_GO` / `HUMAN_GO` matrix row must resolve to **exactly one** serialized authoritative checklist record by `checklistId`.
3. Validator must fail closed when the authoritative checklist record is missing, duplicated, malformed, has blank tenant/unit/hash, wrong tenant/unit/hash, invalid qty, or its qty differs from matrix / `packagingLineage` / `quantityLineage`.
4. Require all of the following to agree exactly:
   - authoritative checklist `checklistId`
   - `packagingLineage.checklistId`
   - `quantityLineage.packagingChecklistId`
   - authoritative tenant == row/result tenant
   - authoritative PrototypeUnit == row PrototypeUnit
   - authoritative engineeringHash == row engineeringHash
   - authoritative qty == `packagingLineage.packagingQty` == matrix `packagingQty` == `quantityLineage.packagingQty`
5. Require canonical quantity source to be exactly the permitted packaging-checklist source. Do not let a valid `packagingLineage.source` mask a contradictory/missing `quantityLineage.sources.packagingQty`.
6. Normal FIXTURE rows may remain cost PARTIAL and packagingQty missing; do not fabricate physical quantity merely to satisfy the verifier.

## Required negative regressions

Starting from an otherwise launch-eligible MANUAL/IMPORTED canonical result, prove `rc != 0` and previous canonical truth set remains unchanged for each:

- mutate **both** `packagingLineage.checklistId` and `quantityLineage.packagingChecklistId` to the same bogus ID;
- remove the referenced authoritative checklist record;
- duplicate the same checklistId in the authoritative snapshot;
- authoritative checklist tenant missing/blank;
- wrong tenant;
- wrong PrototypeUnit;
- stale/wrong engineeringHash;
- authoritative qty differs while row/lineage copies remain unchanged;
- matrix qty differs;
- quantity-lineage qty differs;
- packaging source missing/contradictory even when another source field says `PACKAGING_CHECKLIST`.

The existing runtime missing/null/malformed/negative packagingQty tests must continue to pass.

---

# Residual Blocker 2 — labor canonical proof still trusts self-declared lineage instead of durable labor records

Runtime duplicate-labor handling is accepted. However canonical `laborLineage` currently contains `laborIds`, `semanticKeys`, `minutes`, `integrityOk`, and `duplicateKeys` without publishing the durable labor rows from which those values were derived.

The verifier can prove that the lineage object is internally self-consistent, but cannot independently prove that its labor IDs/semantic keys/minutes actually correspond to durable PrototypeLabor / allowed WorkOrder labor evidence. A coordinated mutation can replace the lineage with one fake unique ID/key and matching minutes, set `integrityOk=true`, and still look valid after serialization.

## Required correction

Reuse existing PrototypeLabor, WorkOrder labor summary, EventJournal/Outbox and backup state. **Do not add another labor ledger or transaction system.**

1. Publish a compact authoritative labor snapshot/index for the selected units in canonical evidence, sufficient to rebuild labor semantics independently. For PrototypeLabor rows include at least:
   - `laborId`
   - `tenantId`
   - `prototypeUnitId`
   - `engineeringHash`
   - `minutes`
   - `reason`
   - existing durable `idempotencyKey` / semantic identity
   - source
2. If WorkOrder labor is allowed to satisfy cost COMPLETE/HUMAN_GO when no PrototypeLabor row exists, publish/bind the relevant authoritative WorkOrder labor identity and make it part of the same verification contract. Otherwise keep that path PARTIAL until it is represented. **Do not allow `_cost_qty_complete.ok=true` while the published labor authority says `integrityOk=false`.**
3. Canonical verifier must independently rebuild the semantic labor key from authoritative rows and require:
   - unique labor IDs;
   - unique semantic identities;
   - tenant/unit/engineering lineage exact match;
   - exact set equality between authoritative labor IDs and `laborLineage.laborIds`;
   - exact set equality between rebuilt semantic keys and `laborLineage.semanticKeys`;
   - computed authoritative total minutes == `laborLineage.minutes` == `quantityLineage.laborMinutes`;
   - no duplicate semantic/idempotency identity;
   - `integrityOk=true` is a derived consequence, not accepted as proof by itself.
4. Backup/restore must preserve this authority snapshot semantics and duplicate corruption exactly; zero tenant-B leakage.

## Required negative regressions

Starting from otherwise valid MANUAL/HUMAN_GO evidence, prove publication fails and preserves previous canonical truth for:

- replace `laborLineage` with a fake single unique laborId/semanticKey and matching minutes while no matching authoritative row exists;
- authoritative labor row missing;
- duplicate raw authoritative rows with different laborIds but same semantic/idempotency identity;
- duplicate laborId;
- wrong tenant;
- wrong PrototypeUnit;
- stale engineeringHash;
- mismatched reason/idempotency semantic key;
- authoritative minutes total differs from `laborLineage.minutes`;
- `laborLineage.minutes` differs from `quantityLineage.laborMinutes`;
- WorkOrder fallback claims COMPLETE without a verifiable canonical authority record, if that fallback remains supported.

Keep the existing hard-crash labor regression and prove retry still yields exactly one durable semantic operation + one journal event + zero open outbox.

---

# Evidence / delivery requirements

1. Fix only the two canonical authority-binding gaps above. Preserve Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup architecture.
2. Run full `pytest -q`; report exact count and label it MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
3. Commit implementation/tests first as a new CODE_EVIDENCE_SHA; require Ubuntu + Windows SUCCESS on that exact SHA.
4. Regenerate the Phase 661–720 canonical truth set from the runner on a clean tree, bound to the exact new CODE SHA. No hand-edited PASS JSON.
5. The serialized canonical result itself must contain enough authoritative checklist/labor evidence for the verifier to recompute identity and totals after serialization. Merely copying more precomputed booleans is not sufficient.
6. Re-run tenant-A backup/restore semantic validation including checklist authority, packaging qty, labor authority/semantic identity, packages/decisions/plans and journal/outbox; prove zero tenant-B leakage.
7. Reuse prior `7a87ea5` REAL Blender evidence only if render/engineering/media paths remain unchanged and verifier still passes; otherwise refresh REAL Blender evidence.
8. Commit evidence/docs separately; require Ubuntu + Windows SUCCESS on the docs/head commit.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md` and generated Phase 661–720 acceptance files. Do not touch `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet truth changed.
10. Leave Issue #1 a concise completion handoff with CODE SHA, docs SHA, pytest count, both Actions run IDs, acceptance generation, coordinated-bogus-checklist negative result, authoritative-labor negative results, crash/idempotency result, backup semantic result, prior/fresh REAL Blender result, and remaining MOCK/PARTIAL/BLOCKED boundaries.
11. **Stop for ChatGPT re-review. Do not enter Phase 721+ until ACCEPT WITH SCOPE.**
