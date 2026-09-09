# Grok 修正指令：Phase 601–660 Final Integrity Corrections

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `594a1c11b244320e03bdf090996a74381a9f87c0`  
> Reviewed CODE_EVIDENCE_SHA: `244c707b67dffff0bdd3824fc5f46a5e16dadde0`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 661+. Fix Phase 601–660 only.**

## Accepted evidence — preserve it

This round is substantive and most of `d6d9458` is now correctly implemented. Correct in place; do not rewrite architecture.

- `consume_material_once(... consumes_inventory=true)` now delegates to the existing `MaterialLot` reservation/consume path and persists lot/reservation lineage.
- fixture-only prototype material remains `consumesInventory=false` / `FIXTURE`.
- as-built now requires completed build, structured tolerance/QC, authoritative DAM ownership/hash/size, and fixture evidence cannot set `physicalPrototypeValidated=true`.
- actual cost now separates physical quantities/time from currency amounts; required monetary categories can remain `PARTIAL` and minutes/counts are not summed into money.
- packaging requires explicit carton dimensions/packed weight, computes volumetric weight, count checks and damage/fit observations.
- ECO now accepts explicit allowed parametric changes and rebuilds through the existing KD / `CabinetSpec` path, with old→new lineage.
- decision board / manual-pilot gate are materially stronger and keep MOCK demand from upgrading readiness.
- prior REAL Blender evidence is now verified fail-closed from the prior canonical portfolio truth set: 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, prior CODE `7a87ea5...`.
- local `pytest -q` is reported as **356 passed**, explicitly MOCK/unit/integration + FIXTURE/REAL_LOGIC — not Production Ready.
- GitHub Actions CODE run `34365524103` is GREEN on Ubuntu + Windows for exact CODE `244c707...`.
- GitHub Actions docs/head run `34366046118` is GREEN on Ubuntu + Windows for `594a1c1...`.
- current canonical generation: `2934a4aa-6d6c-4d2c-a1fe-35863475f8e5`, clean-tree bound to CODE `244c707...`.
- keep Vision / AI Video / Demand = **MOCK**; OS sandbox / AR / preflight / barcode / McKee-BCT = **PARTIAL**; LIVE_CNC / LIVE_LASER / PLC / live provider / live factory = **BLOCKED**.
- keep `physicalPrototypeValidated=false` for fixture acceptance; keep `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveMachineControl=false`.

Do **not** replace Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD registry / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup architecture. Extend/reuse the existing transaction, outbox/journal, inventory and acceptance mechanisms only.

---

## BLOCKER 1 — Packaging tolerance is computed but not enforced

The current `packaging_checklist()` computes per-field `variance` / `evaluate_tolerance()` for carton L/W/H and packed weight, and also computes `assemblyObservedVsEstimated`, but those failures are not added to `reasons`. `ok` is currently based only on oversize/overweight, count mismatch, missing observations, damage, missing parts and packing-fit.

This is already visible in the committed canonical evidence: a selected SKU has `packagingPredictedVsObserved.packedWeightKg.ok=false` (target about 20.672kg, actual 13kg) while the same row says `packagingValidation.ok=true` / `reason="ok"`. That is contradictory and fail-open.

### Required correction

1. Packaging `ok=true` must require every required predicted-vs-observed packaging tolerance that is part of the pinned policy to pass.
2. Explicitly gate:
   - cartonLengthMm tolerance;
   - cartonWidthMm tolerance;
   - cartonHeightMm tolerance;
   - packedWeightKg tolerance;
   - assembly observed-vs-estimated tolerance when assembly is required by this acceptance contract.
3. Any configured tolerance failure must set an explicit blocker/reason and move the unit/SKU to HOLD or NEEDS_ECO according to the existing state model. Do not silently downgrade it to merely informational variance.
4. Keep oversize/overweight, hardware/part counts, damage, missing-part and packing-fit checks; do not weaken them.
5. Persist a single deterministic `packagingPolicyHash` / tolerance-policy lineage so the board can prove which policy made the decision.
6. Do not fabricate carrier/provider truth. Carrier remains CONFIG_ESTIMATE / IMPORTED / MANUAL.

