# Sonaqueen Recipe Library — Supplier Reference Acceptance

CODE commit: `21615a0d2bcf0748814a0c74048e7828590d5be0`
Acceptance generation: `e1abdc35-c80e-4b29-b10c-53b0b1c40928`
Generated: `2026-09-13T05:35:31.196919+00:00`

## Validated scope

- Three SKU references, three mother-recipe descriptions, ten source snapshots.
- Full local pytest: **670 passed**, one dependency deprecation warning, 666.15 seconds.
- New focused tests: **42 passed** (FIXTURE/unit evidence, not REAL model evidence).
- Exact CODE CI: [34739838555](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34739838555) — **Ubuntu + Windows SUCCESS**.
- Clean working tree at exact CODE SHA during live HTTP acceptance.
- Seven supplier images matched snapshot bytes/SHA-256 exactly.
- Three live dynamic pages matched SKU/name; full HTML equality is deliberately not claimed.
- All ten live responses had the expected URL and MIME.
- Three EXPERIMENTAL PRODUCT_REFERENCE recipes imported through existing RecipeRegistry.

| CI job | Job ID | Result |
|---|---|---|
| unit (windows-latest) | `103677560441` | SUCCESS |
| unit (ubuntu-latest) | `103677560672` | SUCCESS |

## Limits and remaining work

This is LIVE_HTTP source verification, not REAL Blender acceptance. Supplier labels were transcribed from reference images and remain supplier claims/approximate dimensions. File integrity does not certify physical measurements.

The mother recipes are structure descriptions, not executable geometry adapters. Exact row dividers, stacked door hinges and sliding tracks still require engineering implementation and validation. Unknown board/door/back thicknesses and hardware details remain explicit blockers.

`engineeringReady=false`, `renderReady=false`, `productionReady=false`, `realBlenderAcceptance=false`, `commercialAssetProductionReady=false`, `globalProductionReady=false`.

No exact 3D model or commerce render for these three SKUs was produced. Phase 901–960 correction/Re-Gate and Phase 961+ HOLD remain separate and unchanged.

Documentation CI is run after the separate documentation commit; its exact SHA and run/job IDs are reported in PR #2 and Issue #1 to avoid a self-referential commit hash.

See [usage and data gaps](SONAQUEEN_RECIPE_LIBRARY.md) and [machine-readable evidence](SONAQUEEN_RECIPE_LIBRARY_ACCEPTANCE.json).
