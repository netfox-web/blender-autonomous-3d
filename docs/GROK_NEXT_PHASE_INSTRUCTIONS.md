# Grok 修正指令：Phase 361–420 Reliability / Tenant & Stock Integrity

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `450993fa60df2907739b87e4efe0c4bb806f8784`  
> Reviewed CODE_EVIDENCE_SHA: `068cbe8218a47d69edd9cbe79db9fe169e37b509`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 421+ yet. Fix only the gaps below. Do not rewrite the existing architecture.**

## Evidence accepted from this round

The following evidence is valid within scope and does not need to be re-described as stronger than it is:

- GitHub Actions code run `34290377181` on `068cbe8`: ubuntu + windows **SUCCESS**.
- GitHub Actions docs/head run `34290489149` on `450993f`: **SUCCESS**.
- Local `pytest -q`: `156 passed`, but this remains **MOCK/unit/integration + FIXTURE** evidence, not Production Ready.
- 4/4 Blender EvidenceBundles are **REAL** for Blender/render scope: Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, clean committed code SHA `068cbe8`, release-bound, artifact hash/size verifier PASS.
- Vision / AI Video / Demand remain **MOCK**.
- OS sandbox / AR / print preflight / barcode / McKee/BCT remain **PARTIAL / ENGINEERING_ESTIMATE**.
- Supplier/carrier/FX/receipts remain **IMPORTED / MANUAL** business data unless a real authenticated provider is connected.
- LIVE_CNC / LIVE_LASER / live machine execution / live provider remain **BLOCKED**.
- `globalProductionReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `fullAutonomousFactoryReady=false` must remain false.

---

# Blocking finding 1 — STRICT_STOCK is not transaction-safe on partial shortage

Current `WorkOrderService.reserve_materials()` reserves from available lots one-by-one and only afterwards discovers whether the total is insufficient. Under `STRICT_STOCK`, if some sheets were reserved and `remaining > 0`, it raises `StockShortage` **without rolling back the reservations already taken in that attempt**. The WorkOrder has not yet stored those reservation IDs, so they can become orphan-held inventory.

This violates the required fail-closed/conservation behavior even though the existing no-stock test passes.

## Required fix

Keep `MaterialLotRegistry` and `WorkOrderService`; do not add a second inventory engine.

Implement one of these small-scope approaches:

1. **Preflight then reserve atomically** under the existing registry transaction/lock boundary, or
2. reserve provisionally and **rollback every reservation created by the current attempt** if the full requirement cannot be satisfied.

The result must guarantee:

- failed `STRICT_STOCK` reservation leaves all lot quantities exactly as before the attempt;
- no orphan reservation remains;
- retrying the failed request does not progressively consume/hold stock;
- conservation remains `available + reserved + consumed == received/adjusted` for every lot.

## Mandatory regressions

- Need 5 sheets, lot A has 2 and lot B has 1: reserve fails SHORTAGE and both lots return to their exact before-state.
- Repeat the same failed reserve 10 times: quantities/reservation count unchanged after every failure.
- Restart after failed reserve: no leaked reservation appears from persisted `lots.json`.
- Concurrent shortage attempts cannot leave partial holds.

---

# Blocking finding 2 — WorkOrder reservation ignores material compatibility

Current `reserve_materials()` calculates the release-required `material` and `thickness`, but selects from `self.lots.list(tenant_id=tid, allocatable=True)` without filtering by material SKU/thickness. Therefore a PB/wood WorkOrder can reserve an unrelated material lot merely because it has free sheets.

## Required fix

Before reservation, candidate lots must be compatible with the ManufacturingRelease snapshot. At minimum enforce:

- exact material / sheet SKU match;
- thickness match within a deterministic tolerance appropriate to stored numeric representation;
- quarantined/blocked lots excluded as already intended;
- if dimensions/grain are manufacturing-significant for the release, enforce them too rather than silently substituting.

Do not silently coerce another SKU into a match. A mismatch is unavailable stock and contributes to structured SHORTAGE evidence.

## Mandatory regressions

- Required `PB_18_WHITE`, only `OAK` stock exists -> SHORTAGE; OAK quantities unchanged.
- Required 18 mm, only 12 mm stock exists -> SHORTAGE; 12 mm lot unchanged.
- Compatible lots across multiple receipts can satisfy one WO and conserve quantities.
- Quarantined matching SKU cannot satisfy the WO.

---

# Blocking finding 3 — New Pilot API tenant boundary is fail-open in several write/read paths

Phase 409–414 requires tenant-scoped Pilot API behavior. Current new/modified endpoints often use `payload.get("tenantId") or tenant(X-Tenant-Id)`, allowing request-body tenant IDs to override the authoritative tenant header. Also `ReceivingService.import_receipt()` accepts caller-provided idempotency keys in one global `_idem` map without forcing tenant scope. A reused key can therefore resolve to another tenant's receipt. Finally `PilotOperations.console()` returns `list(self.logistics.shipments.values())` without tenant filtering, while shipment records themselves do not carry an authoritative tenant ID.

These are multi-tenant isolation blockers.

## Required fix

Use the existing tenant/auth boundary; do not invent a second identity system.

- For normal Pilot/material production/manual API routes, `X-Tenant-Id` (or the existing authenticated tenant source) is authoritative.
- If body `tenantId` is present and differs from the authenticated/header tenant, reject the request (403/409). Do not switch tenants.
- Scope receipt idempotency internally as `(tenant_id, caller_key)` or equivalent. The caller should not need to prefix the key manually.
- A tenant B retry using the same raw idempotency key as tenant A must never return A's receipt or lot.
- Add tenant identity to shipment drafts from their cartons/work order. All cartons in one shipment must belong to exactly one tenant.
- Reject cross-tenant carton mixing.
- `pilot.console(tenant_id=...)` must return only that tenant's shipments, cartons, receipts, purchase requests, WOs, releases and QC rows.
- Do not expose a global shipment list through a tenant-scoped console.

Apply the same authoritative-tenant rule to the Phase 361–420 routes you modified (`/api/materials/lots`, `/api/pilot/receipts`, `/api/pilot/purchase-requests`, `/api/pilot/work-orders/.../reserve`) and any directly adjacent new Pilot route. Do not broaden this into an unrelated full API rewrite.

## Mandatory regressions

- Header tenant A + body tenant B on receipt/material/purchase-request -> rejected; no object created in B.
- Tenant A and tenant B both use raw idempotency key `same-key` -> two tenant-local receipts; neither can retrieve/affect the other's object.
- Tenant A console never includes tenant B shipment/carton/receipt/WO/release/QC data.
- Shipment draft mixing carton IDs from A and B -> rejected.
- Missing tenant header on tenant-scoped Pilot write/read routes -> fail closed according to the existing API convention.

---

# Blocking finding 4 — Phase 415–420 acceptance runner does not fail closed on reliability result

`run_pilot_e2e.py` executes `stress = plat.pilot.reliability.run(...)` and publishes `PILOT_RELIABILITY_ACCEPTANCE`, but final `required_ok` does not directly require the stress contract itself. It only checks REAL Blender/canonical/release conditions and the global false readiness flags. A broken reliability stress could therefore still allow exit 0 / canonical publish.

## Required fix

Add one explicit reliability gate used by `required_ok`. It must require, at minimum:

- `label == FIXTURE`;
- expected WorkOrder count >= 50;
- operation transitions >= 250;
- `noOversell == true`;
- `materialConserved == true`;
- receipt idempotency true;
- quarantine blocked true;
- pack mismatch negative true;
- shipment remains draft/not booked;
- required negative cases actually present and failed;
- plus the new partial-shortage rollback, material mismatch and tenant-isolation negative cases from this correction.

If any required reliability assertion is false/missing, runner must:

- return non-zero;
- not publish/overwrite canonical accepted evidence;
- report which reliability condition failed.

Do not label the 50-WO stress REAL factory throughput. It remains **FIXTURE**.

## Mandatory runner regressions

Inject a hooks/pipeline result with each of these broken one at a time and prove `main()` exits non-zero and does not publish:

- `noOversell=false`;
- `materialConserved=false`;
- missing required negative evidence;
- too few WOs/ops;
- shipment marked booked/submitted;
- partial-shortage rollback false;
- tenant-isolation false.

Also keep the existing clean-tree, commit lineage, 4/4 REAL Blender, releaseHash, canonical-generation and atomic-publish fail-closed tests.

---

# Required test/evidence sequence before re-review

1. Make code/test fixes first and commit them as a new **CODE_EVIDENCE_SHA**.
2. Run `pytest -q`; report count but label it MOCK/unit/integration/FIXTURE, not Production Ready.
3. Push and require GitHub Actions ubuntu + windows GREEN for the code commit.
4. Because code SHA changed, run the existing REAL acceptance path again from a **clean committed tree** and produce 4/4 release-bound `usedMock=false` Blender/T1000 OptiX EvidenceBundles bound to the new CODE_EVIDENCE_SHA.
5. `PILOT_RELIABILITY_ACCEPTANCE.json` must include explicit results for:
   - `partialShortageRollback=true`,
   - `materialCompatibility=true`,
   - `tenantIsolation=true`,
   - plus the existing no-oversell/conservation/idempotency/negative checks.
6. Update `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md` only with facts actually re-proven.
7. Do not edit `CABINET_REAL_ACCEPTANCE.md` unless cabinet evidence changed.
8. Commit docs/evidence separately where practical, push, and require current-head CI GREEN.
9. Keep Human Approval Gate and all LIVE machine/provider blockers unchanged.

# Exit criteria

Do **not** claim Phase 361–420 accepted until all are true:

- failed strict reservation is transaction-neutral (no partial hold/leak);
- lot selection matches required material/thickness and cannot substitute unrelated stock;
- receipt idempotency is tenant-scoped regardless of raw caller key;
- body tenant cannot override authoritative request tenant;
- shipment/carton console data is tenant-scoped and cross-tenant mixing is rejected;
- reliability acceptance itself is part of `required_ok` and fails closed;
- all new negative regressions pass;
- code CI and docs/head CI are GREEN;
- new clean-tree 4/4 REAL Blender evidence is bound to the new code commit;
- Mock/Fixture/Imported/Partial/Blocked truth labels remain honest;
- `globalProductionReady=false` and `fullAutonomousFactoryReady=false` remain false.

When complete, update the normal handoff files and leave Issue #1 a concise completion note with CODE_EVIDENCE_SHA, test result, CI runs, REAL evidence summary and truth labels.