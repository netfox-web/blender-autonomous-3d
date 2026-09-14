# Development Agent 指令：Issue #6 Blender → Generative Video Ground Truth Pipeline V1

> Repo: `netfox-web/blender-autonomous-3d`
> Re-Gate source: Issue #4 READY_FOR_RE_GATE / PR #7
> Accepted scoped CODE: `c9f685854a964d567643cab55f06aceb0c7375d2`
> Accepted scoped DOCS: `f65f264eb8083c08a55b9449acb1b3748eeb68e5`
> CODE Actions: `34811888485` — Ubuntu + Windows SUCCESS
> DOCS Actions: `34813670099` — Ubuntu + Windows SUCCESS
> Full regression: `828` tests on each OS
> Clean REAL Blender generation: `b1d53004-3a4c-4f6d-b192-1ebb85877a6d`
> Re-Gate result: **ACCEPT WITH SCOPE**
> Next work item: **Issue #6 — Blender → Generative Video Ground Truth Pipeline V1**

## 0. Re-Gate truth boundary

Issue #4 is accepted only as a **scoped preview / artwork-placement Golden Product**.

Accepted as REAL / REAL_LOGIC:
- one shared 424×295×900 mm recipe identity with four SKU identities;
- deterministic EngineeringHash shared by the four SKU fixture packages;
- MASTER_SPLIT and SINGLE_SURFACE placement logic;
- mm → crop → UV → packed image → production-trim lineage;
- clean-tree Blender 5.2.1 / OptiX generation, PNG / GLB / `.blend`, blend reopen, HTTP download and service-restart verification;
- exact Ubuntu + Windows CI on CODE and DOCS SHAs.

Still **not** REAL production authority:
- historical SKU artwork = BLOCKED / pending;
- current calibration artwork = FIXTURE;
- board/back/door thickness = ESTIMATED;
- door gap / safe / bleed = CONFIG;
- hardware / joinery / hole positions / articulation = UNKNOWN or BLOCKED;
- `engineeringReady=false`, `manufacturingReady=false`, `productionReady=false`;
- LIVE_CNC / LIVE_LASER / PLC remain BLOCKED.

Do not promote any of the above because Blender output looks correct.

## 1. Branch / PR dependency rule

PR #7 may still be open when this instruction is read.

- **Do not auto-merge PR #7.**
- If `main` does not yet contain the Issue #4 Golden Product files, do **not** duplicate or copy those files into the Issue #6 branch.
- Build Issue #6 against the generic Product Truth / render-pack interfaces already on `main`.
- Use an existing REAL Product Truth fixture/product for the first end-to-end acceptance when needed.
- After PR #7 is merged, add Golden Product integration by adapter/interface only; do not fork a second Golden Product implementation.

## 2. VideoRecipe V1

Add a provider-neutral `VideoRecipe` model and deterministic hash.

V1 must support at least:
- `HERO_ORBIT_8S`
- `DOOR_OPEN_8S`

Schema fields must include:
- recipe id/version;
- duration seconds;
- fps;
- width/height;
- frame count;
- camera path / keyframes;
- lens / sensor / lookAt target;
- product transform timeline;
- articulation timeline;
- scene / lighting recipe identity;
- Product Truth / Engineering / Artwork lineage;
- deterministic `videoRecipeHash`.

Optional future recipes may be declared but must remain explicit PARTIAL/BLOCKED until implemented:
- `ARTWORK_DETAIL_6S`
- `SMALL_ROOM_10S`
- `ASSEMBLY_EXPLODE_10S`

## 3. Ground Truth frame sequence

For every accepted frame, publish deterministic artifacts / metadata for:
- RGB / Beauty;
- Depth;
- Normal;
- ProductMask;
- ArtworkMask;
- Alpha when applicable;
- camera world matrix;
- product/object transform matrix;
- articulation state;
- frame index;
- timestamp.

