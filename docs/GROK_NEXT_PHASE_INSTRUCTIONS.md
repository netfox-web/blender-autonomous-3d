# Development Agent 指令：Issue #6 Round 3B — DOOR_OPEN_8S Authority Integration Gate / REAL Blender Ground Truth

> Supervisor checkpoint: 2026-09-15
> Current main before this instruction: `4fb4f14a36e505255479397b905d18de13e1da8a`
> Reviewed prerequisite PR: #14 `codex/articulation-authority-v1` — OPEN / unmerged
> Accepted prerequisite CODE: `791bf084caa05ad6369ebd1422f0a400e533f44c`
> Accepted prerequisite DOCS: `40e6dd3c27beda0df6aaaaf80041685a813d553c`
> PR #14 decision: **ACCEPT WITH SCOPE / NO MERGE AUTHORIZATION**
> Existing video PR: #13 `codex/video-ground-truth` — OPEN / unmerged / DOOR_OPEN HOLD
> Global Production Ready: **false**

## 0. Supervisor decision

Round 3A is accepted within its exact authority-only scope.

Independent review confirms:

- CODE `791bf084caa05ad6369ebd1422f0a400e533f44c` has exact Ubuntu + Windows GitHub Actions SUCCESS in run `34917002099`.
- DOCS `40e6dd3c27beda0df6aaaaf80041685a813d553c` has exact Ubuntu + Windows GitHub Actions SUCCESS in run `34918715339`.
- Clean exact-CODE authority acceptance `4173c17c-479d-404f-b69a-841ebfa7f2db` reports a clean tree and 18 adversarial authority probes.
- `src/fox3d/articulation_authority.py` is additive and fail-closed: strict schema, deterministic seal, exact pinned resolver, component/product identity binding, transform verification, revision/hash invalidation and cache identity binding.
- Legacy `build_articulated_state()` / Blender helper output remains explicitly DERIVED_RENDER_STATE / OBSERVATION and cannot be promoted to engineering authority.
- The four-door Round 2 source is explicitly authored as `FIXTURE_AUTHORITY`, canonical OPEN 60°, and explicitly states it is not measured/CAD-certified physical hardware truth.

Truth boundary for Round 3A:

- **REAL:** no new physical articulation or Blender render is claimed.
- **REAL_LOGIC:** authority schema/seal/verifier/resolver/product+cache identity/fail-closed behavior.
- **FIXTURE_AUTHORITY:** explicit synthetic four-door motion only.
- **MOCK:** CI Blender path remains regression-only evidence.
- **PARTIAL:** approval/provenance remains a trusted reviewed engineering input; SHA-256 proves integrity, not engineering approval; legacy OPEN convenience path is not migrated.
- **BLOCKED:** physical articulation truth, DOOR_OPEN render ground truth, assembly/exploded authority, live H3/LTX/Vision/provider, Final Commerce Video, machines, Supervisor LIVE and global/full-autonomous readiness.

This acceptance **does not authorize merging PR #14**. It also does not allow PR #13 to copy/cherry-pick the prerequisite while PR #14 is absent from `main`.

## 1. Mandatory prerequisite gate — do not code around it

Before any Round 3B implementation or render:

1. fetch exact current `main`;
2. prove that the accepted Round 3A authority implementation is actually present on current `main` through an authorized repository integration;
3. at minimum verify current-main contains the accepted ArticulationSpec/resolver contract and the exact synthetic fixture authority/binding semantics reviewed in PR #14;
4. record the current-main SHA that contains that prerequisite.

If PR #14 / equivalent accepted authority source is **not present on current main**:

- do not modify PR #13;
- do not copy/cherry-pick PR #14 files into PR #13;
- do not render DOOR_OPEN;
- do not manufacture a replacement authority;
- report `BLOCKED_PR14_NOT_ON_MAIN` to Issue #1 with current-main SHA and STOP.

An instruction commit on main is not the prerequisite itself. The authority implementation must be present on main.

## 2. Once prerequisite is present — resume existing PR #13 only

After Section 1 passes, continue the existing PR #13 lane. Do not open another stacked video PR.

