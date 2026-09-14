# Product model category tree acceptance

Explicit user request: organize mats, coasters, wash mats, wood cabinets (2–5 layer open/hinged), bedside cabinets and rotating cabinets with a website-style hierarchy. PR #12 is stacked on #11; no merge authorization. This is classification/navigation metadata, not a new geometry or material engine.

## Behavior

The expandable category navigation includes the requested six groups, all eight open/hinged layer combinations, preserved sliding/bookcase branches and the previous other product families. Parent filters include descendants. Search matches model names, SKU and category paths; generated/draft filters stay separate. Counts refer to models, never NAS materials. Empty categories remain zero and do not create placeholder models.

Classification has its own revision, history and optimistic concurrency check. It is stored beside the master, outside its draft/input hash, so a classification move does not invalidate geometry or existing base/composition generations. Initial suggestions use explicit model fields and Recipe family, never filenames/artwork as structural truth. The operator can save an explicit classification. Family mismatch, unknown category and branch-only category saves are rejected. New leaf-category drafts inherit family/subtype/layers, with PENDING geometry and no inferred physical measurements.

## Verification

- CODE `052be7f057c24b982b6c6c716c1a9aef094999da`, [Actions 34866913056](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34866913056): exact Ubuntu + Windows SUCCESS, 924 tests per OS. Local focused regression 54 PASS, including eight new category cases. JavaScript syntax and diff checks passed.
- Clean REAL evidence `0c83109d-1e6c-4ec6-8d34-ec8c14c68851` PASS after CODE CI, exact CODE, workingTreeClean=true, developmentOnly=false. `python -X utf8 scripts/run_model_categories_e2e.py --keep-server`, using installed Blender 5.2.1 LTS via BLENDER_PATH.
- Actual HTTP and real Blender base + scene generation with a synthetic mat, both BLEND files reopened. Moving floor-mat classification to wash-mat, rejecting a stale save and restarting retained exact master bytes/input/revision, generation IDs and all eight downloadable artifact hashes/byte lengths. No regeneration required by the move.
- Browser: expandable categories, moving a generated fixture while downloads remain visible, empty 3-layer open-cabinet filter, creation with layers only/unknown dimensions, pending draft state and model search passed. Live local UI exposes the tree with three generated references and eight pending drafts; all eleven master files/drafts/revisions/input hashes/states remained unchanged during the local server update. These local operator checks are separate from clean synthetic evidence.
- Initial local regression emitted a Windows WMI native exception banner while completing; a fresh direct checked-exit run and JUnit completed 54/54 with no such banner. No production code workaround was added.
- DOCS SHA / exact dual CI will be recorded in Issue #1 after the documentation commit. They are not claimed PASS in advance.

## Truth boundary

REAL: scoped loopback HTTP, Blender 5.2.1 LTS OptiX base/scene outputs, BLEND reopen and download byte/hash checks. REAL_LOGIC: category persistence/history/conflicts, independent model identity, restart and inventory filters. FIXTURE: synthetic mat dimensions/material. MOCK: CI Blender paths. PARTIAL: three existing reference models and eight drafts; category availability is not modeling completion. BLOCKED: missing physical dimensions/structures, rotating cabinet mechanism, curved/irregular geometry, physical UV/RIP/print, machine writes, live AI providers and global Production Ready.

Veneer source images are conceptually assets with separate material records; they should not multiply geometry templates. A material library, veneer selector, per-part material assignment and calibrated grain scale are **not implemented in this PR**. Existing ARTWORK purpose rules remain unchanged. No NAS original, source Recipe, production PrintFox service, credential or physical machine changes.

Prior PR #11 CODE e9384c6 / DOCS 389f2fe was fully handed off in Issue #1 comment 5666900229; Supervisor comment 5667208483 accepts that prior PR #11 scope, with NO MERGE AUTHORIZATION; it does not accept PR #12. Issue #6 remains a separate current-main lane under 40e64f343287969712a1d6e6fe0b32b49b77aa96, without unmerged dependencies. No auto-merge of #7/#8/#9/#10/#11/#12.

See [operator guide](MODEL_CATEGORY_TREE.md) and [evidence JSON](MODEL_CATEGORY_TREE_ACCEPTANCE.json). Raw local evidence: `.fox3d-work/category-e2e/0c83109d/`.
