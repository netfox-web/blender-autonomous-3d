# Grok 修正指令：Phase 601–660 Final Integrity — Published Canonical Lineage + Intent Identity

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `a78386deb98b6a78f16185a443aa61daa019f73f`  
> Reviewed CODE_EVIDENCE_SHA: `8d2ebd4aa098b8193b69f61a028749d6ee49498d`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 661+. Fix only the two remaining Phase 601–660 integrity gaps below.**

## Accepted evidence — preserve it

The `32e9bae` corrections are materially improved. Correct the remaining fail-open edges in place; do not rewrite architecture.

- Prototype inventory now persists a `PREPARED` intent before allocation, then recovers existing MaterialLot `RESERVED` / `CONSUMED` rows for the exact prototype work-order instead of blindly allocating replacement stock.
- Durable crash regressions now cover `after-reserve` for single-lot and multi-lot paths, including subprocess `os._exit`, and the prior `after-first-consume` recovery tests remain.
- Packaging acceptance now requires carton L/W/H, packed weight and assembly variance to be `complete=true` + `ok=true`, and validates the pinned `packagingPolicyHash`.
- In-memory acceptance now indexes selected/unit/matrix/board by `candidateId`, requires build completion, and catches many lineage contradictions.
- `pytest -q`: **382 passed**, explicitly MOCK/unit/integration + FIXTURE/REAL_LOGIC — **not Production Ready**.
- GitHub Actions CODE run `34379275367` is GREEN on Ubuntu + Windows for exact CODE `8d2ebd4...`.
- GitHub Actions docs/head run `34379702117` is GREEN on Ubuntu + Windows for exact docs head `a78386d...`.
- Canonical generation `e0b46a65-0d0f-4c33-9bc5-ac72375b8603` is clean-tree bound to CODE `8d2ebd4...`; fixture units remain `WAITING_VALIDATION`, `physicalPrototypeValidated=false`, cost PARTIAL.
- Prior REAL Blender evidence remains verified 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX on CODE `7a87ea5...`, with per-case job/hash/size/GPU lineage. Render/media/engineering path did not change this round.
- Tenant backup/restore still reports exact semantic digest equality for the fixture scenario.
- Keep Demand / Vision / AI Video = **MOCK**; OS sandbox / AR / preflight / barcode / McKee-BCT = **PARTIAL**; supplier/carrier/FX/receipts as IMPORTED/MANUAL/CONFIG where already modeled; LIVE_CNC / LIVE_LASER / PLC / live provider / live factory = **BLOCKED**.
- Keep `physicalPrototypeValidated=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `liveMachineControl=false`.

Do **not** replace Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / KD registry / MaterialLot / Nesting / Remnant / ManufacturingRelease / WorkOrder / QC / Logistics / Backup architecture. Reuse the existing transaction, journal/outbox, inventory, backup and acceptance mechanisms.

---

## BLOCKER 1 — Published canonical truth set still does not prove the claimed exact selected → unit → matrix → board lineage

The in-memory validator is better, but the committed canonical evidence is still fail-open in two ways.

### What is wrong now

1. `_lineage_value()` ignores missing / `None` / empty values. It only detects disagreement among values that happen to be present. A required object can therefore omit a lineage field and still pass.
2. `REQUIRED_BOARD_FIELDS` currently proves key presence, not a non-null/non-empty authoritative value.
3. `run_prototype_validation_e2e.py` drops lineage while serializing the canonical files:
   - published `selected[]` omits `rankingPolicyHash`;
   - published `units[]` omits `selectionId`, `canonicalHash`, `bomHash`, `nestingHash`, `rankingPolicyHash`.
4. The currently committed `PROTOTYPE_VALIDATION_ACCEPTANCE.json` therefore has `ok=true` while its `units[]` cannot independently prove the exact lineage that the audit/report claims.
5. Pre-publish validation of the richer in-memory object is not enough. The canonical evidence that is actually committed must itself survive semantic re-validation after serialization/publication.
6. The decision board may remain a broader Top-10 board, but the canonical truth set needs an exact projection for the four selected targets so that unrelated/extra board rows cannot be mistaken for the four-lineage proof.

### Required correction

1. Define a strict non-null lineage contract for the four selected prototype targets. At minimum, wherever applicable, require and publish:
   - `candidateId`;
   - `selectionId`;
   - `prototypeUnitId`;
   - `engineeringHash`;
   - `canonicalHash`;
   - `bomHash`;
   - `nestingHash`;
   - `rankingPolicyHash`.
2. Do not silently skip missing values. For every field required on a given object, missing / null / empty is a failure, not “no contradiction.”
3. Preserve the authoritative lineage on `PrototypeUnit` or deterministically materialize it from its pinned selection/candidate at canonical generation time. Do not invent a second source of truth.
4. Publish the complete lineage fields in canonical `selected[]`, `units[]`, `matrix[]`, and the exact four selected board projections. If the full Top-10 board remains useful, keep it, but add an exact selected-board projection or otherwise make the four-target proof unambiguous.
5. Require exactly one unit and one matrix row for every selected candidate/selection, and exactly one corresponding selected-board row. Reject duplicate or missing selected targets.
6. Require exact equality of every applicable lineage field across the selected target, unit, matrix and selected-board projection.
7. `buildCompleted=true` must remain authoritative from the unit and match the matrix; do not infer it from state.
8. Board tolerance/QC/packaging/physical/evidence state must remain consistent with that candidate's matrix/unit evidence.
9. After atomic publication, re-read the **serialized canonical truth set** and run semantic validation on what was actually published. A field dropped during serialization, nullified, tampered or contradicted must make the runner non-zero and must not replace the prior good truth set.
10. Do not weaken atomic publication, shared generation ID, clean-tree binding or prior REAL Blender verification.

### Required negative regressions

Add runner/canonical tests proving non-zero + no overwrite for at least:

- unit `selectionId` missing/null;
- unit `canonicalHash` missing/null;
- unit `bomHash` / `nestingHash` / `rankingPolicyHash` missing/null;
- selected `rankingPolicyHash` missing/null when the ranking contract requires it;
- selected/unit/matrix/board lineage field present as empty string;
- board required hash key exists but value is null/empty;
- selected target absent from the exact selected-board projection;
- duplicate selected-board target;
- published serializer intentionally drops one required lineage field => post-publication semantic verification fails and rolls back/refuses overwrite;
- existing mismatch tests continue to fail closed.

The current values may be internally consistent, but **do not call exact canonical 1:1 lineage complete until the committed truth set itself contains and verifies the proof**.

---

## BLOCKER 2 — `inventoryIntentId` fallback can bind a PREPARED intent without proving exact operation identity

The new PREPARED-before-reserve design closes the original orphan-reservation crash window for an exact retry. One fail-closed edge remains in `_find_intent()`.

### What is wrong now

`_find_intent(rec, qty)` first searches by the deterministic idempotency key, but if that does not match it falls back to `rec.inventoryIntentId` and returns that intent without re-validating the full operation identity.

That fallback must not allow a stale/corrupt PREPARED intent to be reused for a different operation. For example, after a crash with a PREPARED intent but before allocation, a retry with a different sheet quantity can miss the deterministic key, fall through to `inventoryIntentId`, and continue with an intent whose stored `quantity` / idempotency key no longer describes the retry.

### Required correction

1. Before using any existing intent — including the `inventoryIntentId` pointer — validate an immutable operation identity against the current prototype operation:
   - tenant ID;
   - prototypeUnitId;
   - workOrderId / deterministic operation key;
   - exact idempotency key;
   - quantity;
   - material;
   - thickness;
   - grain;
   - required length/width;
   - any other requirement field that changes which stock may legally satisfy the operation.
2. If the pointer references another tenant/unit/work-order, a different quantity/requirement, a malformed intent, or an intent that cannot be proven to be the same operation, fail closed (`HOLD` / `BLOCKED`) **before any new reservation/allocation side effect**.
3. If multiple persisted intents claim the same immutable operation identity, treat it as ambiguous and fail closed; do not pick one by iteration order.
4. A mismatched retry must leave all MaterialLot quantities/reservations unchanged.
5. Exact retries after `after-reserve` and `after-first-consume` must continue to recover the already-owned authoritative reservation set and consume exactly once.
6. Final `inventoryLineage` remains based on authoritative MaterialLot reservation states; do not replace it with a boolean or a second ledger.
7. Tenant backup/restore semantic digest must continue to preserve inventory intents and their immutable identity.

### Required negative regressions

- persist PREPARED intent, retry same unit with a different sheet quantity => fail before allocation; no stock/reservation change;
- PREPARED intent requirement material/thickness/grain/length/width mismatch => fail closed;
- `inventoryIntentId` points to an intent for another prototype unit/work-order => fail closed;
- cross-tenant intent pointer => fail closed;
- duplicate intents with the same immutable operation identity => ambiguous/HOLD;
- malformed intent missing required immutable identity field => fail closed;
- exact retry for existing after-reserve single-lot/multi-lot crash continues to bind the same reservation IDs and consume exactly once;
- existing after-first-consume hard-crash recovery remains green.

---

## Required delivery before re-review

1. Fix **only** the two integrity gaps above. **Do not start Phase 661+.**
2. Preserve all accepted implementation/tests and prior crash/packaging regressions; add the new fail-closed tests.
3. Run full `pytest -q`; report it honestly as MOCK/unit/integration + FIXTURE/REAL_LOGIC, not Production Ready.
4. Commit implementation/tests as a new **CODE_EVIDENCE_SHA** and require GitHub Actions Ubuntu + Windows GREEN on that exact SHA.
5. Run acceptance on a clean tree bound to that exact CODE SHA; regenerate canonical `PROTOTYPE_VALIDATION_ACCEPTANCE` + `SKU_LAUNCH_READINESS_ACCEPTANCE` from code, never by hand-editing JSON.
6. Re-read and semantically validate the serialized canonical files after publication; a semantic failure must not replace the previous accepted truth set.
7. Re-run tenant backup/restore semantic validation with the corrected inventory-intent identity and all prototype lineage preserved.
8. Prior REAL Blender 4/4 on `7a87ea5...` may be reused only if the existing fail-closed verifier still passes and render/engineering/media path remains unchanged. If that path changes, generate fresh REAL Blender evidence.
9. Commit docs/evidence separately and require Ubuntu + Windows GREEN on docs/head.
10. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`; update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet truth actually changes.
11. Leave Issue #1 a concise completion comment with CODE SHA, docs SHA, pytest count, both CI run IDs, acceptance generation, intent-identity negative tests, exact **published** four-target canonical lineage result, backup semantic result, prior/fresh REAL Blender status, and remaining MOCK/PARTIAL/BLOCKED boundaries.
12. Stop for ChatGPT review. Do not enter Phase 661+ until **ACCEPT WITH SCOPE**.
