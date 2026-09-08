# Grok 修正指令：Phase 301–360 Pilot Integrity / Release-bound Evidence

> Repo: `netfox-web/blender-autonomous-3d`
> Review head: `c625e9780ca7730190d33d8a40d1ccc3772b32a7`
> Reviewed code commit: `64c5b6fc624ed1e2b6a75de9a1d76ba6701274b7`
> ChatGPT review result: **CHANGES REQUIRED**
>
> Phase 301–360 has substantial implementation and both GitHub Actions runs are GREEN (`34280419735` on code commit, ubuntu+windows; `34280601732` on docs/head). Local `pytest -q` reports 134 passed, but that remains MOCK/unit/integration evidence only. The 4 REAL Blender previews are Blender 5.2.1 + NVIDIA T1000 OptiX with `usedMock=false` and commit/hash/size verification. Do **not** treat those facts as global Production Ready.
>
> Do **not** start Phase 361+. Fix only the integrity/correctness gaps below, preserve the current architecture, then rerun the Phase 301–360 acceptance.

---

## Non-negotiable rules

1. **Do not rewrite** Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / RemnantStore / ReleaseGate / ManufacturingRelease / WorkOrder / QC / Physical Product OS architecture.
2. Extend the existing services minimally. Do not create a second ERP/WMS/MES/inventory master/approval system/evidence system.
3. LIVE_CNC / LIVE_LASER / liveFactoryExecution / liveProvider remain BLOCKED.
4. Vision / AI Video / Demand remain MOCK unless a genuine live provider is separately connected and evidenced.
5. OS sandbox / AR / print preflight / barcode print / McKee-BCT remain PARTIAL or ENGINEERING_ESTIMATE as already documented.
6. MANUAL / IMPORTED / FIXTURE / CONFIG / TEST_DATA must never be relabeled as LIVE_PROVIDER or Production Ready.
7. Human Approval Gate remains mandatory.

---

# Blocker 1 — Phase 358 `noDoubleConsume` is currently fail-open

Current `PilotOps.batch_stress()` contains a result equivalent to:

```python
"noDoubleConsume": double in {"idempotent", None} or True
```

That expression is always `True`; therefore the current stress result cannot prove the Phase 358 / exit-criteria claim that material cannot be double-consumed.

### Required fix

- Remove the unconditional truth path.
- Make `noDoubleConsume` derive from actual observed reservation/consumption state.
- `tests/test_pilot_ops.py::test_batch_stress_and_readiness` must explicitly assert `stress["noDoubleConsume"] is True`.
- Add a negative regression which intentionally creates/corrupts a double-consume condition or substitutes a failing consumption implementation, and prove the stress check becomes false/non-passing rather than silently returning true.
- If the stress summary is written into acceptance evidence, label it **FIXTURE**, not REAL factory execution.

---

# Blocker 2 — MaterialLot reservation is destructive before consume and cancel does not restore it

Current `WorkOrderService.reserve_materials()` calls `MaterialLotRegistry.allocate_sheet()`, which immediately decrements `remainingSheets`. `consume_reserved()` only consumes remnant reservations, and `cancel()` releases remnants but does not restore/deallocate lot sheets.

This means a cancelled reserved WorkOrder can leak material inventory, which violates the required reserve/consume/cancel semantics.

### Required fix

Reuse the existing `MaterialLotRegistry`; do not create a new inventory system.

Implement explicit lot reservation semantics, for example:

- reservation keyed by tenant + WorkOrder + lot + quantity,
- reserve is idempotent and does **not** irreversibly consume committed stock,
- consume/commit transitions the reservation exactly once,
- cancel/release returns unconsumed reserved quantity exactly once,
- restart/persistence behavior stays compatible with the existing durable lot registry where applicable,
- tenant isolation is enforced,
- available/reserved/consumed quantities remain conserved.

A compensating API is acceptable if it is deterministic and fully tested, but direct ad-hoc mutation in WorkOrder is not sufficient.

### Required regressions

At minimum prove:

1. capture lot availability before reserve;
2. reserve WO once and retry reserve — no duplicate reservation;
3. cancel WO — availability returns to the pre-reserve value;
4. create another WO, reserve then consume — stock decreases exactly once;
5. retry consume — stock does not decrease again;
6. cross-tenant reserve/release/consume is rejected;
7. material conservation is included in Phase 358 stress assertions.

---

# Blocker 3 — Required FINAL QC can currently be bypassed by caller boolean

Current `WorkOrderService.complete(..., qc_ok: bool = True)` trusts the caller. A caller can pass `qc_ok=True` even when the WorkOrder has no required FINAL QC records.

That does not satisfy Phase 332 / exit criterion: **missing mandatory QC must block COMPLETED**.

### Required fix

Do not create a second QC system. Reuse `QcService.required_final_ok()` / `completion_allowed()` and existing WorkOrder lineage.

Make WorkOrder completion fail closed using authoritative QC gate evidence. Acceptable approaches include a small injected validator/callback or a QC gate record/hash placed on the WorkOrder by the existing QcService. The caller-provided boolean may be retained for API compatibility, but it must **not** be the authority that allows completion.

### Required regressions

- WorkOrder with zero required FINAL checks: `complete(..., qc_ok=True)` must still fail.
- One required FINAL missing: fail.
- Latest required FINAL is failed: fail.
- Rework followed by latest passing required FINAL set: pass.
- Cross-tenant QC cannot satisfy another tenant’s WorkOrder.

---

# Blocker 4 — REAL Blender EvidenceBundles are not bound to the accepted ManufacturingRelease

The current four REAL preview bundles in `docs/MANUFACTURING_RELEASE_REAL_ACCEPTANCE.json` have valid commit/hash/size evidence, but their bundle field `releaseHash` is `null` for KD, retail, packaging and acrylic. The acceptance family rows separately contain non-null release hashes.

Cause: `render_family_previews()` builds a fresh product instead of rendering from / binding to the exact releases produced by the pilot E2E.

For Phase 357 this is insufficient lineage: it proves a REAL family render, but not that the rendered artifact corresponds to the ManufacturingRelease being accepted.

### Required fix

- Make the render acceptance use the exact product/release snapshots from the four-family pilot path (or explicitly pass those accepted releases into the renderer).
- Every required EvidenceBundle must include a **non-null expected `releaseHash`** matching the exact `ManufacturingRelease.releaseHash` for that family.
- Verify, fail closed, and record at minimum:
  - expected/bundle `commitSha` == clean committed CODE_EVIDENCE_SHA,
  - `releaseHash` == expected release hash,
  - engineeringHash matches the release snapshot,
  - bomHash matches the release snapshot where applicable,
  - `usedMock=false`,
  - real Blender/OptiX,
  - artifact hash + byte size PASS.
- A mismatch in releaseHash / engineeringHash / bomHash must make required REAL acceptance non-zero and must not publish replacement canonical acceptance.

Do not fabricate a releaseHash after rendering. It must come from the same accepted release lineage.

---

# Blocker 5 — Pilot readiness defaults are fail-open

Current `PilotOps.readiness()` uses defaults like `ev.get("releasePackage", True)`, so `platform.pilot.readiness()` with no evidence can report `manufacturingReleasePackageReady=true`, `manualPilotOpsReady=true`, etc.

### Required fix

- Missing evidence must default to **false / UNVERIFIED**, never true.
- Scoped readiness labels must derive from actual evidence, not be hard-coded REAL/IMPORTED when the evidence flag is false or absent.
- `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false` remain mandatory.

### Required regressions

- `platform.pilot.readiness()` with no evidence -> all positive Phase 301–360 scoped readiness flags false/UNVERIFIED.
- Explicit verified evidence can turn only the corresponding scoped flag true.
- Missing supplier/carrier import evidence cannot yield imported-* ready true.

---

# Blocker 6 — `run_pilot_e2e.py` does not fail closed on canonical six-file truth-set failure

The runner computes `canon = aggregate_canonical_consistency(docs)` and displays the result, but `canonicalTruthSetOk` is not currently part of `required_ok`.

Therefore a mixed-generation / mixed-commit / missing / malformed prior six-file canonical truth set can still allow this REAL runner to exit 0 and publish new Phase 301–360 acceptance.

