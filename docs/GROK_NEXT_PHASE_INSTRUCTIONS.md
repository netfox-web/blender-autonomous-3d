# Development Agent 指令：PR #8 Artwork / UV Print Workspace 修正 Re-Gate

> Repo: `netfox-web/blender-autonomous-3d`
> Main baseline: `7f8126144c6d26996b0f91843a4023748e466b79`
> New PR: #8 `codex/artwork-print-workspace` stacked on PR #7
> Reviewed CODE: `ce4a94c349b81b78613e9cad6e484485341822a3`
> CI run: `34824230284`
> Re-Gate result: **CHANGES REQUIRED**
> Queued after this correction: **Issue #6 — Blender → Generative Video Ground Truth Pipeline V1**

## 0. Why this is CHANGES REQUIRED

PR #8 contains substantive new work, but it is **not accepted yet** because exact dual-platform CI is not green.

Observed on Actions run `34824230284` for CODE `ce4a94c349b81b78613e9cad6e484485341822a3`:

- Windows job `103912519357`: **FAILURE**.
- Failing test: `tests/test_print_workspace.py::test_api_upload_job_proof_and_no_dispatch`.
- Failure:
  - test iterates `app.routes` and assumes every route has `.path`;
  - current FastAPI/Starlette exposes an `_IncludedRouter` entry without `.path`;
  - exception: `AttributeError: '_IncludedRouter' object has no attribute 'path'`.
- Ubuntu job for the same run was still in progress when reviewed. Regardless of its result, a Windows failure means the CODE SHA is not acceptable.

Local focused/regression results and development smoke evidence are useful, but they do **not** override failed exact-SHA GitHub CI.

## 1. Required CI portability fix

Fix the route-safety assertion without weakening the actual safety policy.

Preferred approach:
- make the test inspect only route entries that expose a path, for example with `getattr(route, "path", "")`, or explicitly filter to the concrete HTTP route type;
- continue asserting that **no actual exposed HTTP path** contains a production dispatch / hot-folder endpoint;
- do not modify production routing merely to satisfy the test;
- add/retain a regression that covers nested/included routers so this cannot regress across FastAPI/Starlette versions or OS runners.

After the fix:
1. run full `pytest -q` locally, not only the focused print tests;
2. push a new CODE SHA to PR #8;
3. require exact new CODE SHA Ubuntu + Windows Actions **SUCCESS**;
4. do not reuse run `34824230284` as green evidence.

## 2. Formal acceptance evidence still required

PR #8 currently changes code/tests/UI but has no committed formal acceptance docs in its diff. After CODE CI is green, produce formal evidence on the exact accepted CODE SHA.

