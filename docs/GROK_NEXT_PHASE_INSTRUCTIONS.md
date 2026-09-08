# Grok 下一輪開發指令：Phase 301–360 Manufacturing Release & Pilot Operations

> Repo: `netfox-web/blender-autonomous-3d`
> Re-review head: `b55b52c1f90405f9fc0f6c2c2cd1c8e0cd31bad9`
> Evidence code commit: `513ae9df9093005409794b021a533e70edeec9bf`
> ChatGPT review result: **ACCEPT WITH SCOPE**
>
> Phase 241–300 + Evidence Integrity corrections are now materially acceptable within the documented scope. Runner-level `main()` regressions exist; required evidence failures return non-zero; canonical acceptance is staged then `os.replace()` published with rollback; clean-tree REAL evidence is 5/5 Blender 5.2.1 + NVIDIA T1000 OptiX with `usedMock=false`, bundle/expected commit SHA = `513ae9d`, hash/size verifier PASS; CODE CI run `34273759566` and head/docs CI run `34273902323` are GREEN on ubuntu+windows. Local `pytest 120 passed` remains MOCK/unit-regression evidence only, not Production Ready.
>
> Truth labels stay unchanged: Vision / AI Video / Demand are MOCK; OS sandbox / AR / print preflight / barcode / packaging strength remain PARTIAL or ENGINEERING_ESTIMATE; supplier/material/logistics snapshots are MANUAL/IMPORTED unless a real provider is actually connected; LIVE_CNC / LIVE_LASER / electrical compliance / liveProviderReady remain BLOCKED; `globalProductionReady=false`; `fullAutonomousFactoryReady=false`.

---

## Non-negotiable architecture rules

1. **Do not rewrite** Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / RemnantStore / ReleaseGate / existing Physical Product OS modules.
2. Extend existing modules with adapters/services/models only where necessary; no second ERP, WMS, MES, job queue, asset store, approval system, or product master.
3. No LIVE machine execution. CNC / laser / printer / carrier / supplier integrations may expose interfaces and imported snapshots, but actual actuation remains BLOCKED unless explicitly supplied and separately approved in a future instruction.
4. Human Approval Gate remains mandatory before any manufacturing release package is considered released.
5. Any engineering/material/cost/package change must stale the downstream approval/release package via hashes/version lineage.
6. MOCK / FIXTURE / CONFIG / ENGINEERING_ESTIMATE / MANUAL / IMPORTED must never be upgraded to REAL_PROVIDER or Production Ready by wording.
7. Keep all tests cross-platform (ubuntu + windows) and deterministic. CI MOCK suite is not REAL Blender evidence.

---

# Phase 301–304 — Evidence Set Reader / Generation Consistency close-out

The previous blocker is accepted, but there is one hygiene item to close before adding new functionality.

### 301 — Canonical truth-set reader

Use the existing `generations_consistent(...)` logic (or fold it into the current acceptance gate) so a caller can read the canonical six JSON truth files as one set and reject:

- mixed `acceptanceGenerationId`
- mixed `evidenceCodeCommit`
- missing required canonical file
- malformed JSON

Do **not** create a second acceptance system.

### 302 — Aggregate consistency check

`PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE` or the existing aggregate acceptance path must expose a machine-verifiable result that all six canonical JSON truth files belong to the same generation and evidence commit.

### 303 — Regression coverage

Successful publish regression must verify **all six** JSON truth files, not only two. Add mixed-generation / missing-file / mixed-commit read regressions.

### 304 — Preserve current evidence semantics

Do not rerun historical Phase 241–300 REAL acceptance merely for this unit hygiene unless code changes touch the REAL runner/evidence path. If they do, use the clean committed CODE_EVIDENCE_SHA process again.

---

# Phase 305–312 — Immutable Manufacturing Release Package V1

Build a release package that converts an approved product version into a **human-executable manufacturing packet**, not machine control.

### 305 — `ManufacturingRelease` model

Create a versioned immutable release record bound to at least:

- tenantId
- productId / productVersion
- productFamily
- engineeringHash
- bomHash
- nesting/placement hash where applicable
- material snapshot/version ids
- packaging hash
- approval audit hash
- createdBy / approvedBy / releasedAt
- `releaseHash`
- status

Suggested statuses:

