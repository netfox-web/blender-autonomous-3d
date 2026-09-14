# NAS Product Model Library V1 — Scoped Acceptance

The Chinese UI at `/admin/recipes/models` makes the user-selected seven-family NAS inventory reviewable and editable by operators. Physical model dimensions, source evidence, artwork SKUs and print-face notes are separate. A file named 65×45 never becomes product dimensions.

## CODE and clean REAL acceptance

- CODE: `a4eb1d6b7b505e06a246ec5925bc35a66bbe3255`.
- Exact CODE CI: [34841773014](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34841773014); Ubuntu + Windows SUCCESS, **893 passing tests each** (pass markers counted from both completed logs).
- Focused local regression: **66 PASS**, including 23 new cases. A redundant full local run was stopped; it is not claimed as passing evidence. Full regression evidence is the exact-head dual-OS CI.
- Clean evidence: `196a5e3a-311d-4846-8e95-793e22ce2c2c`; workingTreeClean=true, developmentOnly=false, status=PASS.
- Command: `python scripts/run_product_models_e2e.py` at exact CODE, after both CI jobs succeeded.
- Real Blender **5.2.1 LTS**, OptiX, 32 samples, 800×800; three geometries: OPEN_CABINET (7 components), HINGED_CABINET (10), RECTANGLE (1).
- Each PNG/BLEND/GLB/geometry output was validated. Each saved `.blend` was reopened by real Blender and every component size/location matched the manifest. All artifact SHA-256 and byte sizes are in the JSON evidence.
- Actual loopback HTTP exercised create/save/import/generate/download, changed dimensions, stale-download rejection and server restart persistence. Fixture originals were byte-identical after the run.

This document is the separate DOCS phase. Its exact DOCS SHA and dual-OS CI result are recorded in the final Issue #1 handoff after that commit; CODE CI is not substituted for DOCS CI.

## Truth boundary

| Class | Evidence and limitation |
|---|---|
| REAL | Actual HTTP and real Blender generation/reopen for three synthetic regular geometries. Local NAS index, original import and image preview were also exercised; originals stay local. |
| REAL_LOGIC | Revision checks, immutable model history, source-root containment, tenant artwork isolation, explicit dimensions/evidence, stale model download rejection, JSON-safe EXIF rational DPI without changing original bytes. |
| FIXTURE | Formal geometry dimensions, SKU names and artwork are synthetic. They do not validate company product measurements. |
| MOCK | CI Blender and isolated failure fixtures are regression checks, not physical or live provider acceptance. |
| PARTIAL | 21,766 files / 447 candidate groups and seven manually curated NAS reference masters. All seven still have structural gaps; zero NAS product models are claimed complete by this scope. Source images support some exterior dimensions, not calibration. |
| BLOCKED / false | Curved bottles, rounded/special outlines, drawers, box lids, curtain slits/drape and authoritative joints until the required recipe/data exists. Print-face notes do not drive output or apply artwork to the new models. No calibrated UV/RIP export, scene-generation integration or physical print acceptance. |

The seven families are coasters, mats, cabinets, curtains, mask boxes, 50-pack boxes and spray bottles. Wood subtype choices are hinged, open, bedside and bookcase; classification suggestions remain unverified. Native CAD/3D reconstruction of all NAS products has not been completed.

## Operator and integration checks

Browser checks confirmed draft save with missing dimensions, no sticker-size autofill, stale model notice, real preview generation with download links and zero observed JavaScript console errors. The real local NAS mat reference image successfully imported and loaded in the UI. Both existing print jobs remained readable after the service update.

The NAS scanner uses explicitly configured source roots, skips links/reparse points, limits inventory size, publishes complete snapshots atomically and refuses stale IDs when source configuration changes. Operators can inspect supported original artwork; unsupported native formats remain indexed without executing Illustrator or original scripts. JPEG/TIFF rational EXIF DPI import has a regression test and does not establish physical size authority.

PR #10 is stacked on #9. No automatic merge, NAS original overwrite, licensed artwork upload, PrintFox credential access, Linux production mutation, provider generation, hot-folder write or physical machine command is part of this change. `physicalPrintValidated=false`, `globalProductionReady=false`.

Supervisor instruction `bab3a1a2b4631e0c6f40c5c93e33441a72c74dd0` accepts PR #9 WITH SCOPE and keeps Issue #6 queued independently from current main. This NAS work does not implement Issue #6 or change its unmerged-dependency boundary.
