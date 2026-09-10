# Grok 修正指令：Phase 781–840 Re-Gate Round 1 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `bbb5ba20345a366f9f45cb186448f13a638b1538`  
> Phase 781–840 CODE_EVIDENCE_SHA under review: `48869d49a12c594d4ab40097afd0bd51adaf72e0`  
> Current canonical generation: `e9e36a84-9a9a-48e3-a558-e59dd9c88067`  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**  
> This is a correction-only round. Preserve the existing architecture; fix the specific authority/parity gaps below.

## 已接受的證據 — 不要退步

以下內容本輪接受，修正時不得破壞：

- `pytest -q` reported **578 passed**.
- Exact CODE Actions `34495629561` on `48869d49a12c594d4ab40097afd0bd51adaf72e0`: Ubuntu **SUCCESS**, Windows **SUCCESS**.
- Exact docs/head Actions `34496259353` on `bbb5ba20345a366f9f45cb186448f13a638b1538`: Ubuntu **SUCCESS**, Windows **SUCCESS**.
- Canonical generation `e9e36a84-9a9a-48e3-a558-e59dd9c88067` is runner-bound to CODE `48869d4…` with `workingTreeClean=true`.
- DAM artwork bytes/hash checks, basic PrintableSurface derivation, basic mm↔UV round-trip, keep-out BLOCK, stale engineering BLOCK, cross-tenant/tamper basics, 4-door deterministic crop fixture, PNG output hash generation all represent useful **REAL_LOGIC** work.
- Mock Blender is correctly kept `realArtworkPreviewReady=false`; `physicalPrintValidated=false`.

Truth boundary remains mandatory:

- GitHub Actions uses `FOX3D_MOCK_BLENDER=1`; CI is **MOCK/unit/integration + FIXTURE/REAL_LOGIC**, not Production Ready.
- Prior REAL Blender evidence remains only the previously accepted scoped Blender/T1000 evidence. Do not reuse it to claim this new artwork path is REAL-render validated.
- `physicalPrintValidated=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveMachineControl=false`.
- LIVE_CNC / LIVE_LASER / PLC remain **BLOCKED**. Demand / Vision / AI Video remain **MOCK**. Print preflight remains **PARTIAL**.
- Do not modify previously accepted Phase 721–780 logic unless a new regression test proves it is necessary.

---

# Blocker 1 — Remove the second millimetre truth in Blender door geometry

Current artwork acceptance cannot pass while Blender geometry and Engineering Definition disagree.

Current issue to fix:

- Engineering `CabinetEngine._components()` derives door width from the canonical engineering spec.
- `scripts/blender_job.py` independently recalculates door width and currently creates the door mesh with an additional hidden `-0.002` metre width adjustment.
- That hidden Blender-only clearance/gap is not the same source of truth used by PrintableSurface / master artwork crop.

Required correction:

1. **No hidden Blender-side door-size/gap rule.** Any intended door reveal/gap/clearance must either:
   - exist explicitly in the Engineering Definition and be included in the engineering hash, component dimensions/pose and printable-face derivation; or
   - Blender must consume the exact already-derived component face dimensions/pose without inventing a second adjustment.
2. PrintableSurface `widthMm/heightMm`, origin/pose and the physical Blender front face must resolve from the same engineering authority.
3. `master_canvas(... seam_mm=None)` may label seam source `ENGINEERING` only when a real engineering gap/pose was actually resolved. If no engineering gap exists, use an accurate truth label such as `CONFIG`, `UNKNOWN` or `PARTIAL`; do not label a hardcoded zero as engineering truth.
4. Golden 2400×1800 / 4-door test must compare exact engineering door dimensions/poses → PrintableSurface dimensions/origins → Blender mesh dimensions/poses. Do not hardcode 600 mm when the engineering truth says otherwise.
5. Add regression proving a geometry resize/reveal change invalidates the old surface/master/placement lineage.

Do not solve this by creating another Cabinet model or another geometry service.

---

# Blocker 2 — Blender must actually consume canonical UV/crop/rotation/orientation

Current `apply_canonical_artwork()` attaches an image material and copies hashes to object custom properties, but that is not proof that canonical placement was applied.

Required correction:

