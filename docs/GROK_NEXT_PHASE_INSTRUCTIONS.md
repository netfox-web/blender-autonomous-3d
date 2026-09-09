# Grok 開發指令：Phase 601–660 Prototype Validation & SKU Launch Readiness V1

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `ac12f93628cf00b522146f3a2b71db3425b63141`  
> Reviewed CODE_EVIDENCE_SHA: `7a87ea5cedc5242178d7e072de1b9b89c4c60d14`  
> ChatGPT review result: **ACCEPT WITH SCOPE**  
> Phase 541–600 integrity blockers are accepted. **Phase 601–660 is authorized.**

## Accepted baseline — preserve, do not rewrite

Phase 541–600 now has auditable fail-closed evidence:

- manufacturing envelope fields are finite and `>0`; invalid explicit inputs fail before persistence;
- DFM material conservation is independently recomputed from `sheetMm × sheetCount` vs placed + remnant + true scrap; missing authoritative fields do not become zero;
- remnant-first planning enforces tenant + material + thickness + grain compatibility and distinguishes candidate vs actually-used remnant IDs; planning does not consume inventory;
- canonical acceptance contains 10/10 Top-10 lineage rows and 4 detailed REAL Blender media cases bound to CODE `7a87ea5`;
- fresh REAL media = Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, artifact SHA-256 and positive size, exact evidence code commit;
- local `pytest -q`: **327 passed**, explicitly MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready;
- GitHub Actions CODE run `34351349710`: Ubuntu + Windows SUCCESS on `7a87ea5`;
- docs/head run `34351867909`: Ubuntu + Windows SUCCESS on `ac12f936`;
- `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveMachineControl=false` remain correct.

Do **not** rebuild Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD registry / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup. Extend the existing paths only.

---

# Goal of Phase 601–660

Move from “software-ranked SKU portfolio” to a **human-controlled physical prototype validation loop** for small-space / student / rental KD products.

The system must support:

`Top 10 → human selects prototype set → manual prototype work orders → as-built measurements/evidence → QC/assembly/packing/actual-cost variance → ECO/revision loop → pilot-batch readiness → human go/no-go`

This phase does **not** authorize live CNC, laser, PLC, automatic factory execution, automatic purchasing, automatic carrier booking, or unreviewed product launch.

The key truth boundary is:

- software workflow / deterministic calculations = `REAL_LOGIC`;
- operator-entered measurements / photos / timestamps = `MANUAL_EVIDENCE` or `IMPORTED_EVIDENCE`;
- CI-generated prototype data = `FIXTURE`;
- a fixture must never be called a real physical prototype;
- only evidence originating from an explicit human/operator import may qualify as physical pilot evidence;
- physical safety / load / tip-over checks are engineering observations unless backed by a real certified test; do not label them certification.

---

## Phase 601–608 — Prototype Selection & Human Identity Gate

1. Add a durable prototype-selection record for Top-10 candidates.
2. Selection must pin:
   - tenantId
   - candidateId
   - canonicalHash
   - engineeringHash
   - bomHash
   - nestingHash
   - costSnapshotHash
   - rankingPolicyHash
   - selected ranking score
   - selectedAt
   - selectedBy operator identity
   - shift/session identity where available
   - reason
3. Reuse existing Operator/Shift identity. Do not accept an arbitrary string as proof of a physical human action.
4. CI/FIXTURE may use a clearly labeled fixture actor, but must produce `FIXTURE`, never `MANUAL_EVIDENCE`.
5. A stale/superseded/rejected candidate cannot be selected.
6. Default pilot target: select **4 representative SKUs** from Top 10; preserve Top-10 ranking and human override separately.
7. Selection is not machine authorization and must keep `liveMachineControl=false`.

Required tests:

- disabled/closed-shift/cross-tenant operator cannot select;
- stale candidate lineage blocks selection;
- fixture actor cannot produce MANUAL_EVIDENCE;
- superseded/rejected candidate blocks selection;
- restart preserves selection exactly.

---

## Phase 609–616 — Prototype Unit & Manual Build Traveler