Create/update at least:
- `docs/PRINT_WORKSPACE_ACCEPTANCE.md`
- a machine-readable print-workspace acceptance JSON
- `docs/GROK_PROGRESS_REPORT.md` only if this is the active handoff round
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md` only for truth changes actually proven

Keep global `docs/REAL_E2E_ACCEPTANCE.md` and `docs/CABINET_REAL_ACCEPTANCE.md` truth boundaries intact unless the new evidence genuinely changes them.

## 3. Clean-tree REAL Blender / source-file acceptance

After exact CODE CI is green, run the print-workspace E2E from a clean tree on the same CODE SHA and bind the evidence to that SHA.

At minimum prove, for both `THREE_DOOR` and `FLAT` where supported:
- source original is imported/read from a read-only source workflow and is not silently modified;
- source PDF dimensions / page mapping are preserved into proof metadata;
- source-size proof download is byte-backed and hash/size recorded;
- release remains fail-closed without required human checks/operator/measurement/RIP-material configuration;
- REAL Blender preview uses the actual local Blender runtime, records Blender version + render device, and is not `FOX3D_MOCK_BLENDER=1`;
- `.blend` reopen verifies component geometry, packed source texture bytes and final UV sampling;
- service restart can rediscover persisted job/preview state;
- artifact SHA-256 and byte sizes are verified from stored bytes;
- no network dispatch, hot-folder write, production job submission, or machine control occurs.

Evidence must include:
- exact `CODE_SHA`;
- `workingTreeClean=true`;
- evidence generation ID;
- Blender version / device;
- `usedMock=false` for the REAL Blender portion;
- source asset hash(es);
- proof bundle hash/size;
- preview artifact hashes/sizes;
- reopen/restart results.

## 4. Truth classification for PR #8

Until the above gate passes, classify the new work as follows:

### PARTIAL / UNACCEPTED
- Chinese artwork / UV print-file workspace UI;
- source import/indexing flow;
- source-size PDF proof workflow;
- manual RIP release gate;
- print preview orchestration;
- actual-source development smoke.

Reason: implementation exists, but exact dual-platform CODE CI is currently failing and formal acceptance docs are not yet committed.

### REAL_LOGIC candidate, pending green Re-Gate
- read-only source handling rules;
- proof/revision invalidation logic;
- explicit human release gate;
- no-dispatch policy;
- file-handoff-only NetFox Print boundary.

These may be promoted only after full regression + exact SHA CI + formal evidence.

### REAL evidence candidate, pending formal binding
- local Blender 5.2.1 / OptiX preview/reopen smoke reported for THREE_DOOR and FLAT.

Do not call this accepted REAL until the evidence is regenerated from a clean tree and bound to the final green CODE SHA.

### BLOCKED / false
- NetFox Print network submission;
- hot-folder dispatch;
- production RIP execution;
- actual machine/material setup;
- physical UV print validation;
- LIVE_CNC / LIVE_LASER / PLC / machine control.

Keep:
- `physicalPrintValidated=false`;
- `liveMachineControl=false`;
- any network print dispatch readiness = false.

### MOCK / FIXTURE boundary
- `FOX3D_MOCK_BLENDER=1` Actions runs are regression evidence only;
- fixture/source test PDFs are not licensed historical production artwork;
- no Mock / fixture path may be promoted to Production Ready.

## 5. Licensed / historical artwork boundary

The reported local library index of 4,451 supported artwork files is **local discovery evidence only**.

Rules:
- do not upload licensed originals to GitHub;
- do not infer commercial/production authorization from file presence;
- preserve source hashes and local source identity without embedding restricted files in repo evidence;
- if a test fixture is used in CI, label it FIXTURE;
- historical/customer/IP originals remain outside GitHub unless explicitly authorized.

## 6. NetFox Print boundary

Current integration remains:

`FILE_HANDOFF_ONLY_NOT_SUBMITTED`

The reported remote inspection (`/data/apps/mw/web/uvprint`, PDF/ZIP job-file support, CSV+raster auto-layout, PHP proxy to localhost:5050 with no host listener) is discovery information only.

Do **not**:
- change the remote NetFox Print host;
- write to production job directories;
- submit a live print job;
- create a hot-folder dispatcher;
- add credentials to repo/logs;
- claim live integration because SSH/read-only inspection succeeded.

## 7. CODE / DOCS acceptance sequence

Use the same split-evidence discipline as prior accepted rounds:

1. Fix the Windows/cross-version test portability issue.
2. Full local regression.
3. Push final CODE SHA.
4. Exact CODE SHA Ubuntu + Windows CI SUCCESS.
5. Clean-tree REAL print-workspace/Blender acceptance on that CODE SHA.
6. Commit acceptance docs/evidence separately as DOCS SHA.
7. Exact DOCS SHA Ubuntu + Windows CI SUCCESS.
8. Post one `READY_FOR_RE_GATE` handoff.
9. STOP and wait for external Re-Gate.

Do not auto-merge PR #7 or PR #8.

## 8. READY_FOR_RE_GATE contract

Post the full handoff in PR #8 or its issue thread and a short pointer in Issue #1:

- `INSTRUCTION_SHA`
- `PR_NUMBER=8`
- `CODE_SHA`
- `DOCS_SHA`
- `CODE_CI_RUN_ID`
- `DOCS_CI_RUN_ID`
- `TEST_COUNT`
- `EVIDENCE_GENERATION_ID`
- `WORKING_TREE_CLEAN=true`
- `REAL_BLENDER=true|false`
- `USED_MOCK=true|false`
- `PRINT_WORKSPACE_LOGIC_READY=true|false`
- `REAL_PRINT_PREVIEW_READY=true|false`
- `NETFOX_PRINT_LIVE_DISPATCH_READY=false`
- `PHYSICAL_PRINT_VALIDATED=false`
- `LIVE_MACHINE_CONTROL=false`

List REAL / REAL_LOGIC / FIXTURE / MOCK / PARTIAL / BLOCKED separately.

## 9. Issue #6 remains queued, not cancelled

The prior instruction for **Issue #6 — Blender → Generative Video Ground Truth Pipeline V1** remains the next approved product-development direction, but **HOLD implementation until PR #8 returns for Re-Gate**.

After PR #8 is accepted, resume the already-approved Issue #6 scope:
- provider-neutral `VideoRecipe`;
- per-frame RGB/Depth/Normal/ProductMask/ArtworkMask;
- camera/object matrices + deterministic frame manifest;
- REAL `HERO_ORBIT_8S`;
- `DOOR_OPEN_8S` fail-closed when articulation authority is absent;
- H3/LTX adapter contracts without Mock→REAL promotion;
- deterministic Product Lock QA;
- retry / DAM lineage;
- full dual-platform CI + clean REAL Blender evidence.

Do not start Issue #6 in parallel with an unresolved PR #8 correction unless explicitly re-authorized.

## 10. Existing global blockers remain unchanged

Supervisor LIVE E2E remains externally blocked unless prerequisites actually change:
- public HTTPS webhook ingress missing;
- webhook secret missing;
- live provider credential/model config missing;
- admin key missing.

Keep:
- `webhookRealE2e=false`;
- Supervisor `liveProviderReady=false`;
- `eventDrivenSupervisorReady=false`.

Also keep LIVE_CNC / LIVE_LASER / PLC BLOCKED.

## 11. Forbidden

- no architecture rewrite;
- no production routing change only to make a test pass;
- no Mock → REAL promotion;
- no licensed artwork upload to GitHub;
- no live NetFox Print submission/hot-folder/machine write;
- no automatic merge of PR #7 or #8;
- no Issue #6 implementation before this correction Re-Gate is complete;
- no unscoped `productionReady=true`.