`DRAFT -> VALIDATED -> WAITING_APPROVAL -> APPROVED_FOR_MANUAL_RELEASE -> RELEASED_FOR_MANUAL_EXECUTION -> STALE / CANCELLED`

Do not use `APPROVED_FOR_MANUAL_RELEASE` as an alias for LIVE_CNC.

### 306 — Release stale rules

Any change to engineering/BOM/material/nesting/packaging/cost-policy inputs must stale the release.

### 307 — KD manufacturing packet

Generate deterministic artifacts from existing SoT:

- release manifest JSON
- BOM CSV
- cut list CSV
- nesting SVG / existing DXF-friendly output
- edge-banding list
- hardware pick list
- assembly-step manifest
- carton/packing manifest
- checksum manifest

### 308 — Retail fixture packet

Same release architecture; include planogram/display dimensions and fixture-specific hardware/load estimate labels. Electrical remains BLOCKED/non-certified.

### 309 — Packaging packet

Include dieline SVG/DXF-friendly output, fold sequence, material/board grade snapshot, print/preflight truth labels. McKee/BCT remains ENGINEERING_ESTIMATE.

### 310 — Acrylic packet

Include sheet/cut plan, thickness/finish, bend/assembly notes if represented, and laser/CNC export artifact only. LIVE_LASER remains BLOCKED.

### 311 — Release package checksum / tamper detection

Every emitted artifact must be in a manifest with SHA-256 + byte size. Release verifier must fail if an artifact changes after approval.

### 312 — Release acceptance

Create `docs/MANUFACTURING_RELEASE_REAL_ACCEPTANCE.md` + JSON. REAL means deterministic release generation + verified hashes + real Blender evidence where render evidence is required; it does **not** mean a factory machine executed the packet.

---

# Phase 313–320 — Supplier RFQ / Quote Comparison Boundary

No automatic purchasing and no fake live provider.

### 313 — Supplier capability profile

Add a provider-neutral capability profile for materials/processes:

- supported material / thickness
- max sheet/work size
- process type
- MOQ
- lead time
- tooling/setup cost fields
- currency
- location / shipping class metadata
- validity period

### 314 — RFQ package

Generate an RFQ snapshot from a ManufacturingRelease without sending it externally.

### 315 — Quote import

Support MANUAL / IMPORTED CSV/JSON supplier quote snapshots. Preserve source, importedAt, effectiveAt, validUntil, currency, raw source hash.

### 316 — Quote normalization

Normalize material, processing, setup/tooling, packaging, freight, MOQ and lead-time into a comparable schema without destroying original raw snapshot.

### 317 — FX truth boundary

FX remains MANUAL/IMPORTED unless a real provider is actually connected. Never label static fixtures as LIVE_PROVIDER.

### 318 — Quote comparison

Rank by deterministic objectives such as landed cost / lead time / MOQ / risk flags. Keep explainable score components.

### 319 — Quote stale rules

A quote comparison becomes stale if releaseHash, material requirements, quantity or FX snapshot changes.

### 320 — Supplier acceptance

Create acceptance fixture with >=3 supplier quote snapshots and verify normalized comparison + stale behavior. Label this REAL for import/normalization logic, MANUAL/IMPORTED for the source data.

---

# Phase 321–328 — Manual Work Order / Shop Traveler

This is a manufacturing **execution boundary**, not a new MES.

### 321 — WorkOrder model

Bind WorkOrder to one `ManufacturingRelease.releaseHash` and quantity/batch id.

Suggested states:

`DRAFT -> RELEASED_FOR_MANUAL_EXECUTION -> MATERIAL_RESERVED -> IN_PROGRESS -> QC_HOLD -> PACKING -> COMPLETED / REJECTED / CANCELLED`

### 322 — Idempotency

Create/retry/cancel must not double-reserve material, double-consume remnant, or duplicate batch records.

### 323 — Material reservation

Reuse MaterialLot / RemnantStore. Reserve by tenant + lot/version/lease. No new inventory master.

### 324 — Shop traveler

Generate station/operation steps appropriate to family, for example:

- panel cutting
- edge banding
- drilling/routing
- hardware prep
- assembly
- surface inspection
- packaging

For packaging/acrylic use family-appropriate steps. These are operator instructions, not machine commands.

### 325 — Operation evidence