1. Introduce a durable `PrototypeUnit` (or equivalent existing-domain record) for each physical prototype unit.
2. Each unit must pin the selected candidate/version hashes and a unique prototypeUnitId.
3. Build traveler must reuse existing ManufacturingRelease / WorkOrder / MANUAL_STATION conventions where practical; do not create a second MES.
4. Traveler contains human-readable operations only; `machineCommand=false`, `liveCnc=false`, `liveLaser=false`.
5. Build states should be fail-closed, e.g.:
   - `PLANNED`
   - `WAITING_HUMAN_START`
   - `IN_BUILD`
   - `WAITING_VALIDATION`
   - `VALIDATED`
   - `HOLD`
   - `REWORK`
   - `SCRAPPED`
6. Only a selected, non-superseded engineering version may create a prototype unit.
7. If actual inventory reservation is invoked, use the existing MaterialLot/WorkOrder reservation path and tenant isolation. CI must use fixture inventory only.
8. Restart/retry must not create duplicate prototype units or duplicate material consumption.

Required tests:

- idempotent create/start/complete;
- no double consume after restart/retry;
- exact engineering/release lineage preserved;
- cross-tenant access blocked;
- superseded engineering version cannot silently continue as current.

---

## Phase 617–624 — As-Built Measurement & Physical Evidence Capture

Add operator/imported as-built evidence without pretending CI can measure a real object.

Per prototype unit capture at minimum:

- measured width/depth/height;
- measured assembled weight;
- measured carton length/width/height and packed weight when available;
- actual assembly minutes;
- actual operation/rework count;
- missing/damaged/incorrect hardware observations;
- panel/edge/finish defects;
- wobble/stability observation;
- door/drawer fit observation where applicable;
- operator identity + timestamp;
- evidence source (`MANUAL`, `IMPORTED`, `FIXTURE`);
- DAM references for photos/video/documents if supplied;
- SHA/size for imported evidence artifacts when DAM exposes them.

Rules:

1. Preserve engineering target and as-built values separately; never overwrite target dimensions.
2. Calculate absolute and percentage variance for every numeric observation.
3. Define configurable prototype tolerances; label them engineering policy, not certification.
4. Missing required real measurements => `WAITING_VALIDATION`, not PASS.
5. FIXTURE measurements may test logic but cannot set `physicalPrototypeValidated=true`.
6. Manual/imported evidence must be tenant-scoped and operator-attributed.
7. Do not fabricate physical photographs or measurement values in REAL acceptance.

Required negative tests:

- NaN/Inf/non-numeric/negative impossible values fail closed;
- fixture source cannot become MANUAL/REAL;
- missing required measurements cannot validate;
- wrong engineeringHash / prototypeUnitId rejects evidence;
- cross-tenant DAM/evidence reference rejects.

---

## Phase 625–632 — QC Variance, ECO & Revision Loop

1. Compare as-built evidence to the pinned Engineering Definition/BOM/packing target.
2. Produce a structured variance report with severity and source evidence.
3. Support Human decisions:
   - `PASS_AS_BUILT`
   - `REWORK_CURRENT_UNIT`
   - `CREATE_ECO`
   - `HOLD_SKU`
   - `SCRAP_UNIT`
4. `CREATE_ECO` must create a **new immutable engineering version/hash**. Never mutate the accepted engineering hash in place.
5. Existing prototype evidence remains pinned to the old version.
6. New ECO version must invalidate stale BOM/nesting/cost/media/release/ranking lineage and force recomputation through existing engines.
7. A superseded version cannot be newly approved for prototype/pilot batch.
8. Preserve append-only revision reason, actor, timestamps and old→new lineage.
9. If geometry/BOM changes, regenerate cost/nesting and update the portfolio candidate lineage; do not silently reuse stale values.

Required regressions:

- old prototype evidence cannot validate a new engineeringHash;
- ECO changes engineering hash and invalidates stale cost/nesting;
- rejected ECO cannot replace current version;
- restart preserves revision chain;
- tenant A cannot inspect/approve tenant B ECO.

---

## Phase 633–640 — Actual Prototype Cost & Time Variance