Bring the then-current `main` into PR #13 using normal Git ancestry integration so the accepted authority source is consumed from main. Do not manually duplicate the authority module or fixture records. Preserve Round 2 history/evidence as historical evidence; Round 3B must produce a new exact CODE SHA and new evidence.

Do not rewrite Scheduler, Queue, DAM, Product Truth, Artwork Placement, Render Pack, Product Content Factory, geometry interpretation, or the accepted Round 2 video architecture.

## 3. DOOR_OPEN_8S must consume exact engineering authority

Integrate the existing video ground-truth path with `resolve_articulation_authority(...)` / accepted equivalent from current main.

The DOOR_OPEN source/authority/manifest/cache lineage must bind at least:

- tenant/product/SKU/version/engineering identity;
- `articulationAuthorityHash`;
- `productAuthorityHash`;
- `authorityRevision`;
- `authorityKind`;
- exact moving component/object IDs;
- parent identities;
- VideoRecipe identity/hash;
- artwork/source identity already required by Round 2;
- render/cache identity;
- DAM/job lineage.

Fail closed before Blender execution when authority is missing, stale, ambiguous, cross-product, cross-tenant, hash-mismatched, revision-mismatched or component-incompatible.

Absolutely forbidden as authority:

- legacy/default 75°;
- dimension-derived hinge guesses;
- worker-observed transform;
- mesh inference;
- Vision inference;
- provider-generated motion;
- a caller-supplied `ready=true` flag.

## 4. Video trajectory is derivative animation, not physical dynamics

For the accepted synthetic fixture, engineering authority provides the closed pose, pivot/axis/range and canonical 60° OPEN endpoint.

The video recipe may define a deterministic interpolation from CLOSED to canonical OPEN for presentation. That interpolation/easing is **VideoRecipe derivative animation**, not measured hinge speed, torque, acceleration or physical dynamics.

Requirements:

- every frame angle must remain inside the exact resolved authority range;
- first frame must match authoritative CLOSED transform;
- final OPEN frame must match authoritative canonical OPEN transform;
- interpolation semantics must be deterministic and hashed in VideoRecipe;
- no frame may consult the legacy 75° helper as an authority source;
- per-frame expected transform must be derived from the resolved authority and recipe interpolation, then independently compared with Blender-observed component transforms.

If exact component mapping into the Blender scene cannot be proven, stop with `BLOCKED_DOOR_OPEN_COMPONENT_MAPPING`; do not guess object names or pivots.

## 5. Clean REAL Blender acceptance — scoped synthetic ground truth

After exact CODE dual-CI SUCCESS, run one clean-tree REAL Blender 5.2.1 LTS / OptiX DOOR_OPEN_8S acceptance on the accepted synthetic Round 2 product.

Target scope unless an existing canonical recipe already specifies stricter values:

- 8 seconds;
- 12 fps;
- 96 frames;
- same technical control resolution convention as accepted Round 2 unless intentionally versioned in the recipe;
- RGB plus existing required control passes (Depth, Normal, ProductMask, ArtworkMask and any articulation/component observations required by the verifier);
- deterministic matrices/optics/light/scene lineage;
- exact authority + recipe + source hashes in manifest/DAM lineage.

Evidence must include:

- `workingTreeClean=true` at exact CODE;
- Blender version/device and `usedMock=false`;
- artifact SHA/bytes for all required outputs;
- first/middle/final BLEND reopen or equivalent accepted checkpoint reopen;
- first/middle/final door component transforms observed from the saved scene and matched against authority-derived expectations;
- final frame canonical 60° OPEN for the exact FIXTURE_AUTHORITY source;
- process restart/persisted reload checks;
- stale authority revision/hash blocks old cache/download/publication;
- no new candidate/DAM output on fail-closed authority tests.

Do not substitute CI Mock Blender, copied candidate pixels or old Round 2 HERO/DETAIL/ROOM evidence for this new DOOR_OPEN REAL render run.

## 6. Truth labels after successful Round 3B

If Section 5 succeeds, use precise scoped labels:

### REAL_RENDER

- actual clean Blender/OptiX DOOR_OPEN_8S frames and saved-scene observations.

### REAL_LOGIC

- exact ArticulationSpec resolution;
- authority-to-video identity binding;
- deterministic trajectory semantics;
- per-frame transform verification;
- cache/DAM/restart/tamper guards.