1. `apply_canonical_artwork()` must actually consume the canonical transform (`uvRect` or an equivalent deterministic canonical mapping) and apply it to the target face/material/UV mapping.
2. The Blender path must not merely copy `engineeringHash/surfaceHash/artworkHash/placementHash` while ignoring placement coordinates.
3. Requested artwork placement must **fail closed** if the target engineering component/object, image bytes/path, canonical UV/crop data, or lineage is missing or inconsistent. Do not silently `continue` and then let the job look successful.
4. `objectName` or component identity must resolve to the exact engineering component identity; wrong object/component must BLOCK.
5. `rotationDeg`, face orientation and mirror policy must be canonical and must affect mapping deterministically. If arbitrary rotation or mirror truly cannot be supported safely in this correction round, explicitly reject unsupported non-zero/non-default values and label that capability PARTIAL — do not accept and hash a value that has no rendering/output effect.
6. Add deterministic tests that prove changing x/y/crop/rotation changes the actual Blender mapping payload/UV state, not only the hash string.
7. The 4-door master artwork must use each panel’s exact canonical crop. No per-door refit/stretch inside Blender.

---

# Blocker 3 — Repair the REAL artwork preview path before it can ever become REAL

Current non-mock `preview()` path is not acceptable proof of artwork rendering because it can submit generic/empty engineering and does not guarantee the artwork image/object mapping is supplied/applied.

Required correction:

1. Reuse the existing canonical `blender_job_payload()` or equivalent single path. Do not create a second generic preview job schema.
2. A REAL preview job must contain the real engineering definition plus exact target component/object identity, image path/asset identity, UV/crop/placement lineage.
3. `realArtworkPreviewReady=true` is allowed only when the result proves all of the following on the exact CODE SHA:
   - `usedMock=false`
   - actual Blender version
   - actual GPU/device
   - completed render artifact SHA-256 + size + job identity
   - the requested artwork placement was actually applied
   - applied `engineeringHash + surfaceHash + artworkHash + placementHash` exact-match the canonical request.
4. If this machine/run cannot provide such REAL evidence, keep `realArtworkPreviewReady=false/BLOCKED_ENVIRONMENT`. That is acceptable; do not fake it.
5. Historical REAL Blender evidence may remain referenced only as historical renderer capability, not as proof of this artwork placement path.

---

# Blocker 4 — Production artwork generation must re-resolve authoritative lineage

Current `produce_panel()` accepts caller-supplied `master`, `crop`, `placement_hash` and `engineering_hash` too trustingly. A coordinated forged crop/hash must not be able to generate a package labeled ready.

Required correction:

1. Production generation must start from an authoritative persisted/in-memory placement identity (`placementId` or equivalent existing authority), then re-resolve the stored Surface, Artwork, Placement and Master/split relation.
2. Recompute the deterministic master/split crop from authoritative engineering surfaces. Do not trust an arbitrary caller crop as truth.
3. Exact-match at minimum:
   - tenantId
   - productId
   - candidateId where applicable
   - version/revision where applicable
   - engineeringHash
   - surfaceId + surfaceHash
   - artworkId + artworkHash + actual byte SHA/size
   - placementId + placementHash
   - masterHash
   - cropMm / cropPx derivation
   - output physical dimensions.
4. Reject forged/blank/stale `surfaceHash`, `placementHash`, `masterHash`, crop, wrong product/candidate/version, or mismatched output dimensions.
5. Production manifest must contain enough authority snapshot/hash data to independently verify the output; `productionArtworkFileReady=true` must be the result of verification, not a caller-controlled flag.
6. Add coordinated-tamper tests: mutate caller crop + copied hash fields together and prove generation/verification BLOCKS.

Keep using the existing DAM and existing publish/evidence architecture. Do not create a second asset store.

---

# Blocker 5 — Complete identity, rotation/orientation and DPI semantics

Required correction:

1. Surface → Placement → Master → Production must carry and verify product/candidate/version/revision identity consistently. Current checks must not stop at tenant/product/engineering only when more identity is present.
2. `rotationDeg` must not be a hash-only field. Implement it in mm↔UV/output mapping or reject unsupported values fail-closed.
3. Mirror/front/back orientation must have one deterministic canonical representation and be consumed by Blender and production output.
4. Effective DPI must use the **minimum of horizontal and vertical effective DPI** based on the actual source crop pixels and actual physical output width/height. Width-only DPI must not overstate print readiness.
5. Pixel width/height and supported MIME metadata should be derived/validated against actual bytes where feasible. Metadata contradictory to bytes must BLOCK.
6. Safe/bleed/keep-out source labels remain explicit CONFIG/ENGINEERING/IMPORTED/PARTIAL as appropriate; unknown hardware geometry must not silently become REAL engineering keep-out.

---

# Blocker 6 — Canonical runner must enforce the full acceptance contract

The current runner/validator is too weak. Phase 781–840 cannot be accepted merely because a small subset of negatives pass while the top-level readiness fields are hardcoded true.

Required correction:

