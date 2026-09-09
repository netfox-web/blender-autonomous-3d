# Grok 修正指令：Phase 601–660 Prototype Validation Integrity Corrections

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `900191c86d2593ca6c1ea9de60cdf5be2ab33e7e`  
> Reviewed CODE_EVIDENCE_SHA: `66a66d1feda59cfe77fe8f5ceb21032d86f2c3f8`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 661+. Fix Phase 601–660 only.**

## Accepted evidence — preserve it

The new Phase 601–660 implementation is substantive and should be corrected in place, not rewritten:

- durable prototype selection / PrototypeUnit / as-built / ECO / observed-cost / packaging / decision records exist;
- fixture actor is prevented from producing `MANUAL_EVIDENCE` in the canonical scenario;
- canonical acceptance is bound to clean CODE SHA and uses atomic publication;
- TENANT_SCOPED backup now includes prototype state and current restore digest is equal;
- local `pytest -q` is reported as **341 passed**, explicitly MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready;
- GitHub Actions CODE run `34357037364` is GREEN on Ubuntu + Windows for `66a66d1`;
- docs/head run `34357513520` is GREEN on Ubuntu + Windows for `900191c`;
- `physicalPrototypeValidated=false` for CI fixture evidence;
- Demand remains MOCK; Vision / AI Video remain MOCK; OS sandbox / AR / preflight / barcode / McKee-BCT remain PARTIAL; LIVE_CNC / LIVE_LASER / PLC / live provider / live factory execution remain BLOCKED;
- `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveMachineControl=false` are correct;
- prior 4/4 REAL Blender evidence on `7a87ea5` may be reused because this phase did not change the portfolio/media/engineering render path, but the reuse reference must itself be verified fail-closed as described below.

Do **not** replace Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD registry / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup architecture. Extend existing paths only.

---

## BLOCKER 1 — `consume_material_once` currently does not consume real durable inventory

Current code sets `materialConsumed=true`, `consumedSheets=N`, `consumesInventory=true` inside `PrototypeUnit`, but does not reserve/consume from the existing MaterialLot / WorkOrder inventory path. This proves only an internal boolean/counter, not inventory conservation.

### Required correction

1. If a prototype unit declares `consumesInventory=true`, delegate to the **existing** MaterialLot / WorkOrder reservation+consume mechanism. Do not create a second inventory ledger.
2. Pin the exact required material SKU / thickness / dimensions / grain policy and exact lot/reservation IDs used.
3. Retry/restart/idempotency must not consume a second time.
4. A shortage or incompatible material must fail closed and leave all lots unchanged.
5. Persist enough lineage on the PrototypeUnit to audit the existing inventory transaction IDs / lot IDs / consumed quantities.
6. If a prototype uses no real inventory path (e.g. CI fixture-only), keep `consumesInventory=false` and label the material observation `FIXTURE`; do not claim inventory consumption.

### Required regressions

- before/after durable lot quantities prove exact conservation;
- retry + recreate `Platform` + retry again => same consumed quantity and same transaction/lot lineage;
- wrong SKU/thickness/grain cannot satisfy the prototype requirement;
- partial shortage rolls back with zero orphan reservation/consume;
- boolean-only `materialConsumed=true` with unchanged stock must cause acceptance failure.

---

## BLOCKER 2 — as-built evidence can validate a prototype without enforcing engineering tolerances / completed build state

Current `PASS_AS_BUILT` effectively allows a non-fixture actor to set `physicalPrototypeValidated=true` when the five required numbers merely exist and engineeringHash matches. It does not require the unit to have completed the build, does not evaluate tolerance policy, and does not require the defect/QC observations that Phase 601–660 specified.

### Required correction

1. `record_as_built` / `PASS_AS_BUILT` must require the unit to be at the correct completed-build state (`WAITING_VALIDATION` or equivalent existing state). A `PLANNED`, `WAITING_HUMAN_START`, or `IN_BUILD` unit cannot become physically validated.
2. Compute a structured tolerance result for every required numeric field using the pinned engineering-policy tolerance. Do not merely store variance.
3. Out-of-tolerance required dimensions/weight/assembly observations must result in HOLD / REWORK / NEEDS_ECO according to explicit policy; they must not silently become `VALIDATED`.
4. Add required structured observations, with explicit `NOT_APPLICABLE + reason` only where truly inapplicable:
   - missing/damaged/incorrect hardware;
   - panel/edge/finish defects;
   - wobble/stability observation;
   - door/drawer fit where applicable;
   - rework count / defect count.