### Required regressions

- each individual carton dimension out of tolerance => packaging `ok=false`;
- packed weight out of tolerance but under max 30kg => `ok=false`;
- assembly time out of tolerance => packaging/readiness blocker where policy requires it;
- exact in-tolerance fixture values => packaging software-loop PASS while physical prototype still remains false;
- canonical evidence must never contain `packagingValidation.ok=true` while a required packaging variance row has `ok=false`.

---

## BLOCKER 2 — Canonical runner still accepts false tolerance / missing-or-partial packaging semantics

`validate_prototype_acceptance_result()` currently checks that `toleranceStatus` exists, not that the required fixture contract passes. It also accepts `packagingCompleteness` values `MISSING` / `PARTIAL` as structurally valid. The runner therefore published `ok=true` even though the committed 4 selected matrix rows have `toleranceStatus=false`.

The previous instruction explicitly required negative regressions for **tolerance contract false** and **missing required packaging evidence**. The current runner tests only reject an invalid packaging string such as `"nope"`; they do not prove that `MISSING` / `PARTIAL` or `toleranceStatus=false` fail the successful software-loop acceptance.

### Required correction

1. Separate **schema validity** from **acceptance semantics**. Presence of a key is not a PASS.
2. For a canonical Phase 601–660 software-loop PASS:
   - exactly 4 selected + 4 units + 4 matrix rows;
   - `buildCompleted=true` for all 4;
   - required tolerance/QC structure present and semantically valid;
   - for the fixture software-loop success path, use deterministic in-tolerance fixture observations so `toleranceStatus=true` for all 4;
   - required packaging must be `COMPLETE` and `packagingValidation.ok=true` for all 4;
   - packaging per-field required variance cannot contradict packaging overall status;
   - fixture actual-cost may remain explicitly `PARTIAL` if the contract intentionally demonstrates `WAITING_PHYSICAL_EVIDENCE`, but that state/blocker must be consistent and cannot become pilot approval;
   - `physicalPrototypeValidated=false` remains mandatory for fixture evidence;
   - `liveMachineControl=false`, MOCK demand, and global/full/live Production Ready flags remain false.
3. Fail closed if board/matrix semantic values contradict each other (e.g. matrix tolerance false but board state not blocked; packaging overall true while required variance false).
4. Do not make `result.ok` authoritative; recompute acceptance from canonical evidence, as intended.
5. A failed rerun must not overwrite the last valid canonical truth set; preserve atomic publication/rollback.

### Required negative runner tests

Add one independent regression for each:

- `toleranceStatus=false` => non-zero, no overwrite;
- missing tolerance result => non-zero;
- `packagingCompleteness=MISSING` => non-zero;
- `packagingCompleteness=PARTIAL` on a required package => non-zero;
- `packagingValidation.ok=false` => non-zero;
- packaging overall true + any required per-field variance `ok=false` => non-zero;
- missing QC required observation => non-zero;
- stale lineage => non-zero;
- fixture physical flag true => non-zero;
- tenant restore mismatch => non-zero.

After correction, regenerate the canonical acceptance; do not hand-edit the JSON to make it green.

---

## BLOCKER 3 — Real inventory consume still has a crash window between lot consumption and PrototypeUnit lineage persistence

The normal retry test is now much better, but the crash/restart guarantee is not complete. `consume_material_once()` first obtains one or more durable reservations, then calls `consume_reservation()` for each reservation, and only after the loop persists `materialConsumed=true` + `inventoryLineage` on the PrototypeUnit.

If the process dies after one durable `consume_reservation()` but before PrototypeUnit lineage is persisted, stock can be partially/fully consumed while the prototype record still looks unconsumed. A restart may allocate/consume additional stock. Ordinary same-process retry does not prove this failure mode.

### Required correction

