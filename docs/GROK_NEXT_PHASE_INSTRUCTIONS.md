# Grok 修正指令：Phase 541–600 Portfolio Integrity Gate

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `936025191d7723dcec96b1d2b6e0ba30de8c863c`  
> Reviewed CODE_EVIDENCE_SHA: `655ea994bdd7e5505324b10ea02f0166abefb08e`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 601+. Do not rewrite existing architecture. Fix Phase 541–600 gaps only.**

## What is accepted in this round

The following work is substantive and may be preserved:

- 28 candidates across 8 KD kinds; invalid candidates retained and Top 10 excludes invalid rows.
- Candidate/DFM/ranking are correctly scoped as `REAL_LOGIC`, not global Production Ready.
- Commercial values remain `CONFIG_ESTIMATE`; Demand remains `MOCK`.
- Tenant portfolio state is included in TENANT_SCOPED backup and current semantic restore digest reports equal.
- Human prototype state remains separate from live machine execution.
- GitHub Actions run `34346220584` on CODE `655ea99` is GREEN on Ubuntu + Windows.
- Docs/head run `34346553169` on `9360251` is GREEN on Ubuntu + Windows.
- Local `pytest -q` is reported as 257 passed, explicitly MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
- LIVE_CNC / LIVE_LASER / live factory / live provider remain BLOCKED; global/full/live readiness flags remain false.

However, the current acceptance is still fail-open in several Phase 541–600 requirements. Fix the items below before any Phase 601+ work.

---

# Blocker 1 — Manufacturing envelope validation must be fully fail-closed

Current `PortfolioFactory.create_intent()` validates `maxWidthMm`, but other manufacturing-critical envelope fields can still be zero, negative, malformed, NaN/Infinity, missing via override, or otherwise invalid without an equivalent fail-closed gate.

Required fix:

1. Validate every manufacturing-authoritative envelope field before persisting the intent:
   - `maxWidthMm`
   - `maxDepthMm`
   - `maxHeightMm`
   - `maxLongestCartonMm`
   - `maxPackedWeightKg`
   - `maxAssemblyMinutes`
   - `thicknessMm`
2. Numeric fields must be finite, numeric, and `> 0`.
3. `thicknessMm` must be a non-empty finite positive list and must pass the existing material/thickness policy; do not silently coerce an invalid list to the default.
4. Invalid/missing explicitly supplied constraints must return `NEEDS_INPUT`/BLOCKED and must not create a valid PortfolioIntent.
5. Keep safe configured defaults only when the caller did not explicitly provide an invalid value. Never let `0`, negative, NaN, Infinity, non-numeric, empty list, or `None` become an accepted manufacturing envelope.

Required regressions:

- parameterized negative tests for every field above: `0`, negative, `None`, non-numeric and non-finite where applicable;
- empty / malformed thickness list;
- assert no valid persisted intent is produced from malformed manufacturing constraints.

---

# Blocker 2 — DFM area conservation currently trusts a possibly-missing derived error

Current `_scorecard()` effectively does:

`err = float(nest.get("areaConservationError") or 0)`

and then `conservation = err < 2`.

That means a missing/None `areaConservationError` can become zero and PASS. This violates the required fail-closed invariant.

Required fix:

1. Do not use missing `areaConservationError` as zero.
2. Independently recompute material conservation from authoritative nesting fields:

   `inputSheetArea ≈ placedArea + reusableRemnantArea + trueScrapArea`

3. Require all source fields used in that equation to exist, be finite, and be non-negative.
4. Bind `inputSheetArea` to actual sheet dimensions × sheet count. Do not accept a contradictory precomputed total.
5. If panel BOM is non-empty, zero/missing sheet count or missing placed/remnant/scrap fields must fail DFM.
6. Store the recomputed error and tolerance in the DFM scorecard so acceptance does not rely only on a boolean.
7. Ranking, prototype readiness, and Phase 541–600 acceptance must all use this fail-closed recomputed result.

Required regressions:

