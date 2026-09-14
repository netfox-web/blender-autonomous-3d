# Development Agent 指令：Issue #6 Round 2 — Video Ground Truth Hardening / Durable Candidate Lineage

> Supervisor Re-Gate checkpoint: 2026-09-15
> Main before this checkpoint: `8d54bb9bf1786ef8c9bbf7122cbb770927be5cda`
> Reviewed PR: #13 `codex/video-ground-truth` — still OPEN / unmerged
> PR #13 CODE: `728e954af3312c8ad625e242918cbb029d0c1993`
> PR #13 DOCS/head: `7fc4cb39d1c5d3c916dfee498124f7291fb40701`
> CODE CI: `34887469718` — Ubuntu + Windows SUCCESS, 858 tests/OS
> DOCS CI: `34890613886` — Ubuntu + Windows SUCCESS, 858 tests/OS
> Clean REAL evidence: `e42c8575-56db-473a-bd28-d8353dc536cc`, `workingTreeClean=true`, `developmentOnly=false`, Blender 5.2.1 LTS / OPTIX
> Re-Gate result: **PR #13 ACCEPT WITH SCOPE / NO MERGE AUTHORIZATION**
> Authorized lane: **continue hardening the existing PR #13 branch only; do not open a stacked PR and do not auto-merge**.

## 0. Accepted scope and truth boundary

PR #13 is accepted for deterministic Video Ground Truth V1 only.

### REAL
- exact-CODE clean-tree `HERO_ORBIT_8S` on real Blender 5.2.1 LTS / OPTIX;
- 8 s / 12 fps / 96 frames;
- 576 actual Beauty/Depth/Normal/ProductMask/ArtworkMask/Alpha artifacts;
- first/middle/last `.blend` reopen observations;
- actual frame order/timestamps, camera/object matrices, optics/scene/light observations, finite EXR checks;
- artifact bytes/SHA/size and persisted DAM/job lineage.

### REAL_LOGIC
- frozen pre-worker Product/Engineering/Artwork/Placement authority;
- deterministic Video/Camera/Scene recipe hashes;
- sealed authority + controller receipt + canonical manifest;
- persisted reload/tamper guards;
- provider-neutral H3/LTX request contracts that remain network-blocked;
- deterministic Product Lock QA proxy with PASS/RETRY/REJECT;
- provider/model/version/seed/config persistence, idempotent retries and preview publication gate.

### FIXTURE / MOCK
- source product is an explicit synthetic 800×295×900 cabinet with four doors and generated asymmetric artwork; it is not a company-measured product and does not import the unmerged Issue #4 Golden Product;
- CI Blender remains MOCK regression evidence;
- current provider candidate pixels are `FIXTURE_COPY`, not H3/LTX output.

### PARTIAL
- current REAL sequence is 128×128 control-preview resolution, not final commerce video;
- `ARTWORK_DETAIL_6S` and `SMALL_ROOM_10S` have recipe/worker paths but no dedicated clean REAL acceptance yet;
- Product Lock QA is a deterministic pixel/metadata proxy, not semantic Vision;
- candidate journal/local DAM persistence is not an OS trust boundary and needs further durable-lineage hardening.

### BLOCKED / false
- `DOOR_OPEN_REAL=false` / authoritative hinge articulation unavailable;
- assembly animation authority unavailable;
- live H3/LTX/Vision/provider calls;
- Final Commerce Video;
- physical UV/RIP/print/hot-folder/machine writes;
- Supervisor live webhook/provider prerequisites;
- LIVE_CNC / LIVE_LASER / PLC;
- unscoped/global Production Ready.

No Mock/FIXTURE/REFERENCE output may be promoted to REAL or Production Ready.

## 1. Branch and architecture discipline

Continue **only** on the existing PR #13 branch `codex/video-ground-truth`. Do not create another stacked feature PR for this round. Do not auto-merge PR #7–#13.

Do not rewrite Scheduler, Queue, DAM, Recipe, TwinStore, CabinetSpec, Product Truth, Artwork Placement, Product Truth Render Pack, or the existing Blender geometry interpreter. Keep this round narrow and additive.

Issue #5 overlaps the same video lane: do not reimplement a second Video Ground Truth engine merely to satisfy another issue number.

## 2. Priority A — close durable candidate-journal lineage gap

Current accepted lineage is immutable in normal execution, but Round 2 must fail closed if a previously persisted attempt journal is altered before a later retry.

Required changes:
- every existing prior attempt journal must be loaded through the same verified `_load_attempt()` path before it influences retry count, accepted-lineage lock, or next-attempt authorization;
- a corrupt, missing-required-field, renamed/duplicated, SHA-mismatched or otherwise unverifiable prior journal must **BLOCK** creation of any new attempt;
- if any independently verified prior attempt is `PASS`, no later attempt may be created;
- retry numbering/count must derive from the verified durable set, never raw unverified JSON;
- QA asset SHA/bytes and candidate artifact bytes/DAM refs must remain part of verification;
- do not silently repair or overwrite a damaged accepted journal.