Allow operation start/complete records, operator id, timestamp, notes, and optional DAM attachment ids. Do not fabricate sensor evidence.

### 326 — Scrap/remnant transaction

Actual/manual recorded cut outcome can create reusable remnant vs true scrap transactions using existing remnant logic. Keep expected vs recorded quantities separate.

### 327 — Batch lineage

WorkOrder must preserve productVersion/releaseHash/material lots/remnants/operator/QC/package lineage.

### 328 — WorkOrder acceptance

Add deterministic retries/cancel/reservation tests and one full manual-execution simulation. Do not call it live MES.

---

# Phase 329–336 — Quality Control & Traceability V1

### 329 — Tolerance schema

Define product/family-specific measurable checks with nominal, tolerance and unit. Engineering rules remain authority.

### 330 — Incoming material QC

Record material lot checks such as thickness/size/finish/visible defect state. Fixture measurements are TEST DATA unless actual user/device data is imported.

### 331 — In-process QC

Record operation-linked measurements and pass/fail/rework decisions.

### 332 — Final QC

Required final checks before PACKING/COMPLETED. Missing mandatory checks must block completion.

### 333 — Defect / rework taxonomy

Add stable defect codes, severity, disposition (`REWORK`, `SCRAP`, `USE_AS_IS_WITH_APPROVAL`, `REJECT`) and audit trail.

### 334 — DAM evidence

QC photo/file evidence must reference existing DAM assets; no second media store.

### 335 — Traceability report

One call/report must trace:

`productVersion -> releaseHash -> BOM -> material lots/remnants -> work order -> operations -> QC -> package/carton`

### 336 — QC acceptance

Test out-of-tolerance block, required-QC block, rework loop, tenant isolation, and hash lineage.

---

# Phase 337–344 — Packaging / Logistics Execution Boundary

### 337 — Carton instance IDs

Turn packaging plan into per-batch carton instances with contents, expected dimensions/weight, and optional measured dimensions/weight fields.

### 338 — Expected vs measured

Never overwrite estimates with actuals. Keep `EXPECTED/CONFIG_ESTIMATE` separate from `MEASURED/IMPORTED` values.

### 339 — Packing list

Generate carton-level packing list and batch total.

### 340 — Palletization V1

Provide deterministic pallet grouping / footprint / height / weight planning where relevant. Label as planning logic, not carrier certification.

### 341 — Shipping request snapshot

Generate provider-neutral shipping request data but do not submit to a carrier.

### 342 — Carrier quote import

Support MANUAL/IMPORTED carrier-rate snapshots with service, charge, dimensional-weight rules, validity and source hash.

### 343 — Label payload boundary

Generate barcode/QR/text payload and label data structure. Actual barcode verification/printing stays PARTIAL unless a real printer/scanner path is later proven.

### 344 — Logistics acceptance

Test carton contents conservation, dimensional weight, oversize flags, pallet constraints, quote source labels and stale behavior.

---

# Phase 345–352 — Pilot Unit Economics / Variance Loop

### 345 — Cost freeze at release

Freeze the cost basis used when a ManufacturingRelease is approved. Do not silently recompute history.

### 346 — Actual-cost import

Allow MANUAL/IMPORTED batch actuals for:

- material
- processing/labor
- hardware
- packaging
- freight
- scrap/rework

### 347 — Estimated vs actual variance

Report absolute/percent variance by category and total.

### 348 — Waste economics

Separate:

- true scrap cost
- reusable remnant inventory value
- recovered remnant usage credit

No double-credit.

### 349 — Margin guard

Compute contribution margin from scoped price input + frozen release estimate/actual. Do not add payment processing.

### 350 — Break-even quantity

Support setup/tooling/MOQ quantity curves from imported quote snapshots.

### 351 — Product R&D feedback

Feed recorded batch outcomes back into existing Product R&D as **observations**, while demand remains MOCK/MARKET_UNVERIFIED unless real demand data is imported.

### 352 — Unit economics acceptance

Fixture test should show estimate vs actual variance, remnant recovery effect, and margin changes without changing historical snapshots.

---

# Phase 353–360 — Manual Pilot Operations E2E / Acceptance

### 353 — KD E2E

`approved product -> ManufacturingRelease -> material reservation -> WorkOrder -> operations -> QC -> carton -> cost variance -> COMPLETED`