- remove `areaConservationError` while other data is malformed: must not PASS;
- remove/None/tamper `partUsedArea` / `reusableRemnantArea` / `trueScrapArea` / `sheetCount` / `sheetMm`: must fail or reject the candidate;
- create an arithmetic mismatch larger than tolerance: candidate cannot enter Top 10 or prototype readiness;
- valid known nesting still passes with conservation error within tolerance.

---

# Blocker 3 — Remnant-first planning must enforce material compatibility, not thickness only

Current portfolio planning filters available remnants by tenant and thickness, then passes a planning remnant list that does not preserve/enforce the remnant material identity. A same-thickness remnant of the wrong material can therefore be considered by the planning nester.

Required fix:

1. Preserve and validate remnant lineage fields needed by the existing material policy, including at least:
   - `remnantId`
   - tenant
   - material / material SKU
   - thickness
   - dimensions
   - grain/orientation where the existing nesting/remnant model supports it
   - source run / source lineage
2. A remnant may enter a candidate planning pool only if it is compatible with the BOM/material requirement. Same thickness alone is insufficient.
3. For mixed-material cross-SKU portfolios, partition planning by compatible material/thickness/grain group rather than allowing the final loop value to define one global material.
4. Distinguish `candidateRemnantIds` (eligible pool) from `usedRemnantIds` (actually placed/allocated by the planning result), or an equivalent exact lineage model.
5. `noDoubleAllocation` / remnant double-use must be proven against actual planned placements, not merely against the list of available remnant IDs.
6. This remains PLANNING only and must not consume/reserve live inventory.

Required regressions:

- same tenant, same thickness, wrong material remnant: must not be used;
- right material but incompatible thickness: must not be used;
- grain/orientation incompatibility if supported by current model: must not be used;
- mixed-material portfolio: each planned remnant placement must trace to a compatible candidate/material group;
- duplicate actual `usedRemnantId` across two planned allocations must fail closed.

---

# Blocker 4 — REAL Blender media evidence is summarized, not sufficiently committed/bound

Current committed acceptance says only `REAL blender media = real=4/4`. The runner counts rows with `label=REAL` and `usedMock=false`, but the canonical acceptance JSON does not commit the four detailed media evidence records. `media_pack()` also labels REAL from `realBlender + !usedMock + completed + digest`, without requiring a positive artifact size or persisting a per-media code/evidence lineage binding.

Therefore the statement “4/4 beautyHash bound on 655ea99” is not yet adequately proven by the committed canonical truth set.

Required fix:

1. Commit the exact four representative REAL media evidence records into the canonical Phase 541–600 acceptance JSON (or an atomically-published companion file included in `PORTFOLIO_ACCEPTANCE_FILES`).
2. For each media case persist and gate at minimum:
   - `candidateId`
   - candidate `engineeringHash`
   - render job ID / unique execution identity
   - preview artifact reference
   - alternate/exploded artifact reference when generated
   - `usedMock=false`
   - `realBlender=true`
   - Blender version
   - GPU / device / OptiX truth from the actual job/worker evidence when available
   - artifact SHA-256
   - artifact size, strictly `> 0`
   - generated/executed timestamp or equivalent fresh-run identity
   - exact `evidenceCodeCommit` binding for this acceptance generation
3. Do not call a media case REAL if digest is present but size is missing/zero.
4. Do not allow an old cached artifact from another CODE_EVIDENCE_SHA to satisfy “fresh clean-tree REAL media” without explicit verified lineage.
5. If the underlying render job already has commit/evidence lineage, use it. If it does not, add only the minimum runner/evidence binding needed; do not build a second renderer or scheduler.
6. The canonical committed evidence must allow ChatGPT to audit the actual 4 cases without trusting only `real=4/4` prose/count.

Required negative regressions:

- four fake rows marked REAL but missing SHA-256 -> fail;
- SHA present but `artifactSize=0`/missing -> fail;
- `usedMock=true` -> fail REAL media gate;
- `realBlender=false` -> fail;
- wrong/missing evidence code commit -> fail;
- fewer than four valid detailed cases with `--real-media` -> fail;
- a failed run must not overwrite the previous valid canonical generation.

