# Grok 下一階段指令：Phase 481–540 Manual Factory Pilot V1 / Operational Control & Recovery

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed head: `f492b6b0a1c7282f7b9db25d01c30a28f1517522`  
> Reviewed CODE_EVIDENCE_SHA: `018cc70997a420e82358c0bb37677aa6b4de7eeb`  
> ChatGPT review result: **ACCEPT WITH SCOPE**  
> Phase 421–480 evidence-integrity correction is accepted. You may start Phase 481–540.

## Review result / accepted evidence

The `a827459` blockers are considered fixed for the current scope:

- deployment/operator acceptance now derives `evidenceCodeCommit` from the runner and records `workingTreeClean` at generation time;
- expected-commit mismatch, dirty tree and missing lineage fail non-zero and do not overwrite a previously valid package;
- destructive journal tamper uses an isolated, generation-scoped scratch journal rather than corrupting the shared Pilot journal;
- `journalHealthyBeforeTamper=true`, `tamperDetectionIsolated=true`, `journalTamperDetected=true`, `sharedJournalHealthyAfterAcceptance=true` are part of the fail-closed acceptance contract;
- current deployment acceptance reports shared journal `ok=true/status=REAL` after acceptance;
- process restart / work-order restart / station lease recovery / no-double-completion / releaseHash preservation / crash material conservation remain gated;
- CODE GitHub Actions run `34314263328` on `018cc70` is GREEN on Ubuntu and Windows;
- docs/head GitHub Actions run `34314618721` on `f492b6b` is GREEN on Ubuntu and Windows;
- local report says `pytest -q` = **208 passed**. This remains MOCK/unit/integration + FIXTURE/REAL_LOGIC evidence, never Production Ready;
- clean-tree REAL Blender evidence is 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX, `usedMock=false`, exact `commitSha=018cc70`, verifier PASS, non-null matching ManufacturingRelease `releaseHash`, artifact hash/size.

Truth boundaries remain mandatory:

- Vision / AI Video / Demand = **MOCK** unless a real authenticated provider is connected and exercised.
- OS sandbox / AR / print preflight / barcode hardware / McKee-BCT = **PARTIAL / ENGINEERING_ESTIMATE** unless separately proven.
- Supplier / carrier / FX / receipts = **IMPORTED / MANUAL**, not LIVE_PROVIDER.
- FIXTURE/CHAOS load = **FIXTURE**, not real factory throughput or SLA.
- LIVE_CNC / LIVE_LASER / PLC / machine actuation = **BLOCKED**.
- `globalProductionReady=false`.
- `liveFactoryExecutionReady=false`.
- `liveProviderReady=false`.
- `fullAutonomousFactoryReady=false`.
- Unscoped `productionReady=true` is forbidden.

Do not rewrite the existing Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / Logistics / Pilot architecture. Extend the current components and persistence boundaries only.

---

# Phase 481–488 — Operator identity, shift and station accountability

Extend the existing MANUAL_STATION/operator flow so every manual state-changing action has an authoritative operator identity and station/shift context.

Required:

- operator record: `operatorId`, tenant, display name, enabled/disabled, allowed manual capabilities;
- shift/session record: `shiftId`, operatorId, stationId, openedAt, closedAt, status;
- dispatch/ack/start/complete/QC/hold/rework/packing/stock-adjust actions must record operatorId + shiftId where applicable;
- disabled operator or closed shift cannot perform new state-changing actions;
- cross-tenant operator/station/shift references fail closed;
- restart must preserve open shift and station relationship;
- no password/authentication claim unless a real auth layer exists. If identity is only server-created/manual, label it **REAL_LOGIC / MANUAL_IDENTITY**, not production IAM.

Tests:

- valid operator/shift completes one manual operation;
- disabled operator rejected;
- closed shift rejected;
- cross-tenant shift rejected;
- restart preserves active shift exactly once;
- duplicate completion remains idempotent.

# Phase 489–496 — Traveler packet + scan token + printable manual work instructions

Use existing WorkOrder / releaseHash / traveler as the source of truth. Do not create a second job model.

Produce a versioned manual traveler packet containing:

- tenantId, workOrderId, releaseId, exact `releaseHash`, engineeringHash/BOM hash where available;
- ordered operation list and current statuses;
- required material lot/reservation refs;
- QC plan/hash and packing refs;
- operator/station placeholders;
- scan token / QR payload resolving back to the authoritative WorkOrder/operation;
- printable HTML or PDF artifact stored through existing DAM where practical.