Every frame must bind to:
- tenant / SKU / product version;
- EngineeringHash;
- Product Truth identity / acceptance generation;
- ArtworkHash / ArtworkVersion when present;
- PlacementHash / finalUvHash when present;
- SceneRecipeHash;
- CameraRecipeHash;
- VideoRecipeHash;
- Blender job id;
- artifact SHA-256 and byte size.

No second hidden geometry or camera source of truth is allowed in Blender scripts.

## 4. VIDEO_GROUND_TRUTH_MANIFEST.json

Create a machine-readable manifest with one row/object per frame.

Required integrity rules:
- deterministic manifest hash;
- exact frame set `0..N-1`;
- no duplicate frame indices;
- no missing frame;
- strictly increasing timestamps;
- artifact SHA / size verified from stored bytes;
- camera/product matrices finite numeric only;
- cross-SKU / cross-generation frame mixing fails closed;
- frame reorder tamper fails closed.

Do not reduce acceptance to one final MP4 SHA. The frame-level lineage is the authority.

## 5. REAL Blender acceptance scope

### HERO_ORBIT_8S
Must be REAL in this round if the local Blender runtime is available.

For acceptance, use a low-cost deterministic render profile suitable for CI-independent local evidence; schema must still support production profiles separately.

Prove:
- product geometry remains unchanged across frames;
- camera follows the declared orbit/dolly path;
- Artwork does not drift relative to printable surfaces;
- ProductMask and ArtworkMask remain bound to the same product/artwork lineage;
- output can be regenerated and independently verified from the manifest.

### DOOR_OPEN_8S
Do **not** fabricate articulation authority.

- For the 424×295×900 Golden Product, Issue #4 currently declares `articulationAuthority=UNKNOWN`; therefore its DOOR_OPEN must remain BLOCKED unless new verified articulation authority is introduced with evidence.
- A REAL DOOR_OPEN acceptance may instead use an existing product whose hinge/articulation worker evidence is already scoped REAL and authoritative.
- If no such product is used, keep `doorOpenGroundTruthReady=false` and continue; this does not block HERO_ORBIT V1 acceptance.

## 6. Provider-neutral generative gateway

Create or extend adapters without coupling core Product Truth to one model:
- `H3MaxAdapter`
- `LTX25Adapter`
- future provider interface.

Provider request package may contain:
- RGB reference frames / keyframes;
- Depth;
- Normal;
- ProductMask;
- ArtworkMask;
- camera metadata;
- style/prompt brief;
- product-lock constraints.

Current rule:
- no live credential/runtime → `liveProviderReady=false`;
- fixture/mock transport is allowed for unit tests only;
- mock H3/LTX must never be labeled REAL.

## 7. Product Lock QA V1

Implement deterministic QA contracts first.

At minimum:
- silhouette / ProductMask IoU;
- artwork region / ArtworkMask IoU;
- aspect-ratio / topology proxy;
- declared door/panel count where authority exists;
- camera-motion consistency from metadata;
- frame identity / temporal continuity sanity checks;
- artifact and lineage integrity.

Statuses:
- `PASS`
- `RETRY`
- `REJECT`

If there is no live Vision provider:
- `visionQaReady=false`;
- deterministic checks may be REAL_LOGIC;
- heuristic / fixture Vision remains MOCK and cannot promote a candidate to production authority by itself.

## 8. Candidate / retry / DAM lifecycle

Implement:

`Ground Truth -> Provider Candidate -> QA -> PASS / RETRY / REJECT -> DAM`

Persist:
- attempt number;
- provider/model;
- seed if available;
- provider request id if available;
- runtime/cost only when actually observed;
- source Ground Truth manifest hash;
- QA result and reason;
- idempotency key.

DAM classes must distinguish:
- Blender Ground Truth;
- Provider Candidate;
- QA Accepted;
- QA Rejected;
- Final Commerce Video.

A rejected candidate must fail closed if any code attempts to publish it as Final Commerce Video.

## 9. Negative regression matrix