After changing this evidence path, rerun **fresh clean-tree 4/4 REAL Blender** media on the new CODE_EVIDENCE_SHA. Do not reuse the current `655ea99` 4/4 claim as the final evidence for the modified instrumentation.

---

# Blocker 5 — Acceptance runner must gate the scenario itself and exact Top-10 lineage

The Phase 595–600 requirement says every Top-10 candidate must have exact engineering/BOM/cost/ranking lineage. The current canonical acceptance mostly records aggregate counts/hash and does not prove each Top-10 lineage row.

Required fix:

1. `run_portfolio_factory_e2e.py` must require `result.ok is True`; a scenario returning `ok=false` must fail even if all aggregate booleans look good.
2. Persist an auditable Top-10 manifest with, per candidate:
   - candidateId / canonicalHash
   - engineeringHash
   - BOM hash
   - nesting/plan hash or exact planning lineage
   - cost snapshot hash
   - ranking policy hash
   - score/contribution reference
   - current state
   - prototype approval status if applicable
3. Gate that no Top-10 row has missing/empty required hashes.
4. Gate that the candidate state is not `REJECTED_DFM`, `NEEDS_INPUT`, or `SUPERSEDED`.
5. Cost snapshot lineage must be fresh relative to the candidate engineering hash.
6. Store this Top-10 manifest inside the atomic canonical generation so it is directly reviewable.

Required regressions:

- fake scenario `ok=false` with otherwise passing fields -> runner must fail;
- Top-10 row missing BOM/cost/ranking lineage -> fail;
- stale engineering/cost hash mismatch -> fail;
- rejected/superseded candidate manually injected into manifest -> fail;
- prior successful truth set remains intact on failure.

---

# Truth labels — do not promote scope

Keep these labels unless independently proven otherwise:

- Candidate generation / DFM / ranking: `REAL_LOGIC`
- Cross-SKU/remnant portfolio planning: `REAL_LOGIC / PLANNING`; **no live inventory consume**
- Automated acceptance scenario / automatic actor `pm`: `FIXTURE / REAL_LOGIC`; it is not proof a physical human approved a real prototype
- Commercial cost: `CONFIG_ESTIMATE` unless an imported/manual/live source is independently evidenced
- Demand: `MOCK`
- Vision Judge: `MOCK`
- AI Video: `MOCK`
- OS sandbox / AR / preflight / barcode hardware / McKee-BCT: `PARTIAL / ENGINEERING_ESTIMATE`
- LIVE_CNC / LIVE_LASER / PLC / live factory execution / live provider: `BLOCKED`
- `liveMachineControl=false`
- `liveFactoryExecutionReady=false`
- `liveProviderReady=false`
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- Unscoped `productionReady=true` remains forbidden.

---

# Required evidence sequence for this correction

1. Fix **only** the Phase 541–600 integrity gaps above. Do not start Phase 601+.
2. Do not rewrite Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Registry / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup architecture.
3. Add the negative regressions above.
4. Run full `pytest -q` and report the exact count, labeled MOCK/unit/integration + REAL_LOGIC/FIXTURE, not Production Ready.
5. Commit code/tests as a new `CODE_EVIDENCE_SHA`.
6. Push and require Ubuntu + Windows GitHub Actions GREEN on that exact code SHA.
7. From a clean tree run the Phase 541–600 acceptance with `--expected-commit <new CODE_EVIDENCE_SHA>` and `--real-media` on the real T1000/OptiX host.
8. Produce a new atomic acceptance generation containing detailed Top-10 lineage and detailed 4/4 REAL media evidence.
9. Re-run TENANT_SCOPED backup/restore semantic digest with the new portfolio evidence/state if any durable schema changed.
10. Commit docs/evidence separately and require docs/head Ubuntu + Windows GREEN.
11. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`; update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet-specific truth actually changes.
12. Leave Issue #1 a concise completion handoff with new CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, Top-10 lineage result, DFM conservation result, remnant material-compatibility result, 4 detailed REAL media cases, tenant backup result and readiness matrix.

## Exit gate

Phase 541–600 may be accepted only when all five blockers above are fail-closed and auditable from committed evidence.

Until then: **CHANGES REQUIRED — Phase 601+ is not authorized.**
