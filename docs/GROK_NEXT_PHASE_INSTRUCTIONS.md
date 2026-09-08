# Grok 下一輪開發指令：Phase 361–420 Pilot Reliability / Manufacturing Control Boundary V1

> Repo: `netfox-web/blender-autonomous-3d`  
> Review head: `e5f3e6ce722c16f222a5bdb6d8f57efb34512383`  
> Reviewed CODE_EVIDENCE_SHA: `414847d9b183fb7175461e5a886dfbe9337b5a73`  
> ChatGPT review result: **ACCEPT WITH SCOPE**  
> Phase 301–360 correction exit criteria are materially satisfied. Proceed to Phase 361–420, but keep all existing truth boundaries.

## Accepted evidence from the previous round

- Local `pytest -q`: **144 passed**, explicitly **MOCK/unit/integration suite — not Production Ready**.
- GitHub Actions code run `34283481326`: **SUCCESS**, `unit (ubuntu-latest)` + `unit (windows-latest)`.
- GitHub Actions docs/head run `34283611233`: **SUCCESS** on `e5f3e6c`.
- MaterialLot reserve/cancel/consume conservation is now explicit and tested; retry consume is idempotent and cross-tenant access is rejected.
- Required FINAL QC is authoritative; `complete(..., qc_ok=True)` cannot bypass zero/missing/failed required FINAL checks.
- Phase 358 `noDoubleConsume` is observed from state, has a positive assertion and a negative regression; this remains **FIXTURE/simulation evidence**.
- REAL Blender acceptance is **4/4** on Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, clean committed code SHA `414847d`, artifact hash/size verified, and each artifact is bound to the exact accepted ManufacturingRelease with non-null matching `releaseHash` plus engineering/BOM lineage.
- `run_pilot_e2e` now requires canonical truth-set consistency and fails non-zero on mixed generation/commit, missing/malformed files, or release-lineage mismatch without overwriting the accepted files.
- Missing readiness evidence defaults false/UNVERIFIED.

## Truth labels that remain unchanged

- **REAL within scope:** release package generation/verification, manual WorkOrder flow, QC logic/traceability, lot reservation logic, real Blender/OptiX rendering evidence.
- **IMPORTED / MANUAL:** supplier quotes, carrier quotes, FX, actual-cost imports, measured operational inputs unless a real authenticated provider is actually connected.
- **FIXTURE / TEST_DATA:** stress runs, synthetic demand, test QC data, auto-seeded test inventory.
- **PARTIAL / ENGINEERING_ESTIMATE:** OS sandbox (`PATH_GUARD_ONLY`), AR, barcode printing, print preflight, McKee/BCT/packaging strength.
- **MOCK:** Vision Judge, AI Video, Demand unless a genuine provider is connected and separately accepted.
- **BLOCKED:** LIVE_CNC, LIVE_LASER, live machine control, electrical compliance, live provider actions without credentials.
- `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false` must remain false.

---

# Non-negotiable architecture rules

1. **Do not rewrite** Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / RemnantStore / ReleaseGate / ManufacturingRelease / WorkOrder / QC / Physical Product OS.
2. Do not create a second ERP, WMS, MES, QMS, inventory master, approval system, evidence system, render queue, or DAM.
3. Extend the existing services with small ports/adapters/state rules only.
4. Human Approval Gate remains mandatory for manufacturing release/export.
5. No autonomous purchase, payment, carrier booking, CNC, laser, or machine actuation in this phase.
6. A successful import/parser/API call may be **REAL logic**, but imported business data itself stays **IMPORTED/MANUAL**. Do not label imported supplier/carrier data `REAL_PROVIDER`.
7. Do not use fixture auto-generation to hide unavailable material, missing QC, unavailable provider, unavailable machine, or missing evidence.
8. Preserve the existing clean-commit / EvidenceBundle / atomic acceptance publish semantics.

---

# Phase 361–368 — Inventory truth, strict stock policy, concurrency safety

The current manual pilot is accepted as a simulation boundary, but one important hardening item must be addressed first: `WorkOrderService.reserve_materials()` can currently create a new MaterialLot when stock is missing/insufficient. That is acceptable only as an explicit **FIXTURE/test convenience**; it must not silently fabricate stock in a normal/manual-production path.

## Required work

- Add an explicit material allocation policy to the existing WorkOrder/Pilot path, e.g.:
  - `STRICT_STOCK` — default for non-test/manual-production API paths.
  - `FIXTURE_AUTO_SEED` — allowed only for tests / explicit pilot fixture runners and labeled FIXTURE.
