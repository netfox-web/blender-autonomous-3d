# Grok 修正指令：Phase 601–660 Final Integrity — Reservation Intent + Canonical Lineage

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `da48e19f0fa631b4389fb757327c3f6b489a3bc0`  
> Reviewed CODE_EVIDENCE_SHA: `0b9caedd008b4d1f924cdcad529d87a4ac59154c`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 661+. Fix only the remaining Phase 601–660 integrity gaps below.**

## Accepted evidence — preserve it

This round is substantive and the three blockers from `df5c29e` are materially improved. Correct in place; do not rewrite architecture.

- Packaging predicted-vs-observed carton L/W/H, packed weight and assembly-time tolerance now participate in `ok`; failures place the unit on HOLD and `packagingPolicyHash` is persisted.
- The canonical validator now requires `toleranceStatus=true`, QC complete, required packaging `COMPLETE`, `packagingValidation.ok=true`, and rejects required per-field packaging variance contradictions that are present.
- Prototype inventory now pins reservation lineage and can recover after a crash **after the first consume**; same-process `CrashInjected` and real subprocess `os._exit` regressions recreate `Platform`, resume the pinned reservations and keep final consumed quantity idempotent.
- `pytest -q`: **366 passed**, explicitly MOCK/unit/integration + FIXTURE/REAL_LOGIC — **not Production Ready**.
- GitHub Actions CODE run `34372952091` is GREEN on Ubuntu + Windows for exact CODE `0b9caed...`.
- GitHub Actions docs/head run `34373383049` is GREEN on Ubuntu + Windows for exact docs head `da48e19...`.
- Canonical generation `0d6fc75a-9337-4144-8227-e9a49f0abaa7` is clean-tree bound to CODE `0b9caed...`; current committed 4/4 FIXTURE rows are internally green and keep `physicalPrototypeValidated=false`.
- Prior REAL Blender evidence remains verified 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, on CODE `7a87ea5...`; render/media/engineering path was not changed this round.
- Keep Demand / Vision / AI Video = **MOCK**; OS sandbox / AR / preflight / barcode / McKee-BCT = **PARTIAL**; supplier/carrier/FX/receipts as IMPORTED/MANUAL/CONFIG where already modeled; LIVE_CNC / LIVE_LASER / PLC / live provider / live factory = **BLOCKED**.
- Keep `physicalPrototypeValidated=false` for fixture acceptance and keep `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `liveMachineControl=false`.

Do **not** replace Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD registry / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup architecture. Reuse the existing transaction, outbox/journal, inventory, backup and acceptance mechanisms.

---

## BLOCKER 1 — Crash window still exists between durable reservation and durable Prototype inventory intent

The new recovery correctly handles a crash after one reservation has already been consumed, but `consume_material_once()` still performs `reserve_sheets()` / `allocate_requirement()` **before** the new Prototype `inventoryIntent` is persisted. MaterialLot reservation is itself durable. A process death after successful reservation allocation but before `self.persist()` of the Prototype intent can therefore leave durable RESERVED stock with no persisted Prototype intent. On restart `_find_intent()` can see no intent and `allocate_requirement()` can reserve replacement stock, especially for a multi-lot allocation.

This is an orphan-reservation / double-reservation crash window. Fix it without creating a second inventory ledger.

### Required correction

1. Make the prototype inventory operation recoverable **before any new reservation side effect can be duplicated**. Use the existing deterministic workOrder/op key, MaterialLot reservation state, transaction/outbox/journal and Prototype persistence.
2. A restart/retry must first reconcile existing compatible `RESERVED` or `CONSUMED` MaterialLot reservations belonging to the exact tenant + prototype operation/workOrder before allocating any replacement stock.
3. If you choose a PREPARED intent state, persist enough deterministic operation identity first and then bind the exact reservation IDs/lot IDs/quantities after allocation. If atomic cross-file commit is not possible, recovery must deterministically reconstruct the reservation set from MaterialLot state/journal and bind it to the intent.
4. Never silently create a second reservation for quantity already reserved or consumed by the same prototype operation.
5. If multiple prior reservation sets are ambiguous, incompatible with required material/thickness/grain/size, or cannot be proven to belong to this operation, fail closed / HOLD. Do not guess.
6. Keep final lineage based on authoritative MaterialLot reservation states; no boolean-only proof.
7. Tenant backup/restore semantic digest must continue to include the new inventory intent state.

### Required crash regressions

Add durable subprocess tests for both single-lot and multi-lot paths:

- inject `os._exit` immediately after successful reservation/allocation but before the final Prototype reservation-binding persistence;
- recreate `Platform` and retry the exact same prototype consume operation;
- no extra reserved quantity and no orphan reservation remains;
- no replacement reservation is created for quantity already reserved/consumed;
- exact workOrder/op key and reservation/lot lineage are preserved;
- final `available + reserved + consumed == sheetCount` for every affected lot;
- final consumed increment equals the required quantity exactly once;
- journal/outbox health is consistent;
- another retry after recovery is idempotent.

Do not remove the existing **after-first-consume** crash regressions; both crash windows must be covered.

---

## BLOCKER 2 — Packaging canonical validator is still fail-open for missing required variance fields and assembly variance

`_packaging_variance_contradicts()` currently rejects a packaging field only when the field exists as a dict and explicitly has `ok=false`. A missing/malformed required field is not a contradiction. It also checks only carton L/W/H + packed weight and does not validate the required `assemblyObservedVsEstimated` contract even though the pinned packaging policy includes assembly tolerance.

The generated canonical evidence is currently self-consistent, but the verifier must also reject incomplete/tampered evidence rather than only validate this happy-path generation.

### Required correction

For `packagingCompleteness=COMPLETE` + `packagingValidation.ok=true`, require fail-closed proof of the pinned policy:

1. `cartonLengthMm`, `cartonWidthMm`, `cartonHeightMm`, `packedWeightKg` must each exist, be dicts, be `complete=true`, and be `ok=true`.
2. Required assembly observed-vs-estimated evidence must exist, be `complete=true`, and be `ok=true` under the same acceptance policy.
3. Missing, malformed, `complete=false`, null, or `ok!=true` is failure; presence is not PASS.
4. Validate deterministic `packagingPolicyHash` lineage between the checklist/readiness board/matrix/canonical evidence wherever that hash is exposed. A stale or contradictory policy hash must fail closed.
5. Keep oversize, overweight, hardware/part-count, damage, missing-part and packing-fit rules unchanged.

### Required negative runner regressions

- remove each required packaging variance field one at a time => non-zero + no overwrite;
- required variance item malformed / `complete=false` / missing `ok` => non-zero;
- assembly variance missing => non-zero;
- assembly variance `complete=false` => non-zero;
- assembly variance `ok=false` while overall packaging says true => non-zero;
- packaging policy hash mismatch/stale => non-zero.

---

## BLOCKER 3 — Canonical success needs exact one-to-one selected → unit → matrix → board lineage

The validator currently verifies counts and many row fields, but it does not prove that the four selected SKUs, four PrototypeUnits, four matrix rows and corresponding decision-board rows are the **same four objects with the same lineage**. It also allows a unit with `buildCompleted != true` when its state is `WAITING_VALIDATION` / `VALIDATED` / `HOLD`, while the matrix can independently say `buildCompleted=true`.

The board is checked using the first four rows rather than by the exact selected candidate IDs. A shuffled, duplicated or unrelated board slice can therefore satisfy structural checks.

### Required correction

1. Build a canonical target map keyed by selected `candidateId` (and `selectionId`/`prototypeUnitId` where applicable). Reject duplicates.
2. For each of exactly four selected prototype targets, require exact one-to-one agreement across selected/unit/matrix/board for all applicable lineage:
   - `candidateId`;
   - `selectionId`;
   - `prototypeUnitId`;
   - `engineeringHash`;
   - `canonicalHash`;
   - `bomHash`;
   - `nestingHash`;
   - `rankingPolicyHash`;
   - evidence source / physical-validation state where applicable.
3. Do not infer `buildCompleted` from state. The authoritative unit must have `buildCompleted=true`, and matrix `buildCompleted` must exactly match it.
4. Validate the decision-board row by selected `candidateId`, not `rows[:4]`. If the board remains Top-10, that is fine, but all four selected candidates must have exactly one corresponding row.
5. The selected board row must not contradict matrix tolerance/QC/packaging/physical/evidence state.
6. Missing target, duplicate target, stale engineering lineage or cross-object mismatch => fail closed and do not overwrite the prior canonical truth set.

### Required negative runner regressions

- unit `buildCompleted=false` + state `WAITING_VALIDATION`, while matrix says true => non-zero;
- selected candidateId differs from matrix candidateId => non-zero;
- unit/matrix engineeringHash mismatch => non-zero;
- BOM/nesting/ranking lineage mismatch => non-zero;
- duplicate selected candidate or duplicate board candidate => non-zero;
- a selected candidate absent from decision board => non-zero;
- board tolerance/QC/packaging/physical state contradicts that candidate's matrix row => non-zero.

---

## Required delivery before re-review

1. Fix **only** the three integrity gaps above. **Do not start Phase 661+.**
2. Preserve all accepted logic and all prior regressions; add the new fail-closed/crash tests above.
3. Run full `pytest -q`; label it honestly as MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
4. Commit implementation/tests as a new **CODE_EVIDENCE_SHA** and require GitHub Actions Ubuntu + Windows GREEN on that exact SHA.
5. Run the acceptance runner on a clean tree bound to exact CODE SHA; regenerate canonical `PROTOTYPE_VALIDATION_ACCEPTANCE` + `SKU_LAUNCH_READINESS_ACCEPTANCE` from code, never by hand-editing JSON.
6. Canonical fixture software-loop may remain `FIXTURE / REAL_LOGIC`, cost may remain explicitly PARTIAL, and `physicalPrototypeValidated=false` is correct until genuine physical MANUAL/IMPORTED evidence exists.
7. Prior REAL Blender 4/4 on `7a87ea5...` may be reused only if the existing fail-closed verifier still passes and render/engineering/media path remains unchanged. If that path changes, generate fresh REAL Blender evidence.
8. Re-run tenant backup/restore semantic validation with inventory intents included.
9. Commit docs/evidence separately and require Ubuntu + Windows GREEN on docs/head.
10. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`; update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet truth actually changes.
11. Leave Issue #1 a concise completion comment with CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, pre-intent + post-consume crash recovery results, exact canonical lineage results, prior/fresh REAL Blender status, and remaining MOCK/PARTIAL/BLOCKED boundaries.
12. Stop for ChatGPT review. Do not enter Phase 661+ until **ACCEPT WITH SCOPE**.