### 354 — Retail fixture E2E

Same pipeline with fixture/planogram-specific release artifacts.

### 355 — Packaging structure E2E

Same pipeline with dieline/fold/board/preflight truth boundaries.

### 356 — Acrylic E2E

Same pipeline with acrylic cut plan; LIVE_LASER stays BLOCKED.

### 357 — REAL Blender evidence refresh

For the release/pilot acceptance, produce real Blender preview EvidenceBundles on the available real worker where rendering is required. `usedMock=false`, artifact hash/size PASS, clean committed CODE_EVIDENCE_SHA. Do not require a 5090; report detected hardware honestly.

### 358 — Batch stress/regression

Run at least:

- 20 product releases across the existing product families
- >=100 WorkOrder operation records
- retries/idempotency checks
- cross-tenant isolation
- no material double-consume
- no stale release allowed to complete

This may be fixture/simulation and must be labeled accordingly.

### 359 — Readiness matrix

Add scoped flags such as:

- `manufacturingReleasePackageReady`
- `manualPilotOpsReady`
- `qcTraceabilityReady`
- `importedSupplierQuoteReady`
- `importedCarrierQuoteReady`
- `liveFactoryExecutionReady=false`
- `liveProviderReady=false`
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`

### 360 — Acceptance documents

At minimum add/update:

- `docs/MANUFACTURING_RELEASE_REAL_ACCEPTANCE.md` + JSON
- `docs/PILOT_OPERATIONS_ACCEPTANCE.md` + JSON
- `docs/QC_TRACEABILITY_ACCEPTANCE.md` + JSON
- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md` evidence pointer

Keep domain acceptance concise and machine-verifiable; do not copy the same generic table into every file.

---

# Test / CI / evidence requirements

Before handoff:

1. `pytest -q` PASS locally; label as MOCK/unit/integration suite unless a test truly runs real Blender.
2. GitHub Actions ubuntu-latest + windows-latest GREEN on the code commit.
3. Any new REAL Blender acceptance must be run from a clean committed CODE_EVIDENCE_SHA.
4. EvidenceBundle must preserve commit SHA, worker, GPU, Blender version, `usedMock`, artifact path/id, hash, size, engineering/BOM/release hashes as applicable.
5. REAL runner must fail closed on missing/invalid required evidence.
6. Canonical acceptance generation/evidence commit consistency must remain valid.
7. Separate code/evidence commit pattern is preferred when REAL evidence is generated after code commit.
8. No tests may enable LIVE_CNC/LIVE_LASER merely to achieve coverage.

---

# Required final handoff in Issue #1

After completion, update the repo and leave one concise Issue #1 comment containing:

- Phase 301–360 code commit SHA
- evidence/docs SHA if separate
- local pytest count + explicit MOCK-suite note
- code/head GitHub Actions run IDs
- REAL / MOCK / PARTIAL / BLOCKED summary
- ManufacturingRelease acceptance summary
- WorkOrder/QC/traceability acceptance summary
- number of REAL Blender EvidenceBundles and detected hardware
- remaining blockers
- `fullAutonomousFactoryReady=false`

Do not ask the user to copy/paste anything. ChatGPT will read the repo directly.

---

# Exit criteria

Phase 301–360 is acceptable only if:

1. Existing Phase 1–300 behavior is preserved; no architecture rewrite.
2. Canonical six-file generation/commit reader rejects mixed truth sets.
3. ManufacturingRelease is immutable/hash-bound/stale-aware and produces verified manual manufacturing packets for KD/retail/packaging/acrylic.
4. Supplier/carrier quote source truth is preserved as MANUAL/IMPORTED unless genuinely live.
5. WorkOrder material reservation/consumption is idempotent and tenant-safe.
6. Required QC blocks completion; full traceability is queryable.
7. Estimated vs measured/actual values are not conflated.
8. Pilot unit-economics preserves frozen history and separates true scrap vs reusable remnant value.
9. Four family pilot E2E paths pass within their stated scope.
10. REAL Blender evidence is clean-commit bound and verified where required.
11. local tests and ubuntu+windows CI are GREEN.
12. LIVE_CNC/LIVE_LASER remain BLOCKED and `fullAutonomousFactoryReady=false`.
