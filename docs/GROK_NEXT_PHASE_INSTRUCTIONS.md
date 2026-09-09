# Grok 修正指令：Phase 361–420 Final Integrity Corrections

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `ce77f882e61e4de955ab0fdcfb8d460a2b0e92c6`  
> Reviewed CODE_EVIDENCE_SHA: `cdc1b5b32dd96d13730c6a1c46703cc69e120886`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 421+ yet. Fix only the remaining integrity gaps below. Do not rewrite existing Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / WorkOrder architecture.**

## Evidence accepted from `cdc1b5b` / `ce77f88`

These items are accepted within their stated scope and do not need to be re-described as stronger than they are:

- Local `pytest -q`: **166 passed**, but this remains **MOCK/unit/integration + FIXTURE** evidence, not Production Ready.
- GitHub Actions code run `34294248563` on `cdc1b5b`: ubuntu + windows **SUCCESS**.
- GitHub Actions docs/head run `34294345801` on `ce77f88`: ubuntu + windows **SUCCESS**.
- Partial STRICT_STOCK shortage no longer leaves partial reservations in the tested in-process path; 10 retries/restart/concurrent shortage regressions are present.
- Material SKU + thickness matching is now enforced; quarantined lots are excluded.
- Receipt idempotency is tenant-scoped; request header tenant is authoritative on the new Pilot routes; tenant console filters shipments/cartons/receipts/WOs/releases/QC; cross-tenant shipment carton mix is rejected.
- `reliability_gate()` is now part of `required_ok`; explicit broken reliability booleans/negative evidence fail non-zero.
- Clean-tree REAL acceptance has 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX EvidenceBundles, `usedMock=false`, exact `commitSha=cdc1b5b`, non-null matching ManufacturingRelease `releaseHash`, verifier PASS.
- `PILOT_RELIABILITY_ACCEPTANCE.json` correctly labels the 50-WO/652-op stress as **FIXTURE**, not factory throughput.
- Vision / AI Video / Demand remain **MOCK**.
- OS sandbox / AR / print preflight / barcode / McKee-BCT remain **PARTIAL / ENGINEERING_ESTIMATE**.
- Supplier/carrier/FX/receipts remain **IMPORTED / MANUAL** unless a real authenticated provider is connected.
- LIVE_CNC / LIVE_LASER / live machine execution / live provider remain **BLOCKED**.
- `globalProductionReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `fullAutonomousFactoryReady=false` must remain false.

---

# Blocking finding 1 — Acceptance hook path still fabricates a passing reliability result when evidence is missing

In `scripts/run_pilot_e2e.py`, the hook/pipeline branch currently does:

```python
stress = data.get("stress") or passing_reliability_stress()
```

This is fail-open. If the pipeline omits `stress`, returns `None`, or otherwise fails to provide reliability evidence, the runner silently replaces the missing evidence with a perfect synthetic PASS.

The current regression `_pipeline()` in `tests/test_pilot_runner.py` explicitly returns `"stress": None`, and `test_runner_valid_six_file_set_can_proceed` expects exit 0. That proves the missing-evidence path is currently accepted.

This violates the rule that REAL acceptance must fail closed on missing required reliability evidence.

## Required fix

- Remove every implicit `passing_reliability_stress()` fallback from acceptance execution.
- `passing_reliability_stress()` may remain only as an **explicit test fixture helper** when a test deliberately injects it.
- In the hook path, use the supplied `stress` value as-is. Missing / `None` / empty / malformed stress must enter `reliability_gate()` and fail.
- The non-hook production acceptance path must continue to use the actual `plat.pilot.reliability.run(...)` result.
- Failure must return non-zero and must not overwrite canonical accepted evidence.

## Mandatory runner regressions

Add direct `run_pilot_e2e.main()` tests proving all of these return non-zero and leave canonical files unchanged:

1. pipeline omits the `stress` key entirely;
2. `stress=None`;
3. `stress={}`;
4. missing `label`;
5. missing one required boolean;
6. missing required negative evidence;
7. existing explicit false cases (`noOversell`, conservation, shipmentDraft, partial shortage, tenant isolation, too few WOs/ops) remain fail-closed.

Also change the current “valid runner” fixture so it explicitly injects a complete passing FIXTURE stress object rather than relying on a hidden default.

---

# Blocking finding 2 — Release sheet dimensions are computed but ignored during STRICT_STOCK allocation

`WorkOrderService.reserve_materials()` reads the release nesting snapshot and computes:

- `sheetSku`
- `thickness`
- `grain`
- `sheetMm -> length / width`

but the actual STRICT_STOCK call currently passes:

```python
length=None,
width=None,
```

Therefore a lot with the right SKU and thickness but the wrong sheet dimensions can satisfy a release. This is not an acceptable material compatibility check because the frozen ManufacturingRelease already carries the nesting/sheet geometry used for production planning.

## Required fix

Keep the existing `MaterialLotRegistry.lot_compatible()` / `allocate_requirement()` path. Do not create another inventory or nesting engine.

- Pass the release-required sheet `length` and `width` into `allocate_requirement()` when they are present in the frozen nesting snapshot.
- Enforce deterministic dimensional compatibility. Do not allow a smaller/different sheet to satisfy a release just because SKU/thickness match.
- Grain remains manufacturing-significant. If the release specifies a grain direction, missing/unknown lot grain must not silently count as compatible.
- Preserve exact release-to-lot lineage on the WorkOrder reservations.
- If a product family genuinely does not have sheet dimensions, keep dimensions optional for that family rather than inventing fake values.

### Receipt fidelity

The MANUAL/IMPORTED receiving path must be able to preserve real lot geometry instead of forcing every newly received lot to the default 2440×1220 / default grain.

Within the existing `ReceivingService` + `MaterialLotRegistry`:

- accept optional `length`, `width`, and `grain` from the receipt row;
- persist those values on the MaterialLot;
- when optional `expectedLength`, `expectedWidth`, or `expectedGrain` are provided, mismatch must quarantine/fail consistently with the existing expected material/thickness behavior;
- do not turn this into a supplier live feed. Truth label remains MANUAL/IMPORTED.

## Mandatory regressions

- Release requires 2440×1220 PB_18_WHITE 18mm; only 2000×1000 PB_18_WHITE 18mm exists -> SHORTAGE, lot unchanged.
- Correct 2440×1220 material succeeds.
- Correct SKU/thickness/dimensions but wrong grain -> SHORTAGE, lot unchanged.
- Missing lot grain when release requires a grain direction -> unavailable, not silently accepted.
- Multiple compatible receipts can satisfy one WO and conservation remains true.
- Receipt round-trip preserves supplied dimensions/grain.
- Expected-dimension/grain mismatch is quarantined and cannot satisfy the WO.

---

# Blocking finding 3 — Caller-supplied idempotency keys are still globally scoped in adjacent multi-tenant services

Receipt idempotency was fixed correctly, but the same isolation pattern is still fail-open in adjacent services:

- `WorkOrderService.create()` uses the raw caller `idempotency_key` directly when one is supplied.
- `ManufacturingReleaseService.create()` uses the raw caller `idempotency_key` directly when one is supplied.
- `LogisticsService.instantiate_cartons()` uses the raw caller `idempotency_key` directly when one is supplied.

Each service keeps a process-global `_idem` map. Two tenants using the same raw caller key can therefore resolve to the first tenant's object. In `LogisticsService`, carton and shipment idempotency also share the same `_idem` namespace, which should not be able to cross-resolve object kinds.

## Required fix

Do not add a new identity/idempotency subsystem. Keep the existing services and simply make their internal keys safe:

- internally scope all caller-provided keys by `tenant_id`;
- keep same-tenant retry idempotent;
- different tenants using the same raw key must create/retrieve only their own object;
- separate idempotency namespaces by object kind where a service shares one map (`carton` vs `shipment`) or use a deterministic type prefix;
- on any existing object lookup, assert the stored object's tenant matches the requested tenant before returning it.

## Mandatory regressions

- Tenant A and B use raw WorkOrder idempotency key `same-key` -> distinct tenant-local WOs.
- Tenant A and B use raw ManufacturingRelease idempotency key `same-key` -> distinct tenant-local releases.
- Tenant A and B use raw carton idempotency key `same-key` -> distinct tenant-local cartons.
- Same tenant + same key retries return the same object.
- A carton idempotency key cannot collide with a shipment idempotency key/object namespace.
- No console/API response for tenant A contains an object created for B.

---

# Required evidence sequence before re-review

1. Fix code/tests only for the three blockers above; do **not** start Phase 421+.
2. Commit code/tests first as a new **CODE_EVIDENCE_SHA**.
3. Run `pytest -q`; report the count, but label it MOCK/unit/integration/FIXTURE — never Production Ready.
4. Push and require GitHub Actions ubuntu + windows GREEN for the code commit.
5. Because the code SHA changed, rerun the existing REAL acceptance from a **clean committed tree**.
6. Produce 4/4 release-bound Blender 5.2.1 + T1000 OptiX EvidenceBundles with `usedMock=false`, verifier PASS, exact new CODE_EVIDENCE_SHA, non-null matching `releaseHash`.
7. `PILOT_RELIABILITY_ACCEPTANCE.json` must still show the actual FIXTURE stress result, not a fabricated fallback; all required booleans/negatives must be explicit.
8. Update `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, and `REAL_E2E_ACCEPTANCE.md` only with facts actually re-proven.
9. Do not edit `CABINET_REAL_ACCEPTANCE.md` unless cabinet evidence itself changed.
10. Commit docs/evidence separately where practical and require current-head CI GREEN.
11. Leave Issue #1 a concise completion note containing CODE_EVIDENCE_SHA, docs SHA, test count, both CI runs, 4/4 REAL evidence summary, and unchanged truth labels.

# Exit criteria

Do **not** claim Phase 361–420 accepted until all are true:

- missing reliability stress can never be silently replaced by a passing fixture;
- runner returns non-zero/no publish for omitted, `None`, empty, or incomplete reliability evidence;
- frozen release sheet dimensions/grain are enforced during STRICT_STOCK when present;
- receipt lot geometry/grain is faithfully persisted and mismatch quarantine works;
- WorkOrder / ManufacturingRelease / carton caller idempotency is tenant-scoped;
- carton and shipment idempotency namespaces cannot collide;
- all new negative regressions pass;
- code CI and docs/head CI are GREEN;
- new clean-tree 4/4 REAL Blender evidence is bound to the new code commit and exact release hashes;
- FIXTURE/IMPORTED/MANUAL/MOCK/PARTIAL/BLOCKED labels remain honest;
- `globalProductionReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `fullAutonomousFactoryReady=false` remain false;
- no LIVE_CNC/LIVE_LASER/provider behavior is added;
- no second ERP/WMS/MES/QMS/scheduler/inventory engine is introduced.
