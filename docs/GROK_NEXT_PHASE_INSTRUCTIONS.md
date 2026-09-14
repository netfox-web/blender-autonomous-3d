# Development Agent 指令：Issue #6 Round 2 — EVIDENCE CLOSURE / RE-GATE HOLD

> Supervisor checkpoint: 2026-09-15
> Current main before this instruction: `84a39b3ce5f4186fe0824fb66add1a9d1db720ef`
> Reviewed PR: #13 `codex/video-ground-truth` — OPEN / unmerged
> Reviewed Round 2 CODE: `a5b368a3d907950c5165f4b1a0058853ace617fc`
> Exact CODE CI: `34900852044` — Ubuntu + Windows SUCCESS
> PR report: local `pytest -q` = 901 PASS, including 43 new Round 2 regressions / 114 video tests total
> Supervisor result: **CHANGES REQUIRED — implementation is materially improved, but Round 2 REAL acceptance + DOCS evidence are not yet complete.**
> Merge authorization: **NO**

## 0. What is accepted at code-review level

The Round 2 implementation is on the correct architecture lane and may proceed to evidence closure without a redesign.

Accepted as **REAL_LOGIC pending formal evidence**:
- every persisted prior video attempt is enumerated from a durable `.attempt-set.json` exact set before retry or publication;
- prior attempt journals are reloaded through verified `_load_attempt()` rather than trusted as raw JSON;
- missing/renamed/foreign/duplicate or SHA-mismatched attempt files fail closed;
- QA asset bytes/SHA, candidate artifact bytes/DAM lineage, tenant/generation/job/frame/role metadata and recomputed QA are rebound during verification;
- a verified prior PASS prevents a later retry;
- publication re-verifies the durable attempt set before selecting an accepted attempt;
- SMALL_ROOM context is separated from Product Truth with independent context objects + context mask, and context geometry/mask assignment is independently validated;
- room pixels are prohibited from entering ProductMask/ArtworkMask.

Do **not** rewrite Scheduler, Queue, DAM, Recipe, TwinStore, CabinetSpec, Product Truth, Artwork Placement, Product Truth Render Pack, Blender geometry interpreter, or the existing Issue #6 pipeline.

## 1. Why this is not ACCEPT yet

Round 2 CODE exists and its exact CI is green, but the formal handoff is incomplete:
- PR #13 currently ends at CODE `a5b368a...`; there is no Round 2 DOCS/evidence commit yet;
- no Round 2 clean-tree REAL Blender acceptance generation is committed for the exact CODE SHA;
- `ARTWORK_DETAIL_6S` and `SMALL_ROOM_10S` therefore cannot yet be promoted from PARTIAL to REAL;
- there is no exact DOCS SHA dual-platform CI for the Round 2 evidence package;
- no new `READY_FOR_RE_GATE` handoff has been posted after completion of those evidence steps.

GitHub Actions for CODE uses `FOX3D_MOCK_BLENDER=1`. It is regression evidence only and **must not** be used as REAL Blender or Production Ready evidence.

## 2. Required action — evidence closure only

Do not add unrelated features. Do not open a stacked PR. Continue only on existing PR #13.

### A. Freeze CODE lineage

If `a5b368a3d907950c5165f4b1a0058853ace617fc` needs no code correction, treat it as the final Round 2 CODE SHA and reuse CODE CI `34900852044`.

If the REAL run exposes any defect and code changes are necessary:
1. make the narrowest possible fix;
2. run full local regression;
3. push a new CODE SHA;
4. obtain new exact Ubuntu + Windows CI SUCCESS;
5. all subsequent REAL evidence must bind the new CODE SHA, not `a5b368a...`.

Do not create a docs commit before the final CODE SHA is frozen.

### B. Run clean REAL Blender Round 2 acceptance

From a clean working tree on the exact final CODE SHA, run `scripts/run_video_round2_e2e.py` with actual Blender 5.2.1 LTS / OptiX and `usedMock=false`.

The acceptance generation must cover the same frozen synthetic source product across:
- `HERO_ORBIT_8S` regression;
- `ARTWORK_DETAIL_6S`;
- `SMALL_ROOM_10S`.

For every sequence record and verify:
- exact CODE SHA and instruction SHA;
- `workingTreeClean=true`;
- Blender version / device / `usedMock=false`;
- recipe kind, duration, FPS, frame count and resolution;
- frame order + timestamp;
- camera matrix + intrinsics + product matrix;
- component observations and first/middle/last `.blend` reopen;
- Beauty / Depth / Normal / ProductMask / ArtworkMask / Alpha actual bytes, SHA-256 and size;
- finite decoded EXR checks;
- manifest / authority / receipt hashes;
- Blender job ID and DAM tenant/kind/metadata lineage.

For `ARTWORK_DETAIL_6S`, additionally prove:
- detail object is exactly the canonical artwork-bearing object;
- ArtworkMask is non-empty, not aliased to ProductMask, and contained by ProductMask;
- artwork identity / placement / UV lineage remain unchanged;
- wrong component injection is fail-closed.

For `SMALL_ROOM_10S`, additionally prove:
- `VideoRoomFloor` / `VideoRoomBack` are scene context only;
- context object geometry + passIndex/materialIndices match canonical scene context;
- `sceneContextMask` is non-empty and distinct from all Product Truth artifact paths;
- context mask does not overlap ProductMask or ArtworkMask;
- reopen observation preserves scene context geometry;
- Product/Artwork identity and product matrices are unchanged by the room scene.