1. `validate_artwork_acceptance_result()` must verify the complete acceptance truth, not only global/live flags and scenario presence.
2. `run_artwork_scenario()` must not set `ok=true` based only on keep-out + stale checks.
3. The canonical runner must derive `surfaceDecorationLogicReady` and `productionArtworkFileReady` from verified scenario results; do not hardcode them true after a shallow check.
4. Acceptance must fail closed unless all applicable results are exact:
   - keep-out collision → `BLOCKED_PLACEMENT`
   - stale engineering/surface/placement → `STALE` or the project’s exact stale code
   - cross-tenant → BLOCK
   - cross-product → BLOCK
   - cross-candidate/version/revision reuse → BLOCK
   - tampered artwork/output bytes → BLOCK
   - STRETCH → BLOCK
   - NaN / Inf / zero dimension / invalid crop / negative bleed or seam → BLOCK
   - duplicate surface/placement canonical identity → BLOCK
   - forged master/crop/hash/placement lineage → BLOCK
   - 2-door / 3-door / 4-door splits → exact deterministic geometry/crop continuity
   - preview ↔ production lineage → exact `engineeringHash + surfaceHash + artworkHash + placementHash`
   - Mock Blender can never make REAL preview true
   - `physicalPrintValidated=false` without physical evidence.
5. Runner tests must inject corrupted scenario results and prove:
   - non-zero return code
   - canonical acceptance files are not published/replaced as a successful generation.
6. Add a negative test where multiple fields are coordinately forged, not only a single-field mutation.

---

# Required regression tests for this correction round

At minimum add focused tests for all of these, using existing modules rather than a rewrite:

- exact engineering door face vs PrintableSurface vs Blender door mesh dimensions/pose, including explicit reveal/gap semantics;
- actual 2-, 3-, and 4-panel split tests (not a test name that only executes 3-panel);
- non-square artwork rotated 90° changes canonical transform and output/mapping as expected;
- mirror/orientation round trip or explicit unsupported-value BLOCK;
- Blender `uvRect`/canonical crop is consumed, and missing object/image/UV does not silently pass;
- production forged crop/master/placement hash BLOCK;
- cross-candidate/version/revision BLOCK;
- horizontal-vs-vertical DPI uses the limiting axis;
- runner corrupted-result injection fails and does not publish success;
- existing Phase 1–780 regression suite remains green.

---

# Docs / truth cleanup after code is fixed

After the correction implementation and canonical runner succeed:

1. Update `docs/GROK_PROGRESS_REPORT.md`; remove the stale contradictory text that still says Artwork Placement is “queued / not started”.
2. Update `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, and `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md/.json` from the new runner evidence.
3. `docs/CABINET_REAL_ACCEPTANCE.md` should only gain a small scoped artwork row if the corrected cabinet artwork truth is actually evidenced. Do not rewrite the historical cabinet acceptance.
4. If no new REAL Blender artwork render exists, keep `realArtworkPreviewReady=false` and label current preview MOCK/BLOCKED_ENVIRONMENT.
5. Never convert generated production PNG into a claim that physical printing/proof is complete.

---

# Re-Gate evidence required

Before asking for the next ChatGPT review:

1. Finish correction source + tests and commit/push a new clear **CODE_EVIDENCE_SHA**.
2. `pytest -q` full suite must pass.
3. Exact CODE_EVIDENCE_SHA GitHub Actions must show Ubuntu + Windows SUCCESS.
4. On that exact CODE SHA with a clean working tree, run the corrected Artwork canonical runner.
5. Produce a **new** `acceptanceGenerationId`, with `evidenceCodeCommit=<exact CODE SHA>` and `workingTreeClean=true`.
6. Canonical evidence must include the complete negative matrix, exact 2/3/4-panel lineage, production-authority verification, preview/production hash parity, and truth labels.
7. Commit/push evidence docs; exact docs/head Actions must also be Ubuntu + Windows SUCCESS.
8. Leave Issue #1 completion comment with CODE SHA, pytest count, CODE Actions run, canonical generation, docs SHA/run, and REAL/MOCK/PARTIAL/BLOCKED summary.
9. **STOP. Do not start Phase 841+ until ChatGPT Re-Gate explicitly says GO.**

## Definition of Done for this correction

Phase 781–840 is accepted only when we can prove, without relying on screenshots or copied hashes, that:

> The same Engineering Definition determines the real cabinet face dimensions/pose; the same canonical ArtworkPlacement determines the real UV/crop/rotation/orientation; Blender actually applies that mapping; the production panel file is regenerated from authoritative placement/master lineage; coordinated tampering fails closed; and Mock/physical/live boundaries remain truthful.

Do not rewrite Scheduler, Queue, DAM, Recipe, TwinStore, CabinetSpec, WorkOrder, MaterialLot, Journal, ManufacturingRelease, PilotBatch or Backup/Restore to accomplish this correction.