- Under `STRICT_STOCK`, insufficient stock must fail closed with a structured shortage result; **do not auto-create inventory**.
- Material lot creation for real/manual pilot inventory must happen through an explicit receipt/import path, not a hidden side effect of reserve.
- Keep existing `MaterialLotRegistry`; do not add a second inventory service.
- Make lot reserve/consume/release read-modify-write atomic inside the existing registry lock/version mechanism.
- Add deterministic stale-version/CAS behavior if needed so two simultaneous reservations cannot oversell the same sheets.
- Preserve tenant isolation and the invariant:
  `available + reserved + consumed == received/adjusted quantity`.
- Persist reservation state and prove restart/reload retains the same quantities, reservation ownership and idempotency state.
- Add explicit inventory adjustment events only if needed; every adjustment must record actor, reason, source, tenant, before/after quantities and hash. No silent mutation.

## Required regressions

- Two threads/process-simulated callers race to reserve the last sheet: at most one succeeds; no negative stock; conservation holds.
- 20–50 concurrent reserve attempts on a small lot: no oversell and deterministic failures.
- Retry the same idempotency key: same reservation, no extra decrement.
- Restart/reload: reserved quantity and reservation owner survive.
- Cancel after reserve: only unconsumed quantity returns.
- Cancel after partial consume: consumed stock stays consumed; only remaining reservation is released.
- `STRICT_STOCK` with no stock => BLOCKED/SHORTAGE, no generated lot.
- `FIXTURE_AUTO_SEED` is visibly labeled FIXTURE and inaccessible from the normal production/manual API default.

---

# Phase 369–376 — WorkOrder state-machine hardening

Use the existing `WorkOrderService`; add transition validation rather than a new workflow engine.

## Required work

- Define one authoritative transition table for current WorkOrder states.
- Reject illegal transitions rather than silently changing state.
- Starting a manufacturing operation requires a released, fresh ManufacturingRelease and successful material reservation.
- `COMPLETED` requires:
  - all required operations completed,
  - authoritative FINAL QC passed,
  - required packing/carton state present where the family requires it,
  - release still matches the WorkOrder-bound releaseHash,
  - no unresolved REJECT/SCRAP/QC_HOLD.
- Retry of `release`, `reserve`, `start op`, `complete op`, `consume`, `packing`, `complete`, `cancel` must be deterministic/idempotent where semantically valid.
- Every state transition records actor, timestamp, from/to, reason, idempotency key and hash in the existing WorkOrder lineage/audit structure.
- Do not add MES machine control.

## Required negative tests

- operation before release/material reserve => fail;
- complete with open operation => fail;
- complete without packing when required => fail;
- complete with QC_HOLD => fail;
- stale/superseded release cannot start a new WorkOrder;
- completed WorkOrder cannot be cancelled or mutate consumption;
- cross-tenant WorkOrder actions fail.

---

# Phase 377–384 — QC Traceability V2 / release-pinned inspection plan

Extend the existing `QcService`; do not build a second QMS.

## Required work

- Freeze the required QC schema/check set into the ManufacturingRelease or WorkOrder snapshot using a version/hash.
- A later config/schema change must not silently change the inspection requirements of an already-released WorkOrder.
- QC records must include source truth: `TEST_DATA`, `MANUAL`, `IMPORTED`, or `DEVICE`; `DEVICE` does not imply calibrated/certified unless separate calibration evidence exists.
- Add optional gauge/device ID, lot ID, operation ID, DAM photo/document refs and operator.
- Latest FINAL result semantics must remain fail closed.
- Rework cycle must preserve failed record + defect/disposition + corrective operation + new final result; do not overwrite history.
- Add trace query path from productVersion/releaseHash/workOrder -> material lot/remnant -> operations -> QC -> carton.

## Acceptance

- Release A pins QC plan hash A; config changes to B; WorkOrder from A still requires A.
- Missing/failed required check still blocks completion.
- Cross-tenant QC cannot satisfy another tenant.
- Rework history remains append-only and traceable.

---

# Phase 385–392 — ManufacturingRelease revision / supersession control

Reuse `ManufacturingReleaseService` and the Human Approval Gate.

## Required work

- Add explicit immutable revision/supersession lineage:
  `releaseId/releaseHash -> supersededBy -> new releaseId/releaseHash`.