Keep estimates and actual observations separate.

Capture actual/manual/imported values where available:

- material used / sheets consumed;
- remnant returned;
- true scrap observed;
- hardware actually consumed;
- labor minutes;
- rework minutes;
- packaging material used;
- prototype shipping/courier amount if manually imported;
- external processing amount if manually imported.

Requirements:

1. Do not overwrite `CONFIG_ESTIMATE` snapshot.
2. Create a separate `actualPrototypeCost` / `observedCostSnapshot` with per-component source labels.
3. `FIXTURE` actual costs stay FIXTURE.
4. `MANUAL` / `IMPORTED` values are not `LIVE_PROVIDER`.
5. Compute estimate vs observed variance with exact engineeringHash and prototypeUnitId lineage.
6. If material accounting is incomplete, mark total actual cost `PARTIAL`, not zero-filled PASS.
7. Remnant credit may only be observed when a real/manual remnant return record exists; otherwise keep estimate separate.

Required tests:

- missing actual component does not become 0 silently;
- estimate and observed snapshots remain immutable and distinguishable;
- stale engineering version cannot reuse observed cost;
- tenant isolation and restart persistence.

---

## Phase 641–648 — Packaging, Assembly & Logistics Validation

1. Build a physical-validation checklist for the 4 selected prototype SKUs.
2. Compare predicted vs observed:
   - carton dimensions;
   - packed weight;
   - volumetric weight calculation;
   - assembly time;
   - hardware count;
   - packing fit / part count;
   - damage/defect observations.
3. Carrier price remains `IMPORTED/MANUAL/CONFIG_ESTIMATE` unless a real provider adapter is independently present; no carrier booking.
4. Barcode hardware remains PARTIAL unless real scan hardware evidence exists.
5. Packaging drop/compression/load observations are MANUAL evidence only; no certification claim.
6. A failed packing/assembly validation must place SKU on HOLD or ECO, not still become pilot-batch ready.
7. Record final carton target revision only through an explicit revision/ECO path.

Required tests:

- oversize/overweight observed carton blocks readiness;
- missing packed weight does not PASS;
- predicted vs observed comparison uses same SKU engineering version;
- no automatic provider/carrier truth promotion.

---

## Phase 649–654 — Pilot Batch Readiness & Decision Board

Create a human-facing decision model for Top-10 / selected-4, but do not auto-launch products.

Per candidate show:

- ranking score + policy hash;
- DFM / conservation;
- expected sheet utilization / scrap / remnant;
- prototype status;
- measured dimensional variance;
- assembly observed vs estimated;
- observed vs estimated cost;
- packaging observed vs estimated;
- QC/rework status;
- REAL Blender media evidence;
- demand truth label;
- blockers.

Allowed readiness states:

- `NOT_SELECTED`
- `READY_FOR_PROTOTYPE`
- `PROTOTYPE_IN_PROGRESS`
- `WAITING_PHYSICAL_EVIDENCE`
- `HOLD`
- `NEEDS_ECO`
- `PROTOTYPE_VALIDATED`
- `READY_FOR_MANUAL_PILOT_BATCH`
- `READY_FOR_HUMAN_GO_NO_GO`

Rules:

1. `READY_FOR_MANUAL_PILOT_BATCH` requires explicit human approval and complete required validation evidence.
2. It is not Production Ready and not automatic machine execution.
3. MOCK demand must not positively upgrade readiness.
4. A human may override ranking only with actor + reason; preserve deterministic score.
5. Never create an unscoped `productionReady=true`.

---

## Phase 655–660 — Acceptance, Backup/Restore, CI & REAL Evidence

Create/update canonical acceptance:

- `docs/PROTOTYPE_VALIDATION_ACCEPTANCE.md` + JSON
- `docs/SKU_LAUNCH_READINESS_ACCEPTANCE.md` + JSON
- update `docs/REAL_E2E_ACCEPTANCE.md`
- update `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- update `docs/GROK_PROGRESS_REPORT.md`
- update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet-specific truth changed.

Acceptance requirements:

1. New durable prototype/evidence/ECO/actual-cost state must be included in TENANT_SCOPED backup/restore semantic contract.
2. Tenant A restore must preserve exact prototypeUnit IDs, engineering lineage, evidence hashes, ECO chain and cost snapshot identity, with zero Tenant B leakage.
3. Runner must be bound to exact clean `CODE_EVIDENCE_SHA` and fail closed on dirty tree / wrong SHA.
4. Acceptance files must be published atomically with one generation ID; failed run must not overwrite prior truth set.
5. Full `pytest -q` count must be reported as MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
6. Require Ubuntu + Windows Actions GREEN on exact CODE SHA; then GREEN on docs/head.
7. Run fresh clean-tree **4/4 REAL Blender** for the four prototype-selected SKU engineering versions on final CODE SHA if portfolio/media/engineering render path changed. Each case must retain the existing per-case SHA/size/job/GPU/commit requirements.
8. Physical prototype acceptance truth:
   - if only fixture measurements exist: `physicalPrototypeValidated=false`, label `FIXTURE`;
   - if real operator/imported evidence is actually supplied and lineage-valid: label `MANUAL_EVIDENCE` / `IMPORTED_EVIDENCE`, not automated REAL sensor truth;
   - never fabricate a physical PASS to satisfy acceptance.
9. Pilot batch acceptance must remain MANUAL-STATION scoped; `liveFactoryExecutionReady=false`.

Minimum acceptance regressions:

- fixture actor/evidence cannot set physical validated;
- missing required measurement blocks validation;
- stale engineering/ECO lineage blocks validation/readiness;
- incomplete actual cost stays PARTIAL;
- packaging validation failure blocks pilot readiness;
- backup/restore preserves exact new durable identities;
- cross-tenant leakage fails;
- dirty tree / mismatched expected SHA fails without overwriting prior acceptance;
- MOCK demand cannot influence GO state;
- LIVE_CNC/LASER/PLC remains BLOCKED.

---

# Truth labels that remain unchanged unless independently proven

- Candidate generation / DFM / ranking: `REAL_LOGIC`
- Cross-SKU/remnant planning: `REAL_LOGIC / PLANNING`
- Prototype workflow code: `REAL_LOGIC`
- CI prototype units / measurements: `FIXTURE`
- Human-entered physical measurements/photos: `MANUAL_EVIDENCE`
- Imported physical records: `IMPORTED_EVIDENCE`
- Commercial estimate: `CONFIG_ESTIMATE`
- Actual manual/imported prototype cost: `MANUAL / IMPORTED`, possibly `PARTIAL`
- Demand: `MOCK` unless a separately evidenced imported/manual source exists; never relabel MOCK as REAL
- Vision Judge: `MOCK`
- AI Video: `MOCK`
- OS sandbox / AR / preflight / barcode hardware / McKee-BCT: `PARTIAL / ENGINEERING_ESTIMATE`
- supplier / carrier / FX / receipt data: `IMPORTED / MANUAL` unless separately live-proven
- LIVE_CNC / LIVE_LASER / PLC / automatic machine execution / live provider: `BLOCKED`
- `liveMachineControl=false`
- `liveFactoryExecutionReady=false`
- `liveProviderReady=false`
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`

# Delivery / handoff

When Phase 601–660 is complete:

1. Commit implementation/tests as a new CODE_EVIDENCE_SHA.
2. Push and capture CODE Ubuntu + Windows CI run ID.
3. Run clean-tree acceptance bound to that exact SHA.
4. Generate canonical docs/evidence separately and capture docs/head CI run ID.
5. Update `docs/GROK_PROGRESS_REPORT.md` with REAL/MOCK/PARTIAL/BLOCKED matrix, pytest count, evidence generation, selected prototype SKUs, backup semantic result, REAL Blender cases, and remaining blockers.
6. Leave Issue #1 a concise completion comment with CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation and truth-label summary.
7. Do not start Phase 661+ until ChatGPT reviews the committed evidence.

## Exit gate

Phase 601–660 is successful only when the software prototype loop is fail-closed and auditable. A successful fixture acceptance proves the software workflow, **not** that real physical prototypes were built or Production Ready.