5. Physical safety/load/tip-over remains engineering/manual observation only; never certification unless separately evidenced.
6. For DAM refs, do not trust caller-supplied `tenantId`, `sha256`, or `size` as ownership proof. Resolve the referenced DAM object from the existing DAM store and verify authoritative tenant ownership + hash/size. Forged or missing ownership metadata must fail closed.
7. `IMPORTED` packaging/as-built evidence must stay `IMPORTED_EVIDENCE`, not be relabeled `MANUAL_EVIDENCE`.

### Required regressions

- a PLANNED unit with perfect manual values cannot validate;
- a completed unit with a large width/height/weight/time deviation cannot validate;
- missing required defect/QC observations cannot validate;
- forged Tenant-B DAM ref carrying `tenantId=A` must reject after authoritative lookup;
- fixture evidence still cannot set physical validated;
- old engineeringHash evidence still cannot validate a new ECO revision.

---

## BLOCKER 3 — actual prototype cost currently mixes physical units into a currency total and is fail-open on omitted components

Current `record_actual_cost()` sums whatever numeric values are supplied. For example `laborMinutes` + sheet counts + hardware counts can become a numeric `total`, which is not a monetary cost. It also marks a record complete when omitted required categories are absent from the input; only explicitly supplied `None` becomes missing.

### Required correction

1. Separate **quantity/time observations** from **monetary cost components**. Examples:
   - quantities/time: sheetsConsumed, materialArea, hardwareQty, laborMinutes, reworkMinutes, packagingQty;
   - currency: materialAmount, hardwareAmount, laborAmount, reworkAmount, packagingAmount, shippingAmount, externalProcessingAmount.
2. Never sum minutes/counts/sheets into a currency total.
3. Define the required accounting categories for a complete observed prototype cost. Omitted required categories must be `MISSING`, not silently ignored.
4. If material accounting is incomplete, total observed cost remains `PARTIAL` / `None` as specified; do not zero-fill.
5. Preserve original CONFIG_ESTIMATE snapshot separately and calculate comparable estimate-vs-observed monetary variance only when the observed monetary set is complete enough.
6. Pin exact prototypeUnitId + engineeringHash + source label + currency + costSnapshotHash / lineage.
7. MANUAL / IMPORTED remains MANUAL / IMPORTED, never LIVE_PROVIDER.
8. Remnant credit may only enter observed monetary variance when an existing real/manual remnant-return record is referenced.

### Required regressions

- `{laborMinutes: 40}` alone cannot become a complete actual monetary cost;
- omission of material accounting remains PARTIAL even if all supplied values are numeric;
- unit quantities are not added to currency total;
- stale engineeringHash cannot reuse the old observed cost;
- estimate and observed cost snapshots remain immutable across restart;
- wrong currency / non-finite / negative invalid monetary inputs fail closed.

---

## BLOCKER 4 — packaging validation is incomplete and missing dimensions can silently become `1`

Current packaging logic uses `observed.get(dim) or 1`; missing carton dimensions may therefore pass. It only gates longest side and packed weight, and does not implement the required predicted-vs-observed / volumetric / assembly / hardware / part-count / defect validation.

### Required correction

1. Require all authoritative carton dimensions and packed weight for a completed packaging validation. Missing values must be `WAITING_VALIDATION` / BLOCKED, never replaced by `1` or another default.
2. Pin the same engineeringHash / prototypeUnitId for predicted and observed packaging.
3. Compute and store:
   - predicted vs observed carton L/W/H variance;
   - predicted vs observed packed weight variance;
   - volumetric weight using an explicit CONFIG policy/divisor;
   - assembly observed vs estimate;
   - expected vs observed hardware/part count;
   - packing-fit / missing-part / damage/defect observations.
4. Oversize, overweight, missing required observations, packing mismatch, or configured tolerance failure must put the SKU/unit on HOLD or NEEDS_ECO.
5. Carrier remains CONFIG_ESTIMATE / IMPORTED / MANUAL; no booking.
6. Barcode hardware remains PARTIAL unless separately evidenced.
7. `IMPORTED` packaging evidence must keep the imported label.

### Required regressions

