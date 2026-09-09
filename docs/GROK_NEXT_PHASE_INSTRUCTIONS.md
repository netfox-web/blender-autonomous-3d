# Grok 開發指令：Phase 541–600 Small-Space KD SKU Portfolio Factory V1

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `90f7d592243922f3a8dd6c9f70a641efb06d66ca`  
> Accepted CODE_EVIDENCE_SHA: `11c79d12d06c4c6f355fd0d2dc8058f0fef2f825`  
> ChatGPT review result: **ACCEPT WITH SCOPE**  
> Phase 481–540 exit gate is accepted. Start **Phase 541–600** only. Do not rewrite existing architecture.

## Accepted baseline

The `142d062` correction is accepted within its declared scope:

- malformed TENANT_SCOPED shared collections now fail closed instead of being silently copied/coerced;
- `idem`, `releases.packets`, MIXED_SPEC and TENANT_DERIVED malformed container cases are covered by negative regressions;
- `tenant_state_digest()` binds exact tenant-A identity/lineage/state rather than counts only;
- same-count record replacement, releaseHash / WorkOrder / pallet parent / idempotency target mutation, DAM byte mutation and journal event-ID mutation fail semantic preservation;
- normal tenant-A restore reports `tenantStateDigest.equal=true`, `identityMismatch=[]`, `tenantLeakageAbsent=true`;
- acceptance generation: `2d0cc206-ed80-4c32-a82f-491ae8842220`;
- restored-root journal health is healthy and backup snapshot path-set remains hash-bound;
- GitHub Actions CODE run `34342453890` on `11c79d1`: Ubuntu + Windows **GREEN**;
- GitHub Actions docs/head run `34342811475` on `90f7d59`: Ubuntu + Windows **GREEN**;
- test suite: **244 passed** under `FOX3D_MOCK_BLENDER=1`; this is MOCK/unit/integration + REAL_LOGIC regression evidence, **not Production Ready**;
- ManufacturingRelease / Blender render path did not change, so prior accepted REAL Blender evidence `018cc70` (4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`) remains a valid referenced baseline for that unchanged path.

Truth boundaries remain mandatory:

- Vision / AI Video / Demand = **MOCK** unless an actual provider is independently proven;
- OS sandbox / AR / print preflight / barcode hardware / McKee-BCT = **PARTIAL / ENGINEERING_ESTIMATE**;
- supplier / carrier / FX / receipts = **IMPORTED / MANUAL** unless independently proven live;
- LIVE_CNC / LIVE_LASER / PLC / autonomous machine actuation = **BLOCKED**;
- `liveMachineControl=false`;
- `liveFactoryExecutionReady=false`;
- `liveProviderReady=false`;
- `globalProductionReady=false`;
- `fullAutonomousFactoryReady=false`;
- unscoped `productionReady=true` is forbidden.

---

# Phase objective

Use the existing Physical Product OS / KD / ManufacturingRelease / WorkOrder / nesting / remnant / costing / Blender / Manual Factory Pilot capabilities to build a **Small-Space KD SKU Portfolio Factory V1**.

The goal is not to invent another product engine. The goal is to let the existing engine evaluate a batch of student / rental / small-space KD product candidates and produce a traceable shortlist for human prototype approval based on manufacturability, material yield, remnant reuse, carton/logistics constraints, assembly effort and clearly-labeled commercial assumptions.

Do **not** add live marketplace demand claims, automatic purchasing, automatic supplier ordering, automatic CNC execution, or autonomous factory control.

Do not rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Registry / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup architecture. Extend/reuse them.

---

# Phase 541–546 — Portfolio Intent & Opportunity Spec

Create a versioned `PortfolioIntent` / equivalent domain object for batch product exploration.

Minimum fields:

- `tenantId`
- `portfolioId`
- target segment (`STUDENT`, `RENTAL_SMALL_SPACE`, `ENTRY_STORAGE`, etc.)
- allowed existing product families/types
- dimension envelope / footprint limits
- target material catalog / thickness constraints
- max carton constraints
- target assembly difficulty / time range
- target landed-cost / margin scenario ranges
- candidate count target
- explicit data-source labels for every commercial signal

Rules:

1. LLM/NL may propose intent, names and non-authoritative preferences only.
2. LLM may **not** directly set manufacturing-authoritative mm, BOM, material quantity, releaseHash or machine parameters without validation through existing engineering rules.
3. Demand source must be one of `MOCK`, `IMPORTED`, `MANUAL`, `UNAVAILABLE`, or a separately proven provider label. Never call MOCK demand REAL.
4. Bad/missing manufacturing constraints fail closed or enter `NEEDS_INPUT`; never silently substitute unsafe values.
5. Tenant boundary is authoritative.

---

# Phase 547–552 — Deterministic Candidate Generator

Generate a portfolio of valid parametric SKU candidates using the **existing product registry and parametric engine**.

Requirements:

- deterministic candidate generation for the same normalized intent + seed/config;
- candidate canonical hash / engineering hash;
- no duplicate canonical geometry/BOM candidate in one portfolio;
- invalid engineering variants are retained as rejected evidence with rule codes, not silently discarded;
- candidate states at minimum: `CANDIDATE`, `REJECTED_DFM`, `NEEDS_INPUT`, `SHORTLISTED`, `WAITING_PRODUCT_APPROVAL`, `APPROVED_FOR_PROTOTYPE`;
- no candidate can become a ManufacturingRelease merely because it ranked highly.

Acceptance fixture target: **at least 24 candidates across at least 6 existing KD / flat-pack product types**, with both valid and intentionally-invalid variants.

---

# Phase 553–558 — Batch DFM Scorecard

For every candidate run existing authoritative paths and produce a machine-readable DFM scorecard:

- engineering-rule result and rejection codes;
- BOM and BOM hash;
- sheet/material requirement;
- single-SKU nesting;
- reusable remnant vs true scrap;
- material utilization / waste conservation;
- hardware count;
- carton plan, weight/volume and oversize gate;
- assembly operation count / configured assembly effort;
- any required QC plan hash;
- lineage back to candidate hash.

No new fake DFM engine. Reuse the existing rules/BOM/nesting/packing logic.

Required invariants:

- `inputSheetArea = placedArea + reusableRemnantArea + trueScrapArea` within tolerance;
- no part appears twice or disappears;
- no rejected/oversize/engineering-invalid candidate may receive an APPROVED status;
- all estimates have an explicit truth/source label.

---

# Phase 559–564 — Cross-SKU Material Synergy & Remnant Planning

Add a portfolio planning mode on top of the existing batch/cross-SKU nesting and remnant system.

It must compare at least:

1. independent single-SKU production;
2. batch same-SKU production;
3. cross-SKU portfolio batch;
4. remnant-first portfolio batch where compatible inventory exists.

Expose:

- sheet count delta;
- true-scrap area delta;
- reusable-remnant created/consumed;
- material compatibility constraints (SKU/thickness/size/grain);
- candidate-to-sheet lineage;
- candidate-to-remnant lineage;
- normalized material-saving metric.

This is **PLANNING only**. Portfolio evaluation must not silently consume live inventory. Any reservation/consumption must go through existing inventory/WorkOrder semantics and human-approved execution paths.

Required regression: cross-SKU planning must never double-allocate one remnant or exceed available stock.

---

# Phase 565–570 — Commercial Scenario Engine

Build a scenario layer using the existing cost engine; do not pretend estimates are live supplier/customer prices.

Per candidate expose:

- material cost;
- hardware cost;
- processing/config estimate;
- packaging estimate;
- shipping/imported/manual quote where available;
- labor/config or manual estimate;
- remnant credit;
- scrap cost;
- landed cost;
- configurable selling-price scenario;
- gross-margin amount / rate;
- source/truth label per component;
- cost snapshot/version hash.

Rules:

- `CONFIG_ESTIMATE`, `IMPORTED`, `MANUAL`, `MOCK`, `LIVE_PROVIDER` must remain distinct;
- missing supplier/carrier data may not be filled with invented REAL values;
- stale price/cost snapshot after engineering hash/release quantity change must be detected;
- ranking may use configured target margin, but may not claim real market willingness-to-pay without real evidence.

---

# Phase 571–576 — Explainable Portfolio Ranking

Create a deterministic ranking/shortlist layer.

Score dimensions should include at least:

- manufacturing validity (hard gate, not a soft score);
- material utilization / true scrap;
- remnant reuse benefit;
- landed-cost scenario;
- carton/logistics burden;
- assembly burden;
- part/hardware complexity;
- configurable margin scenario;
- demand signal only with its actual truth label.

Requirements:

- weights/config are versioned and included in a `rankingPolicyHash`;
- each score has a contribution breakdown;
- tie-breaking is deterministic;
- a MOCK demand score can influence a MOCK/EXPERIMENTAL ranking only and must not upgrade readiness to REAL;
- DFM-invalid candidates cannot rank into the prototype shortlist;
- human override requires actor/reason/audit entry; it cannot rewrite the computed score.

Acceptance target: produce an explainable **Top 10** shortlist from the >=24 candidate fixture portfolio.

---

# Phase 577–582 — Prototype Approval & Release Candidate Pack

For shortlisted candidates create a release-candidate package reusing existing DAM / ManufacturingRelease validation paths.

Package should bind:

- portfolioId / candidateId;
- candidate engineering hash;
- BOM hash;
- nesting/remnant plan hash;
- cost snapshot hash;
- ranking policy hash and score;
- carton/assembly/QC plan summary;
- preview artifact references if available;
- human approval state and audit.

Important:

- Top 10 means **shortlisted**, not automatically approved.
- ManufacturingRelease remains authoritative and immutable according to existing rules.
- `WAITING_PRODUCT_APPROVAL` / `APPROVED_FOR_PROTOTYPE` is not `APPROVED_FOR_LIVE_CNC`.
- superseded candidate/release lineage must fail closed.

---

# Phase 583–588 — Product Media Pack via Existing Blender Pipeline

For representative shortlisted products generate product-media evidence with the existing Blender queue/DAM path:

- white studio preview;
- at least one alternate useful product angle or 360 artifact where existing capability supports it;
- artifact SHA-256 + size;
- candidate/release lineage;
- `usedMock` truth flag;
- worker/GPU/Blender evidence when REAL.

Do not build a second renderer.

For this phase acceptance, run **fresh clean-tree REAL Blender evidence for at least 4 representative shortlisted KD candidates** on the accepted CODE_EVIDENCE_SHA if the real Blender/OptiX host is available. The current T1000 host is acceptable; do not fabricate RTX 5090. If a media subcase cannot run REAL, label it BLOCKED/PARTIAL rather than using mock as production evidence.

AI Video remains MOCK unless a real provider is independently connected and proven.

---

# Phase 589–594 — Manual Prototype Pilot Pack

Use the existing Manual Factory Pilot / traveler / operator / QC / logistics concepts to produce a human-executable prototype pack for selected shortlist items.

At minimum include:

- immutable candidate/release identity;
- traveler and operation sequence;
- BOM/material list;
- nesting/cut planning reference;
- hardware list;
- assembly steps/effort estimate;
- QC checks;
- carton/packing checklist;
- exception/hold path;
- explicit `MANUAL_STATION` / human execution label.

Do not issue live CNC/laser/PLC commands. Do not auto-book carrier or auto-order supplier material.

A prototype pack may be marked `READY_FOR_MANUAL_PROTOTYPE` only when all required upstream hashes/evidence agree and human approval exists.

---

# Phase 595–600 — Fail-Closed Portfolio Acceptance

Add a dedicated clean-tree acceptance runner, e.g. `scripts/run_portfolio_factory_e2e.py`, without weakening existing runners.

Required committed evidence:

- `docs/SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json`
- `docs/SKU_PORTFOLIO_FACTORY_ACCEPTANCE.md`
- `docs/PORTFOLIO_DFM_ACCEPTANCE.json`
- `docs/PORTFOLIO_DFM_ACCEPTANCE.md`
- `docs/PORTFOLIO_COMMERCIAL_ACCEPTANCE.json`
- `docs/PORTFOLIO_COMMERCIAL_ACCEPTANCE.md`

All six new files must share one `acceptanceGenerationId`, exact `evidenceCodeCommit`, `workingTreeClean=true`, and be published atomically or rolled back as one generation.

Minimum fail-closed acceptance gates:

1. >=24 candidates across >=6 existing product types generated deterministically;
2. invalid candidates retained with explicit rejection evidence;
3. no invalid candidate in Top 10;
4. Top 10 deterministic under the same normalized inputs/policy;
5. every Top-10 candidate has exact engineering/BOM/cost/ranking lineage;
6. DFM material conservation passes;
7. cross-SKU/remnant plan has no double allocation / oversell;
8. cost components expose source/truth labels and stale snapshots fail;
9. MOCK/UNAVAILABLE demand cannot become REAL;
10. tenant isolation proven for portfolio/candidate/ranking records;
11. any new durable portfolio state is included in existing tenant backup/semantic restore contract; no new tenant-owned state may be omitted from TENANT_SCOPED backup;
12. manual prototype readiness requires human approval and cannot imply live machine execution;
13. four representative media cases have fresh REAL Blender evidence (`usedMock=false`) if the host is available, otherwise the scope is explicitly BLOCKED/PARTIAL;
14. runner rejects dirty tree, expected-commit mismatch, mixed generation, missing/malformed evidence and leaves previous valid evidence unchanged;
15. `liveMachineControl=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false` remain enforced.

## Required negative regressions

At minimum test:

- duplicate candidate canonical hash;
- engineering-invalid candidate forced into shortlist;
- same candidate geometry with stale BOM/cost hash;
- remnant double-use in two portfolio candidates;
- material incompatibility (SKU/thickness/size/grain);
- stale/missing cost source;
- MOCK demand mislabeled REAL;
- cross-tenant portfolio/candidate lookup;
- human approval missing but prototype readiness requested;
- superseded release/candidate used for pack;
- dirty-tree / wrong CODE_EVIDENCE_SHA acceptance run;
- mixed/missing new acceptance generation;
- persisted new portfolio state omitted from tenant backup/restore semantic digest.

---

# Evidence / CI sequence

1. Implement Phase 541–600 without starting Phase 601+.
2. Run `pytest -q`; preserve exact truth labels.
3. Commit code/tests as a new **CODE_EVIDENCE_SHA**.
4. Push and require GitHub Actions Ubuntu + Windows GREEN on that exact code SHA.
5. From a clean committed tree run the new portfolio acceptance with `--expected-commit <CODE_EVIDENCE_SHA>`.
6. Run the four representative REAL Blender portfolio media cases on the same code SHA when available and verify hashes/sizes/lineage; never substitute mock evidence.
7. Commit evidence/docs separately.
8. Require docs/head Ubuntu + Windows GREEN.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`. Update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet-specific evidence truly changes.
10. Leave Issue #1 a concise handoff with CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, candidate/Top-10 counts, material-conservation/remnant results, commercial truth labels, REAL Blender count, backup/tenant result and readiness matrix.

## Exit definition

Phase 541–600 is accepted only as a **Small-Space KD SKU Portfolio / Manual Prototype Pilot** scope.

It is not live demand intelligence, not a live procurement system, not an MES replacement, and not an autonomous factory. MOCK/PARTIAL/BLOCKED paths must remain honestly labeled.