If one REAL sequence cannot complete, label it PARTIAL/BLOCKED and report the actual failure. Do not fabricate a PASS.

### C. Durable attempt tamper evidence

Run the Round 2 durable candidate acceptance/tamper matrix on the exact final CODE SHA.

At minimum preserve fail-closed coverage for:
- prior decision/model/modelVersion/provider/seed/config tamper;
- identity/frame reorder/duplicate/missing/matrix tamper;
- QA asset path/SHA tamper;
- candidate mask/artifact bytes tamper;
- missing/corrupt/renamed/foreign attempt journal;
- duplicate logical attempt number / attempt-set mismatch;
- prior PASS followed by a new idempotency key;
- publication after any prior-lineage corruption.

Evidence must show no unauthorized new attempt, QA asset, preview publication, or Final Commerce Video is created after corruption.

Candidate pixels remain **FIXTURE_COPY / MOCK provider output**. The durable verification mechanism may be REAL_LOGIC; the candidate itself is not a live H3/LTX result.

## 3. Truth matrix for this Re-Gate

Until the evidence above is complete, use these labels:

### REAL
- only previously accepted Round 1 HERO_ORBIT clean REAL evidence remains REAL.
- Round 2 ARTWORK_DETAIL / SMALL_ROOM become REAL only after exact-CODE clean Blender evidence is completed and documented.

### REAL_LOGIC
- durable attempt-set verification;
- retry/publish fail-closed lineage;
- scene-context authority and context-mask validation;
- deterministic Product Lock pixel/metadata QA.

### FIXTURE / MOCK
- synthetic 800×295×900 four-door cabinet;
- generated asymmetric artwork;
- `FIXTURE_COPY` provider candidate pixels;
- GitHub Actions Blender path (`FOX3D_MOCK_BLENDER=1`).

### PARTIAL
- Round 2 REAL sequence evidence until clean acceptance is finished;
- Product Lock QA remains non-semantic and non-Vision;
- 128×128 control-preview resolution remains non-final commerce quality.

### BLOCKED / false
Keep all of the following false unless separately proven by independent authority/evidence:
- `DOOR_OPEN_REAL=false`;
- `doorOpenGroundTruthReady=false`;
- assembly authority;
- `visionQaReady=false`;
- `liveH3MaxProviderReady=false`;
- `liveLtx25ProviderReady=false`;
- `liveProviderReady=false`;
- Final Commerce Video;
- physical UV/RIP/print/hot-folder/machine write;
- LIVE_CNC / LIVE_LASER / PLC;
- `globalProductionReady=false`;
- `fullAutonomousFactoryReady=false`.

Do not infer hinge pivot/axis/range. `DOOR_OPEN` stays `BLOCKED_ARTICULATION_AUTHORITY` unless a current mainline independent authority supplies exact component/pivot/axis/range/transforms and worker-observed transforms.

## 4. Required docs after REAL run

After the exact final CODE REAL run completes, update only facts that actually changed:
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ACCEPTANCE.md`;
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ACCEPTANCE.json`;
- `docs/GROK_PROGRESS_REPORT.md`;
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`;
- `docs/REAL_E2E_ACCEPTANCE.md` only with scoped video readiness additions/changes.

Update architecture docs only if the implemented contract changed materially. Do **not** rewrite `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet engineering truth itself changed; this Round 2 does not authorize that.

Commit docs/evidence separately as one DOCS SHA, then require exact DOCS SHA GitHub Actions Ubuntu + Windows SUCCESS.

## 5. Final machine-readable handoff

Only after CODE CI + clean REAL + DOCS CI are all complete, post `READY_FOR_RE_GATE` to Issue #1 and Issue #6 with at least:

- `INSTRUCTION_SHA`
- `ISSUE=6`
- `PR=13`
- `CODE_SHA`
- `DOCS_SHA`
- `CODE_CI_RUN_ID`
- `DOCS_CI_RUN_ID`
- `TEST_COUNT`
- `EVIDENCE_GENERATION_ID`
- `WORKING_TREE_CLEAN=true`
- `REAL_BLENDER=true|false`
- `USED_MOCK=true|false`
- `VIDEO_GROUND_TRUTH_READY=true|false`
- `HERO_ORBIT_REAL=true|false`
- `ARTWORK_DETAIL_REAL=true|false`
- `SMALL_ROOM_REAL=true|false`
- `DURABLE_CANDIDATE_LINEAGE_READY=true|false`
- `DOOR_OPEN_REAL=false` unless independently proven
- `VISION_QA_READY=false`
- `LIVE_H3_PROVIDER_READY=false`
- `LIVE_LTX_PROVIDER_READY=false`
- `GLOBAL_PRODUCTION_READY=false`
- `MERGE_AUTHORIZED=false`

List REAL / REAL_LOGIC / FIXTURE / MOCK / PARTIAL / BLOCKED separately. Then **STOP for external Re-Gate**.

## 6. Forbidden

- no auto-merge PR #7–#13;
- no new stacked PR;
- no architecture rewrite;
- no dependency on unmerged PR #7–#12;
- no Mock/FIXTURE/REFERENCE → REAL promotion;
- no generative pixels → Product Truth promotion;
- no CI Mock Blender → REAL Blender promotion;
- no live provider/Vision readiness claim without real network evidence;
- no guessed door/assembly authority;
- no physical print/machine write;
- no unscoped Production Ready claim.