- missing each individual carton dimension fails;
- missing packed weight fails;
- oversize/overweight fails;
- hardware-count/part-count mismatch fails;
- material packing damage/defect observation fails according to explicit policy;
- predicted and observed different engineeringHash fails;
- volumetric-weight computation is deterministic and policy-hash pinned.

---

## BLOCKER 5 — ECO currently changes revision/hash but has no actual engineering-change input

Current accepted ECO creates a new revision/hash, but it rebuilds the same geometry parameters and does not accept an explicit engineering change. This is not sufficient for a physical-prototype feedback loop where a dimensional/assembly/packing problem must be corrected.

### Required correction

1. Extend the existing ECO path with an explicit, validated engineering change payload (only allowed parametric/product fields; no arbitrary mutation).
2. Apply changes through the existing `CabinetSpec` / KD engine / rule engine. Do not hand-edit generated BOM/nesting/cost.
3. Recompute engineeringHash, BOM, nesting, DFM, commercial snapshot, packing and any affected media/release lineage through existing engines.
4. Store exact old→new field changes and hashes in the append-only ECO record.
5. A no-op ECO must fail unless explicitly classified as a documented non-engineering revision; a non-engineering revision must not pretend BOM/nesting/cost changed.
6. Old prototype evidence/cost/packaging/ranking/release cannot validate the new engineering version.

### Required regressions

- change width/height/thickness through ECO => authoritative engineering/BOM/nesting lineage changes appropriately;
- invalid rule/geometry ECO rejects before replacing current candidate;
- no-op engineering ECO rejects;
- restart preserves full revision chain and old→new changes;
- stale evidence cannot qualify the new candidate.

---

## BLOCKER 6 — decision board and pilot-approval gate do not yet meet Phase 649–654

Current readiness output omits several required decision fields, `READY_FOR_HUMAN_GO_NO_GO` is not concretely produced, and `approve_pilot_batch()` can record a pilot decision before it directly verifies all required packaging/cost/QC evidence.

### Required correction

For every selected candidate, decision board must expose and pin:

- ranking score + rankingPolicyHash;
- DFM/conservation;
- expected sheet utilization / true scrap / reusable remnant;
- prototype/build state;
- tolerance result and dimensional variance;
- assembly observed vs estimated;
- observed vs estimated monetary cost + completeness label;
- packaging predicted vs observed + validation result;
- QC/defects/rework status;
- REAL Blender media lineage (or verified prior REAL media reference);
- demand truth label;
- exact blockers and evidence source labels.

`approve_pilot_batch()` must independently fail closed unless:

- current engineering/ranking/cost/nesting lineage is non-stale;
- physical prototype validation is MANUAL_EVIDENCE / IMPORTED_EVIDENCE, not FIXTURE;
- required tolerance/QC evidence passes;
- required packaging evidence exists and passes;
- required actual-cost completeness policy is satisfied or an explicit human exception policy is recorded (do not silently treat PARTIAL as complete);
- human/operator + open shift + reason are valid;
- MOCK demand did not upgrade the state.

Define a deterministic path to `READY_FOR_HUMAN_GO_NO_GO`; it must still keep `productionReady=false` and `liveMachineControl=false`.

### Required regressions

- `PROTOTYPE_VALIDATED` with no packaging cannot create pilot approval;
- validated prototype with PARTIAL required actual cost cannot auto-qualify;
- stale ECO/ranking/cost lineage blocks;
- decision board missing any required field fails acceptance;
- MOCK demand never upgrades GO state;
- fixture actor/evidence cannot approve pilot batch.

---

## BLOCKER 7 — canonical acceptance runner is fail-open on the substantive Phase 601–660 contract

The current runner can return/publish `ok=true` with a hook scenario containing four selected FIXTURE records, `physicalPrototypeValidated=false`, **empty decision board**, no cost/packaging/tolerance evidence, and no media. `result.ok` is currently hardcoded true by the scenario and is too weak as the acceptance authority.

### Required correction

1. The acceptance runner must independently validate the Phase 601–660 evidence structure; do not rely on `result.ok=True`.
2. Canonical acceptance must contain a per-selected-4 structured matrix with at least:
   - selection and exact lineage hashes;
   - PrototypeUnit state and evidence source;
   - build completed status;
   - tolerance/QC status;
   - actual-cost completeness + monetary variance status;
   - packaging completeness + variance status;
   - ECO/current-version status;
   - decision-board state/blockers;
   - physicalPrototypeValidated flag;
   - live-machine flags.
