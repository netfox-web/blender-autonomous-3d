# Development Agent 下一輪開發指令：Phase 901–960 — Product Content Factory V1 / Deterministic Commerce Asset Pack

> Repo: `netfox-web/blender-autonomous-3d`  
> Legacy filename kept for watcher compatibility: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`  
> Reviewed CODE: `cb045af68de6f64f8ba8196ae88382e2210b9dc0`  
> Reviewed docs/head: `f5eddc194ef80b243323a20b87b48f8c43fa3593`  
> Acceptance generation: `78ef13b7-180f-43a3-94f9-15a9b3ad9f1f`  
> CODE Actions: `34712862358` — Ubuntu `103604685753` SUCCESS + Windows `103604685849` SUCCESS  
> docs/head Actions: `34713775560` — Ubuntu `103607125020` SUCCESS + Windows `103607125136` SUCCESS  
> Full pytest: **621 passed**  
> Re-Gate result: **ACCEPT WITH SCOPE — Phase 841–900 CLOSED; Phase 901–960 GO.**

## 0. Scope / fixed truth boundaries

Build on the accepted Product Truth / Artwork / DAM / Queue / Recipe / TwinStore / CabinetSpec architecture. **Do not rewrite those systems.** Do not create a second millimetre, UV, geometry, camera, scene, product identity, or Product Truth source of truth.

Phase 841–900 is accepted only in its scoped meaning:

- Product Truth Blender execution / AOV pack / worker provenance: **REAL / REAL_LOGIC**.
- ProductMask and FRONT PrintableSurface ArtworkMask: **REAL artifacts**, distinct and independently bound.
- Camera/Scene/View frozen authority + fail-closed re-hash: **REAL_LOGIC**.
- Generative Gateway contract: **REAL_LOGIC**.
- live H3 MAX / LTX 2.5: **BLOCKED** until a real provider is connected and evidenced.
- Vision Judge: **MOCK / BLOCKED**.
- physical print: **BLOCKED / false**.
- LIVE_CNC / LIVE_LASER / PLC / live factory execution: **BLOCKED**.
- `globalProductionReady=false`, `fullAutonomousFactoryReady=false`, `liveFactoryExecutionReady=false`.

Mock/FIXTURE/heuristic evidence is never Production Ready. Generative output is never allowed to become Product Truth.

## 1. Goal

Turn one accepted Product Truth / Digital Twin into a deterministic, reusable **commerce content pack** for e-commerce and storefront use while preserving exact product identity and evidence lineage.

The phase should produce a canonical asset manifest for one SKU/version that can contain deterministic Blender product images, dimension assets, product-state views, and provider-neutral lifestyle/generative requests without changing Engineering/Product Truth authority.

Preferred implementation: extend existing `product_truth.py`, `media.py`, `studio.py`, `scene.py`, `commerce.py`, `generative_gateway.py`, DAM and publish helpers where natural. A small focused `content_factory.py` is acceptable if it avoids duplicating existing authorities.

## 2. Canonical Content Pack model / lineage

Create a canonical content-pack record/manifest (name may be `ProductContentPack`, `CommerceAssetPack`, etc.) whose authority is **derived** from accepted upstream Product Truth.

Required identity/provenance fields at minimum:

- `tenantId`
- `skuId` / product identity and product version
- canonical `engineeringHash`
- artwork identity when applicable: placement/relation/final UV hashes
- source Product Truth `renderPackId` / acceptance generation
- source Product Truth artifact hashes needed to prove the product body/artwork identity
- source Camera/Scene/View recipe hashes where relevant
- content-pack recipe/preset hash
- each output asset DAM ref, role, path, SHA-256, size, MIME, pixel dimensions
- Blender job / worker provenance for REAL Blender outputs
- truth label for each asset: REAL / REAL_LOGIC / FIXTURE / MOCK / BLOCKED

Fail closed on cross-tenant, wrong SKU/version, stale engineering hash, wrong source generation, duplicate/missing required roles, foreign DAM refs, or conflicting lineage.

The content pack must not copy dimensions or geometry from pixels. It must use the same Engineering/Product Truth SOT already accepted.

## 3. Deterministic Blender commerce views

Implement a fixed required view set for one canonical cabinet SKU. At least these roles must exist:

1. `WHITE_BACKGROUND_HERO` — clean catalog hero.
2. `HERO_45` — deterministic 3/4 hero.
3. `FRONT_CLOSED` — front closed state.
4. `FRONT_OPEN` — real articulated open state driven from engineering components / product state, not a fake 2D composite.
5. `DETAIL_ARTWORK` or `DETAIL_DOOR` — detail bound to Product Truth artwork/front surface when applicable.
6. `DIMENSION_FRONT` — front dimension image/overlay derived from Engineering mm.

Optional but recommended if existing infrastructure makes it cheap: `DIMENSION_3Q`, `EXPLODED`, `ASSEMBLY_STEP`, transparent/alpha catalog asset.

For every required REAL Blender output capture and verify:

- exact view role / recipe hash
- resolution / aspect ratio / safe margin
- source Engineering/Product Truth hashes
- `blenderJobId`
- worker identity/device evidence
- DAM stored bytes + SHA + size + dimensions
- `usedMock=false` in REAL acceptance

Required views are an exact set for acceptance: missing, duplicated, or swapped roles must fail.

## 4. Content View Recipe / preset contract

Add a deterministic content view/preset contract that binds:

- view role
- CameraRecipe hash
- SceneRecipe hash
- product state (`CLOSED`, `OPEN`, `EXPLODED` where applicable)
- studio/background preset
- output width/height/aspect ratio
- safe margin / framing policy
- artwork visibility requirement if applicable

Use stable hashing and strict schema. Missing fields, bool-as-number, string numbers, NaN/Inf, stale hashes, cross-view swaps, or unrecognized product states fail closed.

Support common presentation presets such as 1:1, 4:5 and 16:9 by recipe/config, but do not duplicate product geometry or invent alternate camera truth.

## 5. Dimension asset authority

`DIMENSION_FRONT` (and any optional dimension views) must obtain dimension labels from `CabinetSpec` / Engineering JSON only.

Requirements:

- width / height / depth values must be exact upstream Engineering values.
- rendered/overlay label payload must be independently checked against Engineering before publication.
- no computer-vision/pixel inference may become dimension authority.
- stale or tampered dimension text/metadata must reject the content pack.
- add negative tests for swapped width/height, changed units/value, stale engineeringHash, and coordinated asset+metadata tampering.

## 6. Lifestyle / generative handoff, without fake readiness

Add structured lifestyle scene briefs/presets for at least:

- `CHILD_ROOM`
- `STUDENT_RENTAL`
- `ENTRYWAY`
- `SMALL_APARTMENT`

Each brief must bind the accepted Product Truth identity, ProductMask/ArtworkMask refs where applicable, allowed context/background changes, framing intent, and forbidden product edits.

Route through the existing provider-neutral `generative_gateway.py` contract. Do **not** fake live H3 MAX / LTX 2.5 execution.

If no live provider is configured:

- provider request/contract may be REAL_LOGIC;
- generated-provider output remains BLOCKED/MOCK as appropriate;
- `liveH3MaxProviderReady=false`, `liveLtx25ProviderReady=false`;
- no generated lifestyle asset may be labeled approved Product Truth or Production Ready.

Generative output must retain source Product Truth / engineering / artwork hashes and be treated as a derivative asset only.

## 7. Commerce QA gate

Add a deterministic QA gate before a content asset can enter the final commerce manifest.

At minimum verify what can be proven without a live vision model:

- source Product Truth identity and engineering hash match
- expected ProductMask / ArtworkMask lineage where applicable
- required view role and recipe hash match
- asset dimensions/aspect ratio/safe-frame constraints
- product-state evidence for OPEN vs CLOSED (bind explicit articulated state / component transforms; do not rely only on a screenshot)
- DAM bytes/SHA/path/job/source lineage

Vision Judge remains MOCK/BLOCKED. Therefore deterministic QA may produce scoped `APPROVED_FOR_ASSET_REVIEW`, but must not imply `commercialAssetProductionReady=true` or global Production Ready.

On unknown/failed QA use `REVIEW_REQUIRED` / `BLOCKED`, never silent PASS.

## 8. DAM roles and exact manifest binding

Use the existing DAM; do not build a second asset store.

Add/standardize content roles as needed, for example:

- `COMMERCE_HERO`
- `COMMERCE_HERO_45`
- `COMMERCE_FRONT_CLOSED`
- `COMMERCE_FRONT_OPEN`
- `COMMERCE_DETAIL_ARTWORK`
- `COMMERCE_DIMENSION`
- `COMMERCE_LIFESTYLE_BRIEF`

Manifest verification must fail closed for:

- foreign tenant/SKU/version
- wrong view role
- wrong DAM object/path
- wrong source `blenderJobId`
- wrong bytes/SHA/size/dimensions
- duplicated required role
- cross-view asset swap
- source Product Truth generation mismatch
- stale content-view recipe hash

## 9. Runner / acceptance

Add a canonical runner, preferably `scripts/run_product_content_e2e.py`, that exercises the official publication path and publishes acceptance only after all required deterministic gates pass.

Create:

- `docs/PRODUCT_CONTENT_FACTORY_ACCEPTANCE.md`
- `docs/PRODUCT_CONTENT_FACTORY_ACCEPTANCE.json`

Update only the necessary existing evidence docs:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`