Add negative tests at minimum for:
- prior accepted journal `qa.decision` tamper;
- model/provider/modelVersion/seed/config tamper;
- candidate identity/frame/artifact tamper;
- `qaAsset.path` / `qaAsset.sha256` tamper;
- missing attempt file / duplicate logical attempt number / renamed foreign file;
- corrupt prior journal followed by a new idempotency key;
- verified prior PASS followed by a new key.

Expected behavior: fail closed, no new DAM candidate, no new accepted/rejected QA asset, no preview/final publication.

## 3. Priority B — expand dedicated REAL sequence coverage without inventing authority

After Priority A is green, run clean exact-CODE REAL acceptance for:
- `ARTWORK_DETAIL_6S`;
- `SMALL_ROOM_10S`.

For `ARTWORK_DETAIL_6S`, independently verify:
- target component equals the canonical artwork-bearing object;
- ArtworkMask remains non-empty, non-aliased and contained by ProductMask;
- camera look-at / recipe hash / artwork identity remain bound to frozen authority;
- cross-component artwork injection fails closed.

For `SMALL_ROOM_10S`, independently verify:
- room geometry/light/background are scene context only and never become product geometry authority;
- room/background pixels cannot enter ProductMask/ArtworkMask;
- product matrices and Product/Artwork identities remain unchanged through the sequence;
- SceneRecipeHash differs deterministically from HERO while Product Truth identity remains the same.

If machine/runtime cost prevents both full sequences in one evidence generation, complete `ARTWORK_DETAIL_6S` first and report `SMALL_ROOM_10S=PARTIAL`; do not fabricate PASS.

## 4. DOOR_OPEN / assembly remain fail-closed

Do not weaken `BLOCKED_ARTICULATION_AUTHORITY` or `BLOCKED_ASSEMBLY_AUTHORITY`.

`DOOR_OPEN_REAL=true` is allowed only if an independent mainline authority supplies exact component ID, hinge pivot, axis, allowed range, canonical closed/open transforms, SKU/product version and worker-observed transforms. Caller metadata or a claimed `ready=true` is never authority.

If such authority does not exist, retain:
- `DOOR_OPEN_REAL=false`;
- `doorOpenGroundTruthReady=false`;
- `BLOCKED_ARTICULATION_AUTHORITY`.

No guessed pivot/axis/range for demos.

## 5. Provider and Vision boundary stays blocked

Do not add credentials and do not perform live provider claims in this round.

Keep:
- `liveH3MaxProviderReady=false`;
- `liveLtx25ProviderReady=false`;
- `liveProviderReady=false`;
- `visionQaReady=false`.

H3/LTX packages may be strengthened only as provider-neutral immutable contracts. They must bind manifest hash, frame/control artifact role + SHA/size, camera metadata, Product/Artwork identity and constraints. Local file paths alone must not be treated as remote-provider delivery proof.

A real-provider candidate must not be routed through the current `FIXTURE_COPY` acceptance path merely by changing a flag.

## 6. Product Lock QA hardening

Keep current deterministic QA explicitly `REAL_LOGIC`, not Vision.

Add adversarial coverage for:
- frame-local mask byte tamper after journal persistence;
- candidate frame reorder/duplicate/missing after QA;
- temporal single-frame identity/matrix drift;
- provider/model/config mutation between QA and publish;
- accepted preview replay under a different manifest/generation;
- candidate DAM reference points to valid bytes from another tenant/job/frame.

Every preview publication must re-validate the sealed ground truth, the durable attempt, candidate bytes and QA result. Final Commerce Video stays BLOCKED.

## 7. Acceptance / evidence requirements

Do not rewrite historical truth docs merely for narrative consistency. Update only fresh Issue #6 Round 2 acceptance artifacts, and update broader audit/readiness docs only if their actual scoped truth changes.

Required evidence sequence:
1. implement Priority A + tests;
2. full local `pytest -q`;
3. commit/push one final CODE SHA on PR #13;
4. exact CODE SHA GitHub Actions: Ubuntu + Windows both SUCCESS;
5. clean tree at exact CODE SHA;
6. run REAL Blender acceptance for HERO regression plus new dedicated sequence(s);
7. verify actual bytes/SHA/size/matrices/masks/reopen/DAM/job lineage and journal tamper matrix;
8. commit docs/evidence separately as DOCS SHA;
9. exact DOCS SHA Actions: Ubuntu + Windows both SUCCESS;
10. post one `READY_FOR_RE_GATE` to Issue #1 and Issue #6;
11. STOP.

`FOX3D_MOCK_BLENDER=1` remains CI regression evidence only.

## 8. Round 2 machine-readable handoff

Report at minimum:
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

Then list `REAL / REAL_LOGIC / FIXTURE / MOCK / PARTIAL / BLOCKED` separately and STOP for external Re-Gate.

## 9. Forbidden

- no architecture rewrite;
- no auto-merge of PR #7–#13;
- no new stacked feature PR for this round;
- no dependency on unmerged #7–#12;
- no Mock/FIXTURE/REFERENCE → REAL promotion;
- no generative pixels → Product Truth promotion;
- no fabricated articulation/assembly authority;
- no live-provider or Vision readiness claim without separate real network evidence;
- no physical print/machine write;
- no unscoped Production Ready claim.