Reuse the existing MaterialLot transaction/outbox/journal/recovery model; **do not create a second inventory ledger**.

1. Before destructive consume, durably pin a prototype inventory intent containing exact workOrderId, requirement, reservation IDs/lot IDs/quantities and an operation/idempotency key.
2. Consumption and recovery must be reconcilable from the existing durable reservation states / journal/outbox.
3. On restart, if some/all pinned reservations are already `CONSUMED`, reconcile those exact records into PrototypeUnit lineage; never allocate replacement stock for already-consumed quantity.
4. If only part of a multi-lot reservation set was consumed before crash, resume/reconcile the remaining pinned reservation set exactly once.
5. Final PrototypeUnit lineage must match the actual durable consumed reservation states and total quantity.
6. If safe reconciliation cannot be proven, fail closed / HOLD; never guess and never double-consume.

### Required crash regressions

Use a real subprocess / `os._exit` style test (or the existing crash injection mechanism) against durable files:

- crash immediately after first reservation consumption in a multi-lot requirement;
- recreate `Platform` and retry the same prototype operation;
- final total consumed increment equals required quantity exactly once;
- exact reservation/lot lineage is preserved;
- no new replacement reservation is created for already-consumed quantity;
- journal/outbox/health are consistent after recovery;
- repeat retry after recovery remains idempotent.

This should extend the existing crash-safe inventory pattern, not introduce new architecture.

---

## Acceptance / truth labels for this correction round

A correct result may be **ACCEPT WITH SCOPE** even without a real physical prototype. The software workflow can be accepted as `FIXTURE / REAL_LOGIC` only if its internal contract is fully self-consistent and fail-closed.

Keep these boundaries:

| Slice | Required truth |
|---|---|
| Prototype orchestration / ECO / validation logic | REAL_LOGIC |
| CI prototype measurements / packaging / cost | FIXTURE (cost may be PARTIAL) |
| Physical prototype built and measured | false / WAITING_PHYSICAL_EVIDENCE unless genuinely manual/imported evidence exists |
| Prior Blender portfolio media | REAL only via verified prior canonical 4/4 T1000 OptiX evidence |
| Demand / Vision / AI Video | MOCK |
| OS sandbox / AR / preflight / barcode / McKee-BCT | PARTIAL |
| Supplier/carrier/FX/receipts where applicable | IMPORTED / MANUAL / CONFIG as already modeled |
| LIVE_CNC / LIVE_LASER / PLC / live provider | BLOCKED |
| global/full/live Production Ready | false |

---

## Required delivery before re-review

1. Fix **only** the three Phase 601–660 integrity blockers above. Do not start Phase 661+.
2. Add all positive + negative regressions listed above, including durable crash/restart inventory recovery.
3. Run full `pytest -q`; report honestly as MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
4. Commit implementation/tests as a new **CODE_EVIDENCE_SHA**.
5. Require GitHub Actions Ubuntu + Windows GREEN on that exact CODE SHA.
6. Run the acceptance runner on a clean tree bound to exact CODE SHA.
7. Regenerate `PROTOTYPE_VALIDATION_ACCEPTANCE` and `SKU_LAUNCH_READINESS_ACCEPTANCE` from the runner; canonical 4/4 fixture software-loop rows must be semantically consistent.
8. Prior REAL Blender 4/4 on `7a87ea5...` may continue to be reused only if the existing fail-closed verifier still passes and the render/engineering/media path remains unchanged. If that path changes, run fresh REAL Blender evidence instead.
9. Commit docs/evidence separately, then require Ubuntu + Windows GREEN on docs/head.
10. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`; update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet truth actually changed.
11. Leave Issue #1 a concise completion comment containing CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, inventory crash-recovery result, fixture tolerance/packaging result, prior/fresh REAL Blender status, and remaining MOCK/PARTIAL/BLOCKED boundaries.
12. Stop and wait for ChatGPT review. **Do not enter Phase 661+ until ACCEPT WITH SCOPE.**