3. Fixture canonical acceptance may correctly finish with `WAITING_PHYSICAL_EVIDENCE`; that is a PASS for the **software workflow only** if all fixture-path contracts are verified. Do not fabricate a physical PASS.
4. Add negative runner tests where each of these is broken independently: empty/malformed board, missing required packaging evidence, cost marked complete incorrectly, tolerance contract missing/false, stale lineage, physical flag from fixture, tenant restore mismatch.
5. Failed acceptance must remain non-zero and must not overwrite prior successful canonical files.
6. Keep generation/commit/clean-tree atomic publication checks already implemented.

### Prior REAL Blender evidence reuse

Because Phase 601–660 did not change portfolio/media/engineering render paths, a new render is not mandatory. However, do not accept a free-form metadata pointer as proof.

The runner/canonical verifier must fail closed unless the referenced prior REAL evidence can be read and verifies:

- exact prior code commit `7a87ea5...` and generation `0b76b09e-...` (or the actual accepted prior canonical values);
- 4/4 cases;
- Blender 5.2.1 LTS + NVIDIA T1000 OptiX;
- `usedMock=false`;
- per-case job ID, artifact SHA-256, positive size, GPU/Blender lineage and exact engineering candidate lineage;
- prior canonical truth set itself is internally valid.

If implementing this verification is awkward, rerunning fresh clean-tree 4/4 REAL Blender on the corrected CODE SHA is an acceptable stronger alternative. Do not label CI mock media as REAL.

---

## Backup/restore — keep current direction, tighten acceptance only

Current `prototype/prototype.json` tenant filtering and prototype domain digest are accepted as the baseline. Do not redesign backup.

For the corrected round, acceptance must still prove exact Tenant-A identity/lineage preservation and zero Tenant-B leakage for:

- selections;
- units;
- measurements/evidence refs;
- ECO chain + field changes;
- observed-cost snapshots;
- packaging checklists;
- decisions/idempotency.

Any newly added durable fields must be included in the semantic digest, not merely counted.

---

## Required delivery before re-review

1. Fix **only Phase 601–660 integrity gaps** above. Do not start Phase 661+.
2. Add negative regressions for every blocker.
3. Run full `pytest -q`; report it honestly as MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
4. Commit implementation/tests as a new **CODE_EVIDENCE_SHA**.
5. Push and require Ubuntu + Windows Actions GREEN on exact CODE SHA.
6. Run clean-tree acceptance bound to that exact CODE SHA.
7. Produce a separate docs/evidence commit and require Ubuntu + Windows Actions GREEN on docs/head.
8. Update:
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/PROTOTYPE_VALIDATION_ACCEPTANCE.md` + JSON
   - `docs/SKU_LAUNCH_READINESS_ACCEPTANCE.md` + JSON
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet-specific truth actually changed.
9. Leave Issue #1 a concise completion comment with CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, prior/fresh REAL Blender evidence status, and remaining truth boundaries.
10. Stop and wait for ChatGPT review. **Do not begin Phase 661+.**

## Truth boundaries remain mandatory

- Prototype workflow logic: `REAL_LOGIC`
- CI-generated physical values: `FIXTURE`
- Actual human-entered physical evidence: `MANUAL_EVIDENCE`
- Imported evidence: `IMPORTED_EVIDENCE`
- Commercial: `CONFIG_ESTIMATE`
- Actual cost: `MANUAL / IMPORTED / FIXTURE / PARTIAL` as applicable, never LIVE_PROVIDER without proof
- Demand / Vision Judge / AI Video: `MOCK`
- OS sandbox / AR / preflight / barcode hardware / McKee-BCT: `PARTIAL / ENGINEERING_ESTIMATE`
- supplier / carrier / FX / receipts: `IMPORTED / MANUAL` unless independently live-proven
- LIVE_CNC / LIVE_LASER / PLC / automatic factory execution / live provider: `BLOCKED`
- `liveMachineControl=false`
- `liveFactoryExecutionReady=false`
- `liveProviderReady=false`
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`

A corrected Phase 601–660 acceptance proves an auditable prototype-validation **software loop**. It does not prove that a real physical prototype has been built, tested, certified, or launched.