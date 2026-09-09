# Grok 修正指令：Phase 421–480 Evidence Integrity Correction — Journal Health / Hermetic Acceptance / Code Binding

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `b0e67c0595ccb5dfbd4c811e58cd4448a013ff35`  
> Reviewed CODE_EVIDENCE_SHA: `94719576b00f33a9fc26e8087d8233c78c302805`  
> ChatGPT review result: **CHANGES REQUIRED**  
> **Do not start Phase 481+ yet.** Fix only the evidence-integrity gaps below. Do not rewrite existing Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / Logistics / Pilot architecture.

## What is accepted from the previous correction

The previous `a3c150f` correction was substantially implemented and should not be redone:

- PREPARED outbox → durable business commit → journal COMMITTED semantics are now present for MaterialLot transaction paths;
- WorkOrder / ManufacturingRelease / receipt / MANUAL_STATION lease state now has durable restart snapshots/reconciliation;
- actual subprocess `os._exit` crash fixtures exist for controlled persistence boundaries;
- FIXTURE business-E2E rows are no longer promoted to plain REAL; persistence/process checks are explicitly `REAL_LOGIC`;
- local handoff reports `pytest -q` = **200 passed**, but this remains MOCK/unit/integration + FIXTURE/REAL_LOGIC evidence, never Production Ready;
- GitHub Actions CODE run `34309132821` on `9471957` is SUCCESS on both `ubuntu-latest` and `windows-latest`;
- docs/head run `34309413179` on `b0e67c0` is also SUCCESS on both `ubuntu-latest` and `windows-latest`;
- clean-tree ManufacturingRelease render evidence is acceptable for its narrow REAL scope: 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, exact `commitSha=9471957`, verifier PASS, non-null matching ManufacturingRelease `releaseHash`, artifact hash/size;
- LIVE_CNC / LIVE_LASER / live provider / live factory execution remain BLOCKED, which is correct.

Truth boundaries remain mandatory:

- Vision / AI Video / Demand = **MOCK** unless a real authenticated provider is connected and exercised.
- OS sandbox / AR / print preflight / barcode / McKee-BCT = **PARTIAL / ENGINEERING_ESTIMATE** unless separately proven.
- Supplier / carrier / FX / receipts = **IMPORTED / MANUAL**, not LIVE_PROVIDER.
- FIXTURE/CHAOS throughput is **FIXTURE**, not factory throughput.
- LIVE_CNC / LIVE_LASER / PLC / machine actuation / live factory execution = **BLOCKED**.
- `globalProductionReady=false`.
- `liveFactoryExecutionReady=false`.
- `liveProviderReady=false`.
- `fullAutonomousFactoryReady=false`.
- Unscoped `productionReady=true` remains forbidden.

---

# Blocking gap 1 — Current deployment acceptance is internally inconsistent and fail-open

The current `docs/PILOT_DEPLOYMENT_ACCEPTANCE.json` says overall `ok=true`, while the same evidence contains:

- `chaos.journalIntegrity.chainOkBefore=false`;
- `chaos.health.journalIntegrity.ok=false`;
- `chaos.health.journalIntegrity.status=BLOCKED_EVIDENCE`;
- `chaos.health.journalIntegrity.reason=payload-tamper`.

This package cannot be accepted as a healthy Phase 421–480 deployment-integrity PASS. A tamper detector working is good, but a journal that is already unhealthy before the destructive test, or a shared health view left in `BLOCKED_EVIDENCE`, must never coexist with overall `ok=true`.

## Required correction

Make the acceptance fail closed on journal health, not merely on `tamperDetected`.

Add explicit mandatory booleans such as:

- `journalHealthyBeforeTamper`;
- `sharedJournalHealthyAfterAcceptance`;
- `tamperDetectionIsolated`;
- `journalTamperDetected`.

The runner's `ok` and exit code must require all of them to be exactly `true`. Missing / `None` / malformed / `false` must fail.

At minimum:

1. verify the shared acceptance journal is healthy before the destructive tamper test;
2. run the tamper test in isolation as described below;
3. verify the shared Pilot journal/health is still healthy after all acceptance checks;
4. if `/api/pilot/health` or equivalent returns `journalIntegrity.ok != true` / `BLOCKED_EVIDENCE`, scoped deployment acceptance must be non-zero and must not publish a successful package.

Do not weaken `EventJournal.verify()` and do not convert `BLOCKED_EVIDENCE` into a warning.

---

# Blocking gap 2 — Destructive journal tamper test must not contaminate shared acceptance state

`ChaosHarness._journal_cases()` currently performs `j.tamper(...)` on the same journal used by the shared Pilot/health acceptance. The current JSON proves that the destructive test leaves that journal in `BLOCKED_EVIDENCE`.

## Required correction

Make the destructive tamper evidence hermetic.

Preferred implementation:

- create a fresh, generation-scoped scratch journal root exclusively for the tamper test;
- seed a small valid chain there;
- assert `verify(...).ok == true` before tamper;
- tamper the scratch chain;
- assert `verify(...).status == BLOCKED_EVIDENCE` after tamper;
- record this as `tamperDetectionIsolated=true` / `journalTamperDetected=true`;
- never mutate the shared Pilot journal used by operator/health/restart acceptance.

Also make the Phase 421–480 acceptance root hermetic enough that repeated runs do not inherit stale broken journal state from a prior acceptance run. Do not delete production/user data; use a dedicated acceptance namespace/root or generation-scoped subdirectory.

## Mandatory regressions

Add runner/harness tests for:

- invalid journal before tamper -> acceptance fails non-zero;
- shared health `BLOCKED_EVIDENCE` -> acceptance fails non-zero;
- isolated scratch tamper is detected while the shared Pilot journal remains healthy;
- two consecutive acceptance runs on a clean committed codebase both pass and do not accumulate/consume stale contaminated state;
- a previously failed/tampered scratch generation cannot poison the next clean generation.

---

# Blocking gap 3 — Deployment/operator evidence code SHA is post-hoc, not runner-bound

`scripts/run_pilot_deploy_e2e.py` currently does not derive or verify `evidenceCodeCommit` / `workingTreeClean` itself, yet the committed acceptance JSON files contain `evidenceCodeCommit=9471957`. Evidence lineage must not depend on a later manual/docs edit that can stamp a desired SHA onto an already-generated payload.

## Required correction

Bind Phase 421–480 acceptance to the code commit inside the runner itself.

Required behavior:

- derive current `git rev-parse HEAD` and clean/dirty status, or accept an explicit `--expected-commit` and compare it to the actual current HEAD;
- write `evidenceCodeCommit` and `workingTreeClean` directly into both `PILOT_DEPLOYMENT_ACCEPTANCE.json` and `OPERATOR_CONTROL_ACCEPTANCE.json` at generation time;
- if an expected commit is supplied and does not exactly equal HEAD, fail non-zero;
- production/review evidence generation must require `workingTreeClean=true`;
- dirty-tree evidence must not be publishable as a successful review package;
- the runner must refuse missing/malformed commit lineage rather than synthesize/pass a default;
- failed lineage verification must not overwrite a previously valid success package.

Do not manually post-edit `evidenceCodeCommit` after the runner finishes.

## Mandatory regressions

Add tests proving:

- expected commit == actual clean HEAD -> success and JSON contains that exact SHA;
- expected commit mismatch -> non-zero and no successful overwrite;
- dirty tree -> non-zero for review evidence and no successful overwrite;
- missing commit lineage -> non-zero;
- deployment and operator JSON generated in the same run carry the same `acceptanceGenerationId`, same `evidenceCodeCommit`, and `workingTreeClean=true`;
- the final docs/evidence package cannot claim a CODE_EVIDENCE_SHA different from what the runner observed.

---

# Acceptance gate must include all integrity properties

Keep the existing mandatory gates and add the new journal/lineage gates. The success contract should require, at minimum:

- `journalBusinessCommitConsistent=true`;
- `noCommittedGhostJournalEvents=true`;
- `processRestartRecovery=true`;
- `stationRestartRecovered=true`;
- `workOrderRestartRecovered=true`;
- `noDoubleCompletionAfterRestart=true`;
- `releaseHashPreservedAfterRestart=true`;
- `materialConservedAfterCrash=true`;
- `tenantIsolationAfterRestart=true`;
- `journalHealthyBeforeTamper=true`;
- `tamperDetectionIsolated=true`;
- `journalTamperDetected=true`;
- `sharedJournalHealthyAfterAcceptance=true`;
- `evidenceCommitMatchesHead=true`;
- `workingTreeClean=true`.

A failed property must produce non-zero exit and a clearly BLOCKED/PARTIAL evidence result; never fabricate a passing fallback.

---

# Required evidence sequence after correction

1. Fix only these Phase 421–480 evidence-integrity gaps. **Do not start Phase 481+.**
2. Add the fail-closed journal-health, hermetic-tamper, repeatability, commit-lineage and dirty-tree regressions.
3. Run `pytest -q` and report the exact count. Keep the truth label MOCK/unit/integration/FIXTURE/REAL_LOGIC as appropriate; never Production Ready.
4. Commit code/tests first as a new **CODE_EVIDENCE_SHA**.
5. Push and require GitHub Actions `ubuntu-latest` + `windows-latest` GREEN on that code commit.
6. From a clean committed tree, run Phase 421–480 acceptance with the runner self-binding the exact CODE_EVIDENCE_SHA. Verify shared journal health is true before and after acceptance.
7. Because the code SHA changes, rerun clean-tree REAL Blender evidence for all 4 families: Blender 5.2.1 LTS + currently detected real NVIDIA OptiX device, `usedMock=false`, exact new CODE_EVIDENCE_SHA, verifier PASS, non-null matching ManufacturingRelease `releaseHash`, artifact hash/size.
8. Commit evidence/docs separately where practical and require current-head CI GREEN.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md`, `docs/PILOT_DEPLOYMENT_ACCEPTANCE.*`, `docs/OPERATOR_CONTROL_ACCEPTANCE.*`. Update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet evidence itself changed.
10. Leave Issue #1 a concise completion comment with code SHA, docs SHA, pytest count, code/head CI runs, journal-health booleans, hermetic tamper evidence, commit-lineage evidence, 4/4 REAL Blender evidence, truth labels and remaining boundaries.

## Exit gate for next ChatGPT review

Phase 481+ remains blocked until all are true:

- deployment acceptance never reports `ok=true` while shared journal health is false/BLOCKED;
- tamper detection is isolated and cannot corrupt the shared acceptance journal;
- consecutive clean acceptance runs are repeatable and healthy;
- deployment/operator evidence self-binds exact clean HEAD inside the runner, not by post-hoc docs edits;
- all mandatory integrity/lineage gates fail closed;
- new CODE_EVIDENCE_SHA has Ubuntu + Windows CI GREEN;
- clean-tree 4/4 REAL Blender evidence is rebound to the new CODE_EVIDENCE_SHA;
- current evidence/docs head CI is GREEN;
- Vision / AI Video / Demand remain MOCK unless genuinely connected;
- sandbox / AR / preflight / barcode / McKee remain PARTIAL unless genuinely proven;
- supplier/carrier/FX/receipts remain IMPORTED/MANUAL;
- `globalProductionReady=false`, `liveFactoryExecutionReady=false`, `liveProviderReady=false`, `fullAutonomousFactoryReady=false`;
- LIVE_CNC / LIVE_LASER remain BLOCKED.