Leave `docs/CABINET_REAL_ACCEPTANCE.md` unchanged unless cabinet truth itself genuinely changes.

Required readiness fields must stay scoped, for example:

- `productContentFactoryLogicReady`
- `realCommerceRenderPackReady`
- `liveGenerativeCommerceReady`
- `commercialAssetProductionReady`

`realCommerceRenderPackReady=true` requires fresh REAL Blender evidence. `liveGenerativeCommerceReady` stays false without a real provider. `commercialAssetProductionReady` must remain false unless its stronger real-world gates are actually evidenced.

## 10. Required adversarial / regression tests

Add tests that execute through the official content runner/publication path, not only isolated helpers. At minimum prove fail-closed behavior for:

1. wrong tenant;
2. wrong SKU/product version;
3. stale/wrong `engineeringHash`;
4. wrong Product Truth generation/renderPack identity;
5. required view missing;
6. required view duplicated;
7. HERO and OPEN DAM refs swapped;
8. wrong view recipe hash;
9. wrong Blender job ID/source path;
10. bytes/SHA/size mismatch;
11. dimension width/height/depth or units tampered;
12. dimension metadata + rendered label metadata coordinated tamper;
13. `FRONT_OPEN` manifest points to a CLOSED articulated-state record;
14. ProductMask/ArtworkMask lineage cross-swap;
15. derivative generative asset attempts to claim Product Truth authority;
16. blocked/mock provider attempts to set live/commercial readiness true;
17. malformed strict recipe values (bool/string/NaN/Inf);
18. cross-tenant/cross-SKU DAM asset substitution with otherwise valid bytes.

