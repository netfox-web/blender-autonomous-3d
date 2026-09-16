# Product variant batches — Round 3 input authority acceptance

Instruction `782d0bd884473f151e7ed8de909015c08f1a712f` / Issue #1 comment 5693576330. Existing PR #15 stays based on unmerged PR #12 `codex/model-category-tree` at `68f64d604bb750c0c48830c0d50516ef5157d296`. No merge, retarget, rebase or new PR.

## Result

Every new batch selection retains a version-1 input authority snapshot and content hash. Its exact identity is included in the batch request hash, row selection hash, deterministic generation ID and published manifest. Mutable progress cannot grant physical readiness. Missing, changed, revoked or cross-tenant authority blocks current completion and download rather than being inferred from the render.

The snapshot records tenant/master/revision/input hash, geometry authority kind, source explanation/Recipe/print-face reference hashes, unmeasured dimension status, unverified surface status, exact artwork classification revisions/hash, classification metadata, and declaration provenance. Declaration provenance records creator, time and decision with `approvedBy=null`, `physicalApproval=false`. Source text hashes make a decision reproducible; they are not measurement evidence.

Authority kinds:

| Kind | Meaning in this implementation |
| --- | --- |
| SYNTHETIC_FIXTURE | Explicit fixture declaration; exercised by this REAL acceptance |
| REFERENCE_RECIPE | Original Recipe reference snapshot; unmeasured, exercised in MOCK regression |
| OPERATOR_DECLARED_UNMEASURED | Default for other operator-entered masters; no independent measurement |
| MEASURED_OR_CAD_AUTHORITY | Reserved and rejected: no reviewed CAD/measurement evidence provider is integrated in this scope |

There is no API or AI/worker shortcut to approve measured geometry, print surfaces or manufacturing. Existing model, artwork, category, serial scheduler, renderer, DAM and publication verifier are reused. Authority files use short tenant/master-scoped paths for Windows compatibility; exclusive-write snapshots and declaration records assume a trusted local filesystem.

## Current versus historical availability

Current batch rows require the exact current master revision/hash and active declaration. Any revision change invalidates current batch completion, even if geometry bytes are unchanged. Downloadable visual assets expose `visualAssetReady=true` only after publication and authority verification; `physicalGeometryAuthorityReady`, `printSurfaceAuthorityReady`, `manufacturingReady` and `physicalPrintValidated` remain false.

Historical generation downloads retain their original snapshot, never the latest declaration. Under existing history rules, the current master input hash must still match; the original revision, declaration, snapshot, publication and artwork revision must remain valid. A later save with the same master hash can leave an original visual download valid while the original batch is no longer current. Revocation/downgrade blocks the affected historical authority too. A category-tree change only changes metadata and grants no physical truth.

Older batches without the authority contract fail closed and must be resubmitted after review. Existing independent historical generations keep their previous visual-only verifier; they do not gain a V1 authority or physical readiness. The UI still allows independently valid history to load when current batch validation fails.

## Exact gates

- CODE `d684686f076fb91c1d9a87ca996a9bd917f1a735`: [Actions 35071688400](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35071688400); Ubuntu + Windows SUCCESS, **1010 tests each**. Actual checkout SHA verified for both jobs. CI is MOCK regression only.
- Local full suite **1010 PASS**; focused batch/composition/category suite **106 PASS**, including 30 additive authority cases.
- Clean exact-CODE REAL acceptance `113ade57-fbe8-46c4-8af5-895de4e65d3d`: two static synthetic cabinet artwork variants, Blender **5.2.1 LTS / OPTIX**, `realOptix=true`, `usedMock=false`.
- Both renders pass SHA/size, finite nonuniform 800×800 image, `.blend` reopen, original queue/job/attempt/cache/DAM/publication lineage. Geometry hashes match and artwork pixels differ.
- Actual server restart preserves and re-verifies exact authority identity. The 30 Round 2 corruption/restoration outcomes still pass on these new artifacts.
- **21 authority outcomes** pass: current master content/hash contradiction, stored hash/reference/version tampering (including numeric/boolean type contradictions), missing snapshot/control, cross-tenant content, forged measured type/declaration, revocation, downgrade, and publication authority mismatch even with recomputed ordinary manifest/publication seals. Category metadata, historical identity, restart and restored visual download checks pass.
- Interruption remains `SIMULATED_INTERRUPTION_REAL_ARTIFACTS`, not a killed-render claim.

Full evidence: [JSON](PRODUCT_VARIANT_BATCH_ACCEPTANCE.json). Prior accepted [Round 2 report](https://github.com/netfox-web/blender-autonomous-3d/blob/7ca89384c1328710a60ddbff18c160c64e7680d1/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md) is historical context only. Exact DOCS SHA and its dual-platform CI are reported in Issue #1 after success; no circular self-SHA claim.

## Truth matrix

| Area | Evidence / readiness |
| --- | --- |
| Durable batch lineage | REAL_LOGIC |
| Input authority enforcement | REAL_LOGIC |
| Blender execution | REAL_RENDER, usedMock=false |
| Geometry inputs | SYNTHETIC / REFERENCE; not physical truth |
| GitHub CI | MOCK regression |
| Physical geometry authority | BLOCKED / false for fixture/reference inputs |
| Physical print / manufacturing release | BLOCKED / false |
| Live H3/LTX/Vision | Unchanged, BLOCKED or MOCK |
| Live CNC/LASER/PLC | BLOCKED |
| Global Production Ready | false |

`inputTruth=SYNTHETIC_STATIC_FIXTURE`, `physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`, `MERGE_AUTHORIZED=false`.

PR #16 stays FROZEN DRAFT; none of its room-scene code/evidence is used. PR #13/#14 remain unchanged and Issue #6 stays `BLOCKED_PR14_NOT_ON_MAIN`. No DOOR_OPEN claim, articulation copy/cherry-pick, legacy-angle promotion, live provider call or machine control. STOP after handoff for Supervisor Re-Gate.