- Produce a deterministic diff summary for engineeringHash, bomHash, nesting/cut plan, packing, cost snapshot and QC-plan hash.
- A superseded/stale release cannot create a new WorkOrder.
- An already in-progress WorkOrder remains bound to its original releaseHash; policy must explicitly mark whether it may finish or requires HOLD/reapproval. Do not silently rebind it.
- Any material engineering/BOM/manufacturing change requires the existing Human Approval Gate again.
- Approval audit must identify the exact releaseHash being approved.

## Negative tests

- modify engineering after approval -> old release stale/superseded;
- attempt new WO from old release -> fail;
- attempt to mutate old release packet -> checksum fail;
- approval for release A cannot authorize release B.

---

# Phase 393–400 — Receiving / procurement boundary without autonomous purchasing

Do not add payment or purchase execution. Reuse supplier/provider snapshots and MaterialLotRegistry.

## Required work

- Add a lightweight `PurchaseRequest` / `MaterialReceipt` adapter only if needed; it must be a boundary object, not a second ERP.
- RFQ/quote comparison may produce `DRAFT_PURCHASE_REQUEST` / `WAITING_HUMAN_APPROVAL`; it must never send a PO or payment.
- A **MANUAL/IMPORTED receipt** can create/increase a MaterialLot with:
  supplier ID, supplier lot, material SKU, dimensions/thickness, received qty, unit cost snapshot, received time, source, actor, optional COA/DAM refs.
- Quantity/material/thickness mismatch can quarantine the receipt or create a discrepancy record; no silent acceptance.
- Only accepted receipt quantity becomes `available` stock under `STRICT_STOCK`.
- Supplier and receipt source labels stay MANUAL/IMPORTED unless a real provider is actually connected.

## Acceptance

- shortage -> draft purchase request, not stock fabrication;
- imported receipt -> lot availability increases exactly by accepted quantity;
- quarantined receipt -> unavailable to nesting/reservation;
- retry receipt import by idempotency key -> no duplicate stock.

---

# Phase 401–408 — Packaging / shipment execution boundary

Reuse current LogisticsService / carton plan. No live carrier booking.

## Required work

- Distinguish expected carton plan from measured carton facts.
- Validate pack completeness: expected SKU/qty/parts vs recorded contents; shortages/duplicates must block shipment-ready scope.
- Bind carton IDs to workOrderId, batchId, productVersion/releaseHash, lot/remnant lineage where relevant.
- Measured dimensions/weight remain MANUAL/IMPORTED unless a real scale/dimensioner integration is separately evidenced.
- Generate `SHIPMENT_DRAFT` / carrier request payload only; `submittedToCarrier=false` by default.
- Barcode payload can be generated, but physical printer integration remains PARTIAL until actually tested on hardware.
- Carrier quote stays IMPORTED unless real provider credentials/API are connected.

## Acceptance

- carton content conservation positive + missing/duplicate negative tests;
- expected and measured data remain separate/immutable;
- shipment draft cannot claim booked/shipped;
- retry pack/ship draft is idempotent.

---

# Phase 409–414 — Pilot Operations console/API on existing Admin surface

Do not create a new frontend stack or second backend.

## Required work

Extend existing Admin/API to expose, by tenant:

- material lots: available/reserved/consumed/quarantined + shortage status;
- WorkOrders: state, releaseHash, material reservations, open operations, QC holds, packing state;
- release revision/supersession status and approval evidence;
- QC failures/rework queue;
- receipt/import status;
- shipment drafts and measured-vs-expected carton facts;
- truthful badges: REAL / IMPORTED / MANUAL / FIXTURE / PARTIAL / MOCK / BLOCKED.

No LIVE_CNC/LIVE_LASER buttons that imply enabled control. Existing machine-control fields stay false/blocked.

Add tenant/RBAC negative tests using the existing auth boundary where available; do not invent a second identity system.

---

# Phase 415–420 — Reliability acceptance / clean-commit pilot evidence

## Required fixture stress

Create a repeatable **FIXTURE** stress scenario (not REAL factory throughput claim):

- >= 50 WorkOrders across KD / retail / packaging / acrylic;
- >= 250 operation transitions;
- concurrent competition for limited MaterialLots;
- retries of reserve/consume/state transitions;
- cancellations before and after partial consume;
- stale/superseded release attempts;
- QC fail -> rework -> pass;
- tenant isolation attacks;
- receipt idempotency;
- carton content mismatch negatives.

Must prove:

- no negative stock / no oversell;
- material conservation;
- no double consume;
- no duplicate receipt stock;
- no illegal state transition accepted;
- no QC bypass;
- no stale/superseded release creates a new WO;
- all expected negative cases actually fail.

