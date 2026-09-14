# Asset purpose and clean template library — scoped acceptance

A user identified ecommerce images mixed into the model artwork picker, then requested a clean template library. Product templates/drafts and historical NAS materials now have separate views. Browsing materials cannot implicitly create a template or change a model's source association. Only explicit creation starts a new draft; only valid current generated previews enter the generated-model list. Generation is not physical validation.

## CODE and clean REAL evidence

- CODE: `3fd0a30008ae8b19cc4bf3d5ba636f30ef73610c`.
- Exact CODE Actions: [34851148775](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34851148775), Ubuntu + Windows SUCCESS, **904 passing tests each**, counted from completed pytest pass markers.
- Local regression: **98 focused PASS**, including 11 new cases across asset-purpose restrictions and inventory/template separation. No new full local suite claim; the dual CI runs the full suite.
- Clean REAL evidence: `5a13d16e-c19d-4d90-846b-49ebbc618bc7`, PASS, workingTreeClean=true, developmentOnly=false. Ran `python scripts/run_product_models_e2e.py --keep-server` on exact CODE **after both CODE CI jobs passed**.
- Real Blender 5.2.1 LTS OptiX: OPEN_CABINET / HINGED_CABINET / RECTANGLE on synthetic dimensions/artwork. Saved BLEND files reopened with component sizes/locations checked. PNG/BLEND/GLB/geometry hashes and sizes are in the companion JSON.
- Actual loopback HTTP proves default-denied unclassified/reference assets, explicit ARTWORK acceptance, classification persistence through restart, revocation blocking downloads, stale-model blocking and original fixture bytes unchanged.
- Browser checks: default model view excludes NAS inventory; source browsing preserves a selected cabinet form; explicit source-to-draft creation; six-page artwork preview; reference excluded / reviewed artwork included in picker; real fixture generation changes counts from 0 generated / 4 drafts to 1 / 3 without reload. No observed JS errors.

The DOCS commit and its own dual-OS CI are recorded in the final Issue #1 handoff after this commit's Actions run. CODE CI is not substituted for DOCS CI. Earlier development/CI runs 34850478869 and 34850948507 were superseded and cancellation requested; neither is acceptance evidence. Development-only evidence 129f9558 is separate from this clean evidence.

## Asset-purpose rule

Six explicit categories: UNCLASSIFIED, REFERENCE, DIMENSION, DIELINE, ARTWORK, PACKAGING. Filename, file extension, pixel size and PDF page size do not establish purpose or product measurements. Review notes and optimistic revisions/history are stored beside immutable originals. Re-uploading identical bytes or renaming cannot erase the classification. All existing unclassified imports, uploads and PrintFox imports require review; there is no legacy print bypass.

Both model and print backends enforce the rule before creating work. Reclassification away from ARTWORK blocks new use and affected artifact downloads, including earlier proof packages. Existing records/originals remain preserved. Operator classification can be mistaken; this is not automatic visual recognition or manufacturing authorization. Only complete assets are classified: mixed sheets/pages must be reviewed/split first. API review remains within the existing LOCAL operator boundary, not authenticated production tenant ownership.

## Scope truth

| Class | Result |
|---|---|
| REAL | Actual loopback HTTP + real Blender generation/reopen on synthetic regular geometries; local actual source preview and purpose cleanup. |
| REAL_LOGIC | Six-purpose gate, version conflicts/history, tenant-scoped local lookup, legacy defaults, unchanged source bytes, revocation and stale downloads, separated model/material UI. |
| FIXTURE / MOCK | Formal dimensions, SKU and artwork are synthetic. CI uses mock Blender regression; it is not physical or live-provider evidence. |
| PARTIAL | 17 explicitly reviewed local imported files: 15 references, one mixed imposition source left unclassified, one six-page door artwork source reviewed page-by-page. Not all NAS materials classified. The live UI snapshot had 8 drafts (including the operator's additional draft), zero generated company models. |
| BLOCKED / false | Physically validated masters, automatic artwork application to new models, unsupported curved/special geometry, calibrated UV/RIP, physical print, machine/hot-folder dispatch and generative scene integration remain incomplete/false. |

`physicallyValidatedMasters=0`, `generatedCompanyModels=0`, `physicalPrintValidated=false`, `globalProductionReady=false`. Purpose approval does not certify dimensions, print-face/jig origin, color, rights or physical printing. NAS originals and existing saved dimensions were not edited; the two original print jobs remain readable. Licensed images, private NAS indexes and curation records stay local.

Supervisor comment [5664501379](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5664501379) accepted the **prior** PR #10 scope out-of-band, without merge authorization. It did not review these new changes. Authorization here is the user's explicit correction, not an invented instruction commit. Current main context remains `bab3a1a2b4631e0c6f40c5c93e33441a72c74dd0`. PR #10 remains stacked on #9 with no auto-merge. Issue #6 remains a separate authorized lane from current main, with no unmerged-branch dependency; it is not implemented in this correction.

Operator guide: [template/material workflow](ASSET_USAGE_TEMPLATE_LIBRARY.md).