Integrity rules:

- stale/superseded releaseHash -> traveler invalid/stale;
- token for tenant A cannot resolve in tenant B;
- token must not directly authorize an operation by itself; server-side tenant/operator/shift checks remain authoritative;
- barcode/QR **payload generation may be REAL_LOGIC**, but physical scanner/printer hardware remains **PARTIAL** unless actually exercised.

# Phase 497–504 — Cycle count and inventory adjustment control

Add manual physical inventory reconciliation on top of MaterialLot; do not bypass STRICT_STOCK.

Required flow:

- create `CycleCount` for selected lot(s);
- capture counted quantity, current system quantity, variance and reason;
- variance does not immediately mutate stock;
- adjustment enters `WAITING_HUMAN_APPROVAL`;
- approved adjustment produces a durable journal event and preserves conservation equation;
- rejected/cancelled adjustment leaves stock unchanged;
- adjustment cannot change consumed history or erase reservations;
- tenant isolation and idempotency required;
- all pre/post quantities preserved for audit.

Truth label: **REAL_LOGIC / MANUAL**. This is not ERP/accounting inventory valuation.

# Phase 505–512 — Actual manual labor/time capture and cost variance

Add append-only manual execution time capture without replacing the existing estimate/cost model.

Required:

- operation start/pause/resume/complete timestamps;
- manual labor minutes per WorkOrder operation;
- optional manual station time;
- append-only correction record rather than destructive editing;
- compute `estimatedLaborCost`, `actualManualLaborCost`, variance and variance reason;
- actual material cost can use frozen/imported lot cost snapshots only; do not call it accounting actual cost;
- retain cost source labels (`CONFIG_ESTIMATE`, `IMPORTED`, `MANUAL` etc.);
- no fabricated wage/provider rates.

Acceptance must explicitly distinguish **estimate**, **manual actual observation**, and **accounting actual** (not implemented).

# Phase 513–520 — Hold / defect / rework / scrap / remnant disposition

Extend the existing QC/exception flow into an operator-safe disposition workflow.

Required states/actions:

- HOLD with reason and actor;
- defect record linked to operation/QC/releaseHash;
- REWORK authorization creates append-only rework step/history;
- SCRAP disposition requires human confirmation and material quantity evidence;
- reusable material must go through existing remnant/inventory path rather than being silently counted as scrap;
- WorkOrder cannot complete while unresolved blocking hold/defect exists;
- restart preserves unresolved holds and rework lineage;
- no negative/duplicate material consumption.

Keep any engineering strength/certification inference PARTIAL unless separately validated.

# Phase 521–528 — Manual packing and shipment handoff boundary

Build on existing carton/shipment-draft logic only.

Required:

- packing checklist tied to WorkOrder/releaseHash;
- measured carton dimensions/weight captured as MANUAL observations;
- mismatch against expected packing data produces exception/hold, not auto-override;
- shipment handoff record can contain manual carrier name, tracking reference and handoff timestamp;
- no carrier booking/API claim unless a real provider adapter is connected;
- duplicate tracking/handoff updates are idempotent and tenant-scoped;
- shipment handoff does not imply delivery confirmation.

Labels: planning logic **REAL_LOGIC**, measurements/tracking **MANUAL/IMPORTED**, carrier provider **BLOCKED/NOT_CONNECTED**.

# Phase 529–536 — Backup / restore / startup reconciliation

Add a supported operational backup/restore path for Pilot durable state without redesigning storage.

Backup scope should include the current durable Pilot state needed to resume safely, such as:

- MaterialLot/inventory state;
- ManufacturingRelease snapshots;
- WorkOrders/travelers;
- station/lease/operator/shift state;
- journal/outbox state;
- QC/exception/packing records;
- references to DAM artifacts (do not silently pretend missing DAM bytes are restored).

Requirements:

- versioned manifest;
- file/hash/size checksums;
- tenant-aware export where applicable;
- restore to a fresh root and verify reconciliation;
- malformed/missing/tampered backup -> BLOCKED, non-zero;
- restore must not duplicate consumption/completion/journal events;
- restore must preserve releaseHash and idempotency semantics;
- include a subprocess restart after restore.

This is local operational backup, not cloud HA/DR unless actually implemented.

# Phase 537–540 — Manual Factory Pilot acceptance and operator recovery drill

Create new scoped acceptance documents, e.g.:

- `docs/MANUAL_FACTORY_PILOT_ACCEPTANCE.md/json`
- `docs/OPERATOR_SHIFT_ACCEPTANCE.md/json`
- `docs/INVENTORY_RECONCILIATION_ACCEPTANCE.md/json`
- `docs/PILOT_BACKUP_RESTORE_ACCEPTANCE.md/json`

Acceptance scenario must exercise at least two tenants and all four product families where applicable:

1. build/open exact ManufacturingRelease;
2. receive/import material using current MANUAL/IMPORTED boundary;
3. create/release WorkOrder under STRICT_STOCK;
4. open operator shift + station;
5. resolve traveler scan token;
6. dispatch/ack/start/complete manual operations;
7. execute at least one QC fail -> hold/rework -> pass path;
8. execute at least one cycle-count variance -> approval -> adjusted conservation path;
9. capture labor time and cost variance;
10. complete packing and manual shipment handoff;
11. hard process restart at a controlled mid-flow point;
12. backup, restore to a fresh root, reconcile and continue without duplicate completion/consumption;
13. prove cross-tenant operator/scan/backup access rejection;
14. verify shared journal remains healthy;
15. prove LIVE_CNC/LIVE_LASER remain BLOCKED.

Load/stress may use FIXTURE data, but it must be labeled FIXTURE. Do not report factory throughput/SLA.

---

# Mandatory fail-closed gates

A successful Phase 481–540 scoped acceptance must require all relevant gates to be exactly true; missing/false/malformed values fail non-zero. Include at minimum:

- `operatorTenantIsolation=true`;
- `shiftRestartRecovery=true`;
- `travelerReleasePinned=true`;
- `scanTokenTenantSafe=true`;
- `cycleCountApprovalRequired=true`;
- `inventoryConservedAfterAdjustment=true`;
- `laborHistoryAppendOnly=true`;
- `blockingHoldPreventsCompletion=true`;
- `reworkLineagePreserved=true`;
- `packingReleasePinned=true`;
- `manualShipmentNoProviderClaim=true`;
- `backupChecksumVerified=true`;
- `restoreReleaseHashPreserved=true`;
- `restoreNoDoubleConsume=true`;
- `restoreNoDoubleCompletion=true`;
- `journalHealthyAfterRestore=true`;
- `crossTenantRestoreRejected=true` or equivalent tenant-safe restore proof;
- `workingTreeClean=true` for review evidence generation;
- `evidenceCommitMatchesHead=true`;
- `liveMachineControl=false`;
- `globalProductionReady=false`;
- `liveFactoryExecutionReady=false`;
- `fullAutonomousFactoryReady=false`.

No `or True`, no fallback-generated PASS payloads, no default-success booleans.

# Evidence / CI sequence

1. Implement Phase 481–540 without starting machine control/provider work.
2. Add focused unit/integration/FIXTURE/REAL_LOGIC tests.
3. Run `pytest -q`; report exact count and labels. Mock/FIXTURE tests are never Production Ready.
4. Commit code/tests as a new **CODE_EVIDENCE_SHA**.
5. Push and require GitHub Actions Ubuntu + Windows GREEN on that code SHA.
6. From a clean committed tree, generate the new Phase 481–540 acceptance; runner must self-bind exact CODE_EVIDENCE_SHA and clean-tree status.
7. If code paths that affect ManufacturingRelease/Blender evidence changed, rerun clean-tree 4/4 REAL Blender evidence with the exact new CODE_EVIDENCE_SHA. If render/release code did not change, do not fabricate a refresh; clearly reference the previously accepted REAL render evidence and state why a refresh was not required.
8. Commit evidence/docs separately and require docs/head CI GREEN.
9. Update `docs/GROK_PROGRESS_REPORT.md`, `docs/CURRENT_IMPLEMENTATION_AUDIT.md`, `docs/REAL_E2E_ACCEPTANCE.md` and the new scoped acceptance docs. Update `docs/CABINET_REAL_ACCEPTANCE.md` only if cabinet evidence changed.
10. Leave Issue #1 a concise handoff comment with code SHA, docs SHA, test count, CI run IDs, acceptance generation, REAL/MOCK/PARTIAL/BLOCKED matrix, and remaining blockers.

## Exit gate for next ChatGPT review

Do not call Phase 481–540 Production Ready. It is accepted for review only if the new manual pilot workflow is durable, tenant-safe, release-pinned, auditable, backup/restorable, fail-closed, and the evidence labels remain honest. LIVE_CNC / LIVE_LASER / PLC / autonomous machine execution must still be BLOCKED.