Label this **FIXTURE / simulation**, not factory capacity.

## REAL acceptance

After code/tests are committed:

1. Record a new clean `CODE_EVIDENCE_SHA`.
2. Run `pytest -q`; state exactly which tests are MOCK/unit/integration/FIXTURE.
3. Push and require GitHub Actions `ubuntu-latest` + `windows-latest` GREEN for the code commit.
4. From a **clean committed tree**, run the existing REAL acceptance path on the actually detected Blender/OptiX worker.
5. Produce at least **4/4 current-code, release-bound REAL Blender EvidenceBundles** for KD / retail / packaging / acrylic with:
   - `usedMock=false`,
   - actual Blender/OptiX worker identity,
   - expected/bundle CODE_EVIDENCE_SHA match,
   - non-null exact `releaseHash`,
   - engineeringHash/BOM hash match where applicable,
   - artifact hash + byte size verification.
6. Reuse the current atomic/staged acceptance system. Do not create a second evidence publisher.
7. Add/update one scoped acceptance pair, preferably `docs/PILOT_RELIABILITY_ACCEPTANCE.md` + `.json`, and update existing progress/audit/REAL_E2E docs only where facts changed.
8. Do not edit `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet evidence actually changes.
9. Commit docs/evidence separately where practical; require current-head CI GREEN.

---

# Evidence hygiene required in this round

There is one non-blocking wording issue from the accepted Phase 301–360 evidence: a row such as `supplier quotes imported` can currently have row status `REAL` while its data source is `IMPORTED`. In the next docs/evidence refresh, make the distinction unambiguous:

- importer/parser/compare **logic execution** may be `REAL`;
- supplier/carrier/FX **business data truth** must be `IMPORTED` / `MANUAL` unless live provider evidence exists.

Do not change historical evidence merely to make it look stronger. Clarify labels without inflating readiness.

---

# Exit criteria for ChatGPT re-review

Do not claim Phase 361–420 complete unless all are true:

1. Normal/manual WorkOrder reservation defaults to strict real inventory; missing stock cannot silently auto-create a MaterialLot.
2. Fixture auto-seed, if retained, is explicit and labeled FIXTURE only.
3. Concurrent reservation cannot oversell; available/reserved/consumed is conserved across retry/restart/cancel/partial consume.
4. WorkOrder state transitions are validated and fail closed; completion requires closed ops + authoritative QC + required packing.
5. QC plan is release-pinned and rework history is append-only/traceable.
6. Superseded/stale release cannot spawn a new WO; approval is exact-releaseHash scoped.
7. Material receipt is MANUAL/IMPORTED, idempotent, and is the explicit source of strict stock; quarantine cannot be allocated.
8. Shipment stays draft/not-booked unless a real carrier provider is separately connected.
9. Fixture stress negative cases truly fail and are labeled FIXTURE, not REAL factory throughput.
10. Local tests pass; code CI ubuntu+windows GREEN; docs/head CI GREEN.
11. REAL acceptance is from a clean committed CODE_EVIDENCE_SHA with 4/4 release-bound `usedMock=false` Blender/OptiX evidence.
12. `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false` unless future genuine evidence explicitly changes those scopes.
13. LIVE_CNC / LIVE_LASER remain BLOCKED and Human Approval Gate remains mandatory.
14. Vision / AI Video / Demand remain MOCK unless genuine provider execution is separately evidenced.
15. No existing core architecture was rewritten and no second ERP/WMS/MES/QMS/evidence system was introduced.

---

# Required Issue #1 handoff

When complete, leave one concise Issue #1 comment with:

- code SHA + evidence/docs SHA;
- local pytest count and exact MOCK/FIXTURE note;
- code/head Actions run IDs and ubuntu/windows result;
- strict-stock/no-phantom-lot result;
- concurrent reserve/consume conservation result;
- WorkOrder illegal-transition regressions;
- QC-plan pinning + QC bypass/rework result;
- release supersession/stale-WO result;
- receipt idempotency/quarantine result;
- shipment draft/not-booked boundary;
- FIXTURE stress counts and negative-case results;
- 4/4 REAL release-bound Blender EvidenceBundle result;
- remaining MOCK/PARTIAL/IMPORTED/MANUAL/BLOCKED boundaries;
- `fullAutonomousFactoryReady=false`.

Do not ask the user to copy/paste the report. ChatGPT will read the repository and Issue directly.