### Required fix

- `canonicalTruthSetOk` must be a required fail-closed prerequisite for Phase 301–360 REAL acceptance.
- Mixed generation, mixed evidence commit, missing canonical file, malformed JSON -> runner non-zero.
- On those failures, existing canonical acceptance files must remain unchanged.
- Preserve the existing staged/atomic publish + rollback behavior; do not create a second acceptance system.

### Required runner-level regressions

Directly exercise `scripts/run_pilot_e2e.main()` or process exit behavior for:

1. valid six-file set -> can proceed;
2. mixed `acceptanceGenerationId` -> non-zero;
3. mixed `evidenceCodeCommit` -> non-zero;
4. missing required canonical JSON -> non-zero;
5. malformed JSON -> non-zero;
6. failure leaves canonical files unchanged.

---

# Required correction acceptance

After fixing the blockers above:

1. Commit all **code + tests** first. Record this as the new `CODE_EVIDENCE_SHA`.
2. Run `pytest -q`; report the count, explicitly labeling it MOCK/unit/integration unless a test actually invokes real Blender.
3. Push and require GitHub Actions ubuntu-latest + windows-latest GREEN on the new code commit.
4. From a **clean committed tree**, run Phase 301–360 REAL pilot acceptance again on the actually detected worker.
5. Required REAL Blender evidence must be 4/4 and release-bound as described above; no `releaseHash=null`.
6. REAL runner must be fail-closed on canonical truth set, release lineage, commit/hash/size, mock usage, and required evidence count.
7. Write/update evidence docs only after success; use the existing atomic/staged evidence semantics.
8. Commit docs/evidence separately where practical, then require current-head GitHub Actions GREEN.
9. Update truthfully:
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/MANUFACTURING_RELEASE_REAL_ACCEPTANCE.md` + JSON
   - `docs/PILOT_OPERATIONS_ACCEPTANCE.md` + JSON
   - `docs/QC_TRACEABILITY_ACCEPTANCE.md` + JSON
10. Do not edit `docs/CABINET_REAL_ACCEPTANCE.md` unless this correction actually changes its scope/evidence.

---

# Exit criteria for re-review

Do **not** move to Phase 361+ until all are true:

1. `noDoubleConsume` cannot be forced true by code path; stress test asserts it and has a negative failure regression.
2. Material lot reserve -> cancel restores unconsumed availability; reserve -> consume decrements exactly once; retries and tenants are safe.
3. WorkOrder completion cannot bypass required FINAL QC by passing `qc_ok=True`.
4. All 4 REAL Blender EvidenceBundles are bound to the exact accepted ManufacturingRelease with non-null matching `releaseHash`, plus matching engineering/BOM lineage where applicable.
5. Pilot readiness defaults false/UNVERIFIED when evidence is absent.
6. `run_pilot_e2e` fails non-zero if canonical six-file truth set is mixed/missing/malformed, and failed runs do not overwrite canonical evidence.
7. Local tests pass; code CI ubuntu+windows GREEN; docs/head CI GREEN.
8. REAL acceptance runs from a clean committed CODE_EVIDENCE_SHA with Blender/OptiX detected honestly and `usedMock=false`.
9. Truth labels remain honest: MOCK/PARTIAL/IMPORTED/MANUAL/FIXTURE/BLOCKED are not promoted.
10. `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `globalProductionReady=false`, `fullAutonomousFactoryReady=false`.

---

# Required Issue #1 handoff

When corrections are complete, leave one concise Issue #1 comment containing:

- new CODE_EVIDENCE_SHA and evidence/docs SHA,
- local pytest count + MOCK-suite note,
- code/head Actions run IDs and ubuntu+windows result,
- material reservation/cancel/consume conservation result,
- QC bypass regression result,
- Phase 358 double-consume positive + negative regression result,
- 4/4 REAL Blender release-bound EvidenceBundle result including non-null releaseHash,
- canonical six-file fail-closed runner result,
- remaining MOCK/PARTIAL/BLOCKED boundaries,
- `fullAutonomousFactoryReady=false`.

Do not ask the user to copy/paste the report. ChatGPT will re-read the repository directly.