Add explicit fail-closed tests for:
- wrong SKU;
- wrong EngineeringHash;
- wrong ArtworkHash;
- wrong PlacementHash / finalUvHash;
- frame reorder;
- missing frame;
- duplicated frame;
- cross-video / cross-SKU frame mix;
- camera matrix tamper;
- product transform tamper;
- articulation tamper;
- ProductMask tamper;
- ArtworkMask tamper;
- artifact SHA / byte-size mismatch;
- manifest hash mismatch;
- rejected candidate publish attempt;
- mock provider attempting `liveProviderReady=true`;
- mock Vision attempting `visionQaReady=true`.

## 10. Evidence / docs

Add:
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ARCHITECTURE.md`
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ACCEPTANCE.md`
- machine-readable acceptance JSON.

Truth Matrix must use explicit labels:
- REAL
- REAL_LOGIC
- FIXTURE
- MOCK
- PARTIAL
- BLOCKED

Required readiness flags include at least:
- `videoGroundTruthReady`
- `heroOrbitGroundTruthReady`
- `doorOpenGroundTruthReady`
- `liveProviderReady`
- `visionQaReady`
- `generativeVideoProductionReady`

No unscoped `productionReady=true`.

## 11. Tests / CI / clean-tree evidence

Do not run only new tests.

Required sequence:
1. full `pytest -q` locally;
2. push CODE SHA;
3. exact CODE SHA Ubuntu + Windows Actions SUCCESS;
4. from a clean tree, run REAL Blender ground-truth acceptance when Blender is available;
5. bind evidence to exact CODE SHA and `workingTreeClean=true`;
6. commit docs/evidence separately as DOCS SHA;
7. exact DOCS SHA Ubuntu + Windows Actions SUCCESS;
8. publish one machine-readable READY_FOR_RE_GATE handoff;
9. STOP for external Re-Gate.

`FOX3D_MOCK_BLENDER=1` CI remains unit/regression evidence only, not REAL Blender evidence.

## 12. READY_FOR_RE_GATE contract

Report in Issue #6 and a short pointer in Issue #1:

- `INSTRUCTION_SHA`
- `CODE_SHA`
- `DOCS_SHA`
- `CODE_CI_RUN_ID`
- `DOCS_CI_RUN_ID`
- `TEST_COUNT`
- `EVIDENCE_GENERATION_ID`
- `REAL_BLENDER=true|false`
- `USED_MOCK=true|false`
- `VIDEO_GROUND_TRUTH_READY=true|false`
- `HERO_ORBIT_GROUND_TRUTH_READY=true|false`
- `DOOR_OPEN_GROUND_TRUTH_READY=true|false`
- `LIVE_PROVIDER_READY=true|false`
- `VISION_QA_READY=true|false`
- `GENERATIVE_VIDEO_PRODUCTION_READY=true|false`

List REAL / REAL_LOGIC / FIXTURE / MOCK / PARTIAL / BLOCKED separately.

## 13. Supervisor LIVE E2E remains on hold

The existing Event-Driven Supervisor production gate is still externally blocked:
- public HTTPS webhook ingress missing;
- webhook secret missing;
- live provider credential/model config missing;
- admin key missing.

Until those prerequisites actually change:
- keep `webhookRealE2e=false`;
- keep `liveProviderReady=false` for Supervisor live chain;
- keep `eventDrivenSupervisorReady=false`;
- do not create repetitive docs-only BLOCKED commits/comments;
- do not substitute curl synthetic webhook / MockTransport for real GitHub delivery.

## 14. Forbidden

- no architecture rewrite;
- no duplicate Golden Product implementation while PR #7 is unmerged;
- no fabricated historical artwork;
- no fabricated articulation/hardware/manufacturing authority;
- no Mock → REAL promotion;
- no LIVE_CNC / LIVE_LASER / PLC;
- no generative video as Product Truth;
- no automatic merge of PR #7;
- no next major phase after Issue #6 completion until Re-Gate.