Do not weaken any Phase 841–900 authority/tamper tests.

## 11. Evidence / CI process

Follow `AGENTS.md` two-phase execution exactly:

1. Implement CODE + tests only.
2. Run full `pytest -q`; report exact count and keep MOCK/FIXTURE labels honest.
3. Commit/push exact CODE SHA.
4. Wait for GitHub Actions Ubuntu + Windows **SUCCESS on that exact CODE SHA**; record run ID and job IDs.
5. On a clean tree at exact CODE SHA, run fresh REAL Blender 5.2.1 LTS + NVIDIA T1000 OptiX content acceptance for one canonical cabinet SKU with `usedMock=false`.
6. Required deterministic commerce views must have real DAM bytes, per-asset SHA/size/dimensions/job/device evidence.
7. Generative/lifestyle provider results remain BLOCKED/MOCK unless an actual live provider was used; do not fabricate them to make acceptance green.
8. Commit docs/evidence separately; push.
9. Wait for exact docs/head Ubuntu + Windows SUCCESS; record run/job IDs.
10. Update Issue #1 with instruction SHA, CODE SHA, docs SHA, pytest count, CODE/docs CI, fresh acceptance generation, and REAL/MOCK/PARTIAL/BLOCKED summary.
11. STOP for ChatGPT Re-Gate. **Do not start Phase 961+.**

## 12. Definition of Done — Phase 901–960

All must be true before asking for Re-Gate:

- Phase 841–900 Product Truth protections remain green and unchanged in authority semantics;
- canonical content-pack lineage derives from accepted Product Truth/Engineering, with no duplicate geometry/mm/UV SOT;
- required deterministic commerce view set is complete and exact;
- OPEN/CLOSED state is bound to explicit product-state evidence;
- dimension assets are provably driven from Engineering mm and tampering fails closed;
- DAM manifest exact-set/source/job/SHA/path/tenant/SKU binding is enforced;
- lifestyle briefs are structured and Product Truth-bound;
- H3/LTX stay BLOCKED unless actually live; Vision stays MOCK/BLOCKED unless actually live;
- derivative generative assets cannot become Product Truth;
- official-runner adversarial matrix passes;
- full pytest passes;
- exact CODE SHA Ubuntu + Windows CI succeeds;
- fresh clean-tree REAL T1000 OptiX commerce render acceptance succeeds with `usedMock=false`;
- docs/head exact SHA Ubuntu + Windows CI succeeds;
- `physicalPrintValidated=false`, LIVE_CNC/LASER/PLC remain BLOCKED, global/full/live factory readiness remain false unless new independent REAL evidence exists;
- Phase 961+ remains HOLD until ChatGPT explicitly releases it.