### FIXTURE_AUTHORITY

- the synthetic four-door engineering motion source, including canonical 60° OPEN.

### PARTIAL

- the sequence is technical/synthetic reference ground truth, not measured company hardware;
- VideoRecipe timing/easing is presentation motion, not physical dynamics;
- no measured hinge clearance/collision/lifetime validation;
- deterministic QA is not semantic Vision unless separately proven.

### BLOCKED

Remain blocked:

- physical/company articulation truth;
- arbitrary real-product DOOR_OPEN without measured/CAD/approved authority;
- authoritative assembly/exploded motion unless separately sourced;
- live H3/LTX/Vision/provider;
- Final Commerce Video production approval;
- calibrated physical UV/RIP/print;
- hot-folder/LIVE_CNC/LIVE_LASER/PLC/machine control;
- Supervisor LIVE prerequisites;
- `globalProductionReady`;
- `fullAutonomousFactoryReady`.

If the legacy boolean `DOOR_OPEN_REAL` is retained, it may only mean **REAL Blender render for this exact FIXTURE_AUTHORITY scope** and must be accompanied by `physicalArticulationTruth=false`. Never expose it as a global production claim.

## 7. Required negative/regression tests

Add focused tests without weakening existing suites. At minimum:

- missing authority/binding blocks before render;
- PR14 authority absent from main gate blocks work;
- stale revision/hash blocks;
- cross-tenant/product/SKU/version/engineering substitution blocks;
- wrong component/object/parent mapping blocks;
- legacy 75° path cannot satisfy authority;
- worker observation cannot become authority;
- tampered pivot/axis/range/open transform blocks;
- mutated authority changes cache/video identity;
- cached outputs under old authority cannot publish/download as current;
- first/final transform contradiction blocks;
- trajectory angle outside authorized range blocks;
- authorityKind remains `FIXTURE_AUTHORITY` end-to-end and cannot be relabeled as physical truth.

Run focused tests and the full local regression suite.

## 8. CODE / REAL / DOCS gate order

Strict order:

1. prerequisite present on current main;
2. integrate current main into existing PR #13;
3. implement minimal Round 3B bridge;
4. focused tests + full local regression;
5. freeze final CODE SHA;
6. exact CODE SHA Ubuntu + Windows CI SUCCESS;
7. clean exact-CODE REAL Blender DOOR_OPEN acceptance with `usedMock=false`;
8. inspect representative frames/checkpoints;
9. commit DOCS/evidence separately;
10. exact DOCS SHA Ubuntu + Windows CI SUCCESS;
11. post `READY_FOR_RE_GATE` and STOP.

CI with `FOX3D_MOCK_BLENDER=1` remains regression evidence only.

## 9. Documentation

Update only relevant truth/evidence docs. Prefer additive Round 3B evidence such as:

- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ROUND3_ACCEPTANCE.md`
- `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ROUND3_ACCEPTANCE.json`
- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`

Update `docs/REAL_E2E_ACCEPTANCE.md` only if a new narrowly scoped REAL-render readiness fact genuinely changes. Do not modify `docs/CABINET_REAL_ACCEPTANCE.md` unless cabinet engineering truth itself changes.

Do not erase historical Round 2 or Round 3A truth boundaries.

## 10. Handoff contract / STOP

Final Issue #1 handoff must include at least:

- prerequisite current-main SHA containing Round 3A authority;
- PR #13;
- Round 3B CODE SHA;
- Round 3B DOCS SHA;
- CODE CI run ID and exact Ubuntu/Windows conclusions;
- DOCS CI run ID and exact Ubuntu/Windows conclusions;
- clean REAL evidence generation ID;
- Blender version/device / `usedMock=false`;
- exact `articulationAuthorityHash`, `productAuthorityHash`, revision and kind;
- frame/artifact counts;
- representative reopen/transform verification results;
- `physicalArticulationTruth=false` for FIXTURE authority;
- live provider/Vision/physical/global flags;
- `MERGE_AUTHORIZED=false` unless a separate explicit merge authorization exists.

If any required gate fails, report the exact BLOCKED/CHANGES_REQUIRED reason and STOP. Do not substitute Mock/FIXTURE evidence for Production Ready.
