# Product variant batches — static preview acceptance

Explicit user request, 2026-09-16: reuse 3D product masters for multiple artwork and scene variants, with an operator UI. This is separate from Issue #6 Round 3B. No synthetic instruction commit or source Issue identity is assigned.

## Delivered behavior

The model workbench now has a reviewed batch list (up to 24 variants), per-row progress/cancellation and a paginated retained-results gallery. It supports the existing master adapters, including cabinets and flat products. Operators select each surface artwork, page and rotation, add the selection to one or more of the three existing background presets, then submit the batch. All selections are preflighted before enqueueing, and each row rechecks current master identity and artwork classification before rendering.

Single renders and batches share the same serial composition queue. Failures and cancellation preserve completed results. Service interruption does not automatically replay work or label incomplete rows successful. Historical downloads independently validate generation/master identity, artifact integrity and current artwork permission; changed geometry or revoked artwork disables downloads. New output publication is sealed only after final source/cancellation checks. Existing older valid composition results remain accessible.

## Exact CODE gate

- CODE: `2a43d9b51001176164bd534f51b63debf3f391cd`
- [CODE CI 35044283265](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35044283265): Ubuntu job 104630648838 and Windows job 104630648705 both SUCCESS; 939 passed markers each, reaching 100%. MOCK regression only.
- Clean-CODE REAL generation: `34fbd5bf-a46d-4914-8d08-cf86e36b83bb`
- Six outputs: two artwork patterns × two backgrounds on a synthetic static three-door cabinet; two patterns on a synthetic flat panel.
- All six use REAL Blender 5.2.1 LTS + OptiX, `usedMock=false`, distinct beauty image hashes, constant geometry within each model, complete artifact hashes/sizes and successful `.blend` reopen.
- Actual HTTP acceptance checks: simultaneous single/batch submission rejection; historical downloads including non-latest results; retained results after process restart; all variants blocked after geometry changes; restoration of identical geometry; selective blocking after artwork revocation; cross-tenant denial.
- Browser UI smoke checks: existing category tree and 4-preview/17-draft inventory preserved; one selection added to two backgrounds; duplicate rejection; pending geometry disabled; switching masters preserves unsent lists; clear list; three existing historical results visible; no console errors.

Machine-readable evidence: [PRODUCT_VARIANT_BATCH_ACCEPTANCE.json](PRODUCT_VARIANT_BATCH_ACCEPTANCE.json). Raw local evidence is in `.fox3d-work/batches/34fbd5bf`; user data and NAS originals were not used as synthetic test fixtures.

## DOCS gate and delivery

This document is committed only after exact CODE dual-platform CI and clean REAL acceptance. The exact DOCS SHA and its Ubuntu/Windows run are recorded in the final Issue #1 handoff after they pass; they are not invented or circularly embedded here. [PR #15](https://github.com/netfox-web/blender-autonomous-3d/pull/15) targets `codex/model-category-tree` and explicitly depends on PR #12. No merge is authorized or performed.

Operator steps: [PRODUCT_VARIANT_BATCH_GUIDE.md](PRODUCT_VARIANT_BATCH_GUIDE.md).

## Limits and remaining work

This completes a static batch-preview slice, not the whole requested product library. The existing inventory remains 21 masters / 4 available previews / 17 drafts. No new real product geometry or physical dimensions are certified. Three presets are simple studio/wall backgrounds, not a furnished-room scene library. Veneer texture/material selection, curved bottle/box adapters, drawer/rotating cabinet geometry and missing product measurements/dielines remain outstanding. AI artwork/provider integration and UV manufacturing are not exercised here.

NAS inspection located cabinet assembly illustrations but they did not establish board thickness or exact door-notch outlines. A file named actual size was a commerce poster with overall dimensions for a different bedside product; it was not substituted as a part drawing for the requested cabinet.

Issue #6 / PR #13 stays blocked until PR #14 authority is authorized and actually on main. This branch contains no Articulation Source V1 copy, cherry-pick, 75-degree animation workaround, DOOR_OPEN render or live H3/LTX/Vision/CNC action. FIXTURE input and REAL render must not be described as physical CAD truth or Production Ready.
