# PrintFox bridge acceptance

Scope: user-authorized design library and bounded generation integration into `/admin/recipes/print`. PR #9 is stacked on PR #8. PrintFox source and Linux services are unchanged.

- CODE: `6ac129750624ed48530f5f5988a0b5f6606c8ce0`.
- Exact CODE CI: [34833832340](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34833832340), Ubuntu and Windows SUCCESS, 870 tests each.
- Local regression: 870 PASS; bridge-focused tests: 21 PASS; both modified JavaScript files pass syntax checks.
- Clean formal evidence: `e7ee0d4c-8858-40ae-b8da-80bc3073a4e9`; `workingTreeClean=true`, `developmentOnly=false`, PASS.
- PrintFox committed app: `1c774d6691b931fa82b8ed7ee4ae5b4de4e83f2a`, exported with `git archive` into isolated loopback servers. No dirty frontend, `.env`, database, real Token or production worker is copied.
- Blender: 5.2.1 LTS, OPTIX; `realBlender=true`, `usedMock=false`; reopened packed textures/UV and restart PASS.
- Original artwork SHA-256: `47a1535518bf1b3f2a09ff5ae7a5922eadf768b392418071a2f551c10e2470f4`. Artwork is explicitly synthetic geometric blocks, not a real generated design or licensed source.
- Formal JSON and artifact hashes: [acceptance record](PRINTFOX_BRIDGE_ACCEPTANCE.json). Operator guide: [PrintFox bridge](PRINTFOX_BRIDGE.md).

## Verified behavior

Actual PrintFox HTTP authentication, design listing/thumbnail/original download, original-byte SHA preservation, one bounded generate enqueue and cancel, durable request replay after Fox3D restart (zero duplicate remote jobs), expiry of memory authentication on restart, source-size proof ZIP, rejection of release without human checks, REAL Blender render/reopen and persisted preview. No AI worker was started; the real server queue path was exercised and canceled before execution.

Development browser checks additionally verified that import preserves unsaved SKU/name, the imported original appears in the print-face selector, a flat product saves with millimeter dimensions, 3D generation completes visibly, own generation cancel reaches canceled state, and logout hides the remote catalog while preserving the product. These manual checks used the isolated development fixture, separately from formal clean evidence.

## Truth matrix

| Classification | Evidence / limit |
| --- | --- |
| REAL | Actual committed PrintFox app HTTP, imported bytes/hash, actual Blender output/reopen and service restart; all using synthetic artwork and isolated services |
| REAL_LOGIC | Session/tenant/origin boundaries, bounded generation, request journal/reconciliation, original provenance, dimension/proof and human-check gate |
| FIXTURE | Synthetic geometric artwork, test Token and pending/canceled jobs; no production operator release |
| MOCK | CI uses `FOX3D_MOCK_BLENDER=1`; transport fixtures exercise failures and redirects |
| PARTIAL | Production PrintFox health/config discovery only; cabinet manufacturing dimensions and Illustrator native slot calibration remain incomplete |
| BLOCKED / false | Production authentication, actual AI generation, native Illustrator imposition, native/live NetFox job submission, physical color/UV validation and all machine controls |

## Reproduction and review state

After installing the project runtime/dev dependencies, use `python scripts/run_printfox_bridge_e2e.py --printfox-repo E:/projects/printfox` on clean exact CODE. It exports committed PrintFox app code, generates synthetic artwork, starts isolated loopback servers, and terminates its test processes. `--allow-dirty` is development-only; `--keep-servers` is for manual fixture UI checks and requires cleanup afterward. Neither flag was used for formal evidence.

The first CODE run 34833598699 on 0675360 failed Ubuntu collection because `filelock` was not declared. Final CODE declares both `filelock` and runtime `httpx`; only run 34833832340 is PASS evidence.

Supervisor comment 5662502718 and instruction `e05295f7834327403ffb102bbc497124550b0258` accept PR #8 WITH SCOPE and authorize Issue #6 next from current main. No automatic merge of PR #7/#8/#9. This user-requested PrintFox work is separate from Issue #6. Supervisor external LIVE prerequisites remain unchanged. Separate DOCS SHA/dual CI are recorded in Issue #1 after this docs commit, not asserted self-referentially here.
