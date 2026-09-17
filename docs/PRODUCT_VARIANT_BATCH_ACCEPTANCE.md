# Product variant batches — Round 9B file and namespace flush gate

Instruction `511e9169421947c155dd47da34dda6b506e27ee4` / [Supervisor comment5705530120](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5705530120) authorizes the corrected indeterminate-commit contract. PR15 remains DRAFT/OPEN on `codex/model-category-tree` (PR12); **MERGE_AUTHORIZED=false, PR16 FROZEN, Round10 HOLD**.

Final closure-only instruction **`7ae49f5f956b43f7981fbcde92452deedffd0847`** / [Supervisor comment5706078068](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5706078068) provisionally accepted the direction and froze CODE87ea4d3 while requiring exact CODE CI, new clean REAL and exact DOCS CI. That review was PARTIAL, not final acceptance; the gates below complete the requested evidence.

## Exact verification

- CODE **`87ea4d3ba753c811f693cec8f4a3f465aca94364`**; [Actions 35161605399](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35161605399): Windows **1314 PASS**, Ubuntu **1310 PASS +4 existing Windows-only skips**. Both checkout SHAs verified. CI render paths are **MOCK regression**.
- Clean exact-CODE local full suite **1314 PASS**, zero skips/failures. Added **29** focused tests; these also pass in a separate Linux container. The final full suite retains the prior persistence, cleanup and identity gates.
- Clean REAL Blender acceptance **`12711dff-d675-4a2e-a620-7d5ad81bf05e`**, run after exact CODE dual-CI success: **Blender5.2.1 LTS / OptiX**, `usedMock=false`, two synthetic/static cabinet variants. Artifact SHA/size, finite pixels, .blend reopen, restart/history/download and cache/attempt/DAM/job/publication lineage PASS. Existing authority/serialization matrices remain PASS.
- DOCS follows these completed gates. Exact DOCS SHA and its subsequent Ubuntu/Windows CI are recorded in the final Issue1 handoff after success; a document cannot embed its own future commit SHA.

## Baseline and corrected contract

Clean accepted CODE **`8129309c45b1db566385305e0db5a03f23c64e33`** was imported unchanged before production edits. Actual Windows and Linux child processes exercised state/request/row/terminal/publication-shaped JSON writes. The actual symbols are `recipe_3d.atomic_json` and `model_batches._once`; the alternate names in the original instruction did not exist. Source inspection and operation tracing found no explicit durable file flush or namespace synchronization. This is **REAL_LOGIC_AUDIT**, not observed data loss or a kernel trace.

Windows11 local E: NTFS writable-file and writable-directory FlushFileBuffers succeeded. Linux Docker writable-overlay file fsync and directory-fd fsync after replace/link/unlink succeeded. Windows GENERIC_READ directory error5 was only a diagnostic; writable directory flushing was available. Capability calls alone did not establish an application commit contract.

The negative baseline in [comment5705499390](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5705499390) remains valid: after real replace, an injected namespace-sync EIO made the writer fail but left a complete seal that the existing unmocked verifier accepted in a fresh process. That was **MOCK / FAULT_INJECTION_LOGIC** at the injected boundary, using an isolated copy of accepted Round8 artifacts. It was not a new render or physical device failure. The original over-constrained D5 was stopped and reported; it is not retroactively relabeled PASS. Supervisor explicitly changed the requirement to an indeterminate outcome without a new authority protocol.

## Implementation

Initial CODE `fa6afd48e08b11f2e9eaf2de9df3684c5cd6d5ba` / Actions35159595918 passed Windows1302 and Ubuntu1298+4, but clean REAL `b940339a-eb0c-443a-9ba8-25f911421e5e` **FAILED** before generating artifacts: status polling saw an active writer's initial request/progress flush window as missing/corrupt metadata (HTTP422). It is not accepted REAL evidence. Two deterministic cases reproduced FAIL before correction; 239 related tests then passed before final freeze, and the final 29 focus tests include 12 startup/corruption guards. All final gates are rerun on the final CODE above; the initial green CI is not substituted for them.

The correction returns only the existing pending/no-batch view while the exact workspace OS lock proves a live writer, initial progress is still absent, and no row/terminal facts exist. It validates serialized task/state/version and any committed request identity/hash; it reads no temp data and writes/replays nothing. No owner, malformed records, wrong identity, or existing row/terminal facts retain rejection. This addresses the timing window enlarged by real sync without changing publication verification or treating missing authority as success.

`durability.flush_file` flushes runtime buffering and the still-open host file handle before atomic replacement. Windows uses FlushFileBuffers; POSIX uses fsync. Existing bounded Windows replace contention retries are unchanged. After replace, immutable link and existing scoped temp unlink, `namespace_committed` synchronizes the containing directory.

Windows opens a writable directory with backup semantics and full sharing, queries its filesystem through the same handle, requires NTFS, then calls FlushFileBuffers. Non-NTFS or API errors do not silently succeed. POSIX opens the directory and fsyncs its descriptor. Every descriptor/handle is closed; no volume handle, elevation, broad scan or background storage subsystem is added.

A file-flush error before the commit leaves final authority absent/unchanged. An error after namespace mutation raises **CommitIndeterminate** with the operation/path and chained cause. The failed call never returns success, does not retry or roll back the committed final, and the batch loop propagates this exception before another row/receipt. The existing service records failure through its existing error path. No schema, verifier, queue, PreviewOwnership, DAM, renderer, Product Master, identity hash, or naming contract changes.

This is a bounded JSON/containing-directory primitive. It does **not** prove durability of every ancestor directory, copied render artifact, remote filesystem, storage controller or power-loss scenario. An indeterminate final may later be observable and valid under the unchanged verifier; that observation is **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**, not proof of durable success from the failing call.

## D1–D6 evidence

| Gate | Current result and classification |
|---|---|
| D1 | Actual flush then real child kill before replace on Windows and Linux; fresh process no phantom final or temp adoption. Injected file-flush errors leave absent/existing final unchanged. REAL_OS_IO_FLUSH / REAL_PROCESS_RECOVERY; injected errors MOCK. |
| D2 | Actual file flush → replace → directory sync → link → directory sync → owned unlink → directory sync, on both exercised platforms. Scoped cleanup errors stop before subsequent writes. REAL_OS_IO_FLUSH; fault paths MOCK. |
| D3 | Copied accepted artifacts, full unmocked verifier. Injected post-replace sync EIO returns CommitIndeterminate; fresh verifier accepts the already-existing valid seal, rejects absent/tampered controls, blocks duplicate generation/receipt, and preserves bytes. PARTIAL / COMMIT_INDETERMINATE_DURABILITY. |
| D4 | Retained nine actual W1/W2/W3 × request/row/terminal crash cases. W2 same-file two-link candidates preserved and recovery fails closed; final verified and duplicate blocked. PARTIAL / PRESERVED UNKNOWN. |
| D5 | Actual flush-complete request/row/terminal/publication JSON writes, killed owner, fresh readers and immutable facts preserved. Duplicate generation/receipt, stale writer and replay blocked. REAL_PROCESS_RECOVERY + REAL_OS_IO_FLUSH; artifact generation/validation in this focused harness is MOCK. |
| D6 | Current full suite retains persistence30, ownership/concurrency21, state-temp35, identity71 and immutable-temp49 cases, including real Windows sharing handles and actual killed/fresh processes. Render fixtures remain MOCK. |

Raw per-process PIDs, operation ordering, paths, bytes/hashes, classifications and test properties are embedded in the JSON evidence. Windows evidence comes from the clean exact-CODE full suite; Linux focused evidence comes from an isolated Docker Linux6.18.33.2-microsoft-standard-WSL2 writable overlay with the same read-only source checkout. Both Actions jobs independently passed on their own runners. No container evidence is mislabeled native Ubuntu CI.

D3 reuses only a copied input artifact tree from accepted Round8 REAL `4c084b88-a7b3-4780-89e9-7bc60721d07e`; original evidence remains byte-identical. The **new** clean REAL evidence is `12711dff-d675-4a2e-a620-7d5ad81bf05e`. No reused render is represented as a new execution.

## Reproduction

From the exact CODE checkout (Python3.12 and declared dependencies installed):

```text
python -X utf8 -m pytest -rA -o junit_family=xunit1 --junitxml=local-full.xml
python -X utf8 -m pytest tests/test_durability.py -rA -o junit_family=xunit1 --junitxml=durability.xml
```

CI/mock regression sets `FOX3D_MOCK_BLENDER=1`. The manual full-verifier D3 helper requires the retained accepted artifact tree; use a new isolated root on every run:

```text
python -X utf8 tests/helpers/durability_publication.py --code-root . --source .fox3d-work/batches/4c084b88/d --root .fox3d-work/r9bf-pub --expected-code 87ea4d3ba753c811f693cec8f4a3f465aca94364 --tenant sonaqueen-home --model a25cc814-30a5-4f30-a7e7-0fc48a0b2625 --generation 97b1a86c-25e1-5613-84bd-34af9e8b9847
```

Clean REAL acceptance sets `FOX3D_MOCK_BLENDER=0` and `BLENDER_PATH=C:/Program Files/Blender Foundation/Blender 5.2/blender.exe`, then runs `python -X utf8 scripts/run_model_batches_e2e.py --round3` only after exact CODE dual-CI SUCCESS. Baseline audit harness source, its hashes and exact commands are embedded in the JSON; baseline worktree remains unchanged.

## Platform references and limits

The file primitive follows [Microsoft FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers). Directory persistence uses the [MS-FSA flush contract](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/0de7dc40-9627-437e-a4df-c4696cdc3d02) with the [NTFS-specific product-behavior limitation, footnote80](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/4e3695bd-7574-4f24-a223-b4679c065b63); the helper rejects other Windows filesystem names rather than interpreting no-op success as a guarantee. POSIX file and directory calls follow [Linux fsync](https://man7.org/linux/man-pages/man2/fsync.2.html). These document platform requests, not destructive hardware test results.

| Truth | Scope |
|---|---|
| File/namespace calls directly exercised | REAL_OS_IO_FLUSH on the named surface |
| Killed writer + fresh reader | REAL_PROCESS_RECOVERY |
| Typed outcome, identity/verifier/ownership retention | REAL_LOGIC |
| Injected EIO, mock artifacts and CI renderer | MOCK / FAULT_INJECTION_LOGIC |
| Failed post-namespace sync | PARTIAL / COMMIT_INDETERMINATE_DURABILITY |
| W2 extra hard link | PARTIAL / PRESERVED UNKNOWN |
| Hardware power-cut/reset survival | BLOCKED / NOT_TESTED |
| New clean synthetic/static Blender output | REAL_RENDER only |

`physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`. No physical CAD, print calibration or Production Ready claim. PR13/14 remain unchanged; Issue6 is BLOCKED_PR14_NOT_ON_MAIN. PR16 scenes remain FROZEN and the user's local runtime has not been deployed/restarted. No live H3/LTX/Vision/CNC/LASER/PLC or machine operations.

[Prior accepted Round8 report](https://github.com/netfox-web/blender-autonomous-3d/blob/85ecad41da13bcd14140a7dd373fed4e09012a4f/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json) retains historical evidence. Its actual counts were Windows1285/Ubuntu1281+4 and REAL4c084b88; Supervisor corrected the earlier misquoted values in comment5705530120. Those prior counts/renders are not current gates.

After exact DOCS dual-CI success: one READY_FOR_RE_GATE handoff, then **STOP for Supervisor; Round10 HOLD**.


## Round 10 — binary artifact publication durability

Supervisor instruction `450b35b55afeb2a198c8896105a87e6e99a297bd` / comment [5706795692](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5706795692) accepted Round 9B with scope and authorized Round 10. The final CODE remains `MERGE_AUTHORIZED=false`, PR15 DRAFT/OPEN/unmerged, PR16 FROZEN, Round11 HOLD.

### Baseline audit and A–D crash windows

Accepted baseline CODE `87ea4d3ba753c811f693cec8f4a3f465aca94364` was inspected before production edits. `model_compositions.generate()` and `print_preview.generate()` copied worker DAM files directly to final names with `shutil.copy2`: no runtime flush, host file flush or containing-directory synchronization. `manifest.json` then recorded hashes, `meta.json` bound the manifest, the existing verifier ran, and publication/latest authority followed. Round 9B JSON files already used the durable `atomic_json` path. Worker-origin DAM files were never modified. This is a **REAL_LOGIC_AUDIT**, not inferred data loss.

Fresh child processes with actual local filesystem writes exercised A–D. The persisted evidence is `.fox3d-work/round10-baseline-probe-evidence.json`, classified **REAL_PROCESS_RECOVERY / local filesystem only**:

- A: killed while a large artifact temp was materializing; no publication/latest and no available generation.
- B: killed after artifact bytes but before manifest; no publication/latest and no available generation.
- C: killed after manifest but before `published.json`; no publication/latest and no available generation; loose files are not authority.
- D: killed after `published.json` but before `latest.json`; published generation remained intact, mutable latest pointer was absent, and no fresh available result was inferred.

These probes do not test power loss, NAS/network storage, controller cache or physical production.

### Minimal correction

`durability.publish_binary()` now streams each DAM artifact to an exact target-bound same-directory temporary, flushes Python and the open host handle, verifies expected SHA/size when supplied, atomically replaces the final name, and synchronizes the containing directory through the accepted Round 9B primitive. Symlink targets are rejected; unknown debris is never adopted or broad-swept. A pre-publication error leaves the prior final unchanged. A post-namespace error propagates `CommitIndeterminate`; the caller receives no success and does not retry, rollback or continue publication. `model_compositions.py` and `print_preview.py` now use this helper for every manifest-authoritative binary/derived file. The authority chain remains `artifact bytes -> manifest hashes -> meta/verifier -> published.json -> latest pointer`; no second marker, DB, WAL, replay or architecture change was added.

### Adversarial and retained tests

New focused tests cover complete byte/hash/size publication, wrong SHA/size preserving the old final, injected namespace indeterminate outcome with complete final bytes, missing source and symlink rejection. The clean exact-CODE full suite passed; the final test set is **Windows 1319 PASS**, **Ubuntu 1315 PASS + 4 existing Windows-only skips**. Exact Actions run [35170538114](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35170538114), checkout SHA verified in both logs. Existing Round 6–9B ownership, identity, temp-debris, and JSON durability suites remain green. CI renderer paths are **MOCK regression**; actual tested OS primitives retain only the narrower REAL label.

### Clean REAL acceptance

After exact CODE dual-platform success, clean acceptance `2fe5d1cd-08bb-4e17-9ca1-ecec317a8c97` ran on Blender **5.2.1 LTS / OptiX**, `usedMock=false`, with two **SYNTHETIC_STATIC_FIXTURE** cabinet variants. All real artifact files (`beauty.png`, `front-closed.png`, `model.glb`, `model.blend`, `geometry.json`, `golden-observation.json`, and door previews) have recorded SHA/size. `.blend` reopen, finite pixels, restart/history/download, cache/attempt/DAM/job/publication lineage and retained Round 9B matrices passed. This is **REAL_RENDER** for the render path only; it is not physical CAD geometry, print validation, manufacturing readiness, NAS durability or power-loss evidence.

| Truth | Classification / boundary |
|---|---|
| Local artifact flush and containing-directory sync | REAL_OS_IO_FLUSH on tested local surface only |
| Fresh child kill and reader | REAL_PROCESS_RECOVERY |
| Hash/size/verifier/publication ordering | REAL_LOGIC |
| Injected I/O and CI fixture artifacts | MOCK / FAULT_INJECTION_LOGIC |
| Namespace-sync uncertainty | PARTIAL / COMMIT_INDETERMINATE_DURABILITY |
| NAS/network filesystem | BLOCKED / NOT_TESTED |
| Physical power cut/reset | BLOCKED / NOT_TESTED |
| Physical product/print/manufacturing/global Production Ready | false |

Round 10 leaves `physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`, and `MERGE_AUTHORIZED=false`. No H3/LTX/Vision/CNC/LASER/PLC or production operation was used.


## Round 10 correction — derived PNG publication durability

Supervisor instruction `93a607a3cd0416734f4f9db55e1e7dc495100861` / correction comment [5707089429](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5707089429) authorized the correction. PR #15 remains DRAFT/OPEN/unmerged; `MERGE_AUTHORIZED=false`, PR #16 is frozen, and Round 11 remains HOLD.

### Corrected CODE

The baseline audit identified direct final-name `shutil.copy2` writes in both `model_compositions.prepare()` and `print_preview.prepare()`. Commit `febdd8b1bd471e7b0cf572fffc1135e761ad48db` replaces those derived PNG writes with `durability.publish_bytes()`: target-bound same-directory owned temporary, runtime and host flush, optional SHA/size validation, atomic replacement, containing-directory synchronization, symlink rejection and owned-temp cleanup. Decode verification occurs only after the durable target exists. Pre-publication errors preserve the prior final; namespace uncertainty propagates `CommitIndeterminate`, with no retry, rollback or adoption. Worker-origin DAM files remain untouched.

### Fresh accepted-baseline A–D crash windows

A fresh child-process probe ran from clean accepted CODE `87ea4d3ba753c811f693cec8f4a3f465aca94364` before the correction. Evidence `.fox3d-work/round10-baseline-accepted87-evidence.json` is classified **REAL_PROCESS_RECOVERY / local filesystem only**: A killed during binary/derived materialization left no fresh available/adoption and preserved the prior generation; B killed after final bytes before manifest left no publication authority; C killed after manifest/meta before publication left no model-composition `published.json` (print-preview latest boundary is preserved as implemented); D killed after publication before latest left the immutable published authority intact while a missing/stale pointer did not duplicate. This does not claim NAS, power-loss, controller-cache or physical-production evidence.

### Adversarial tests and exact CI

Focused tests cover complete derived byte publication with hash/size, writer failure preserving an old final, namespace commit indeterminate with complete final bytes, missing source and symlink safety. Exact CODE Actions run [35172649152](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35172649152) passed on the corrected SHA in both jobs: **Windows 1321 PASS / 0 skipped; Ubuntu 1317 PASS / 4 existing skips**. Local full pytest also passed. CI renderer paths remain **MOCK regression**; only the narrower tested OS primitives carry REAL labels.

### Clean REAL acceptance

After corrected CODE CI, clean REAL evidence `f87232e2-5b33-48bb-998a-bb102232e090` ran Blender **5.2.1 LTS / OptiX**, `usedMock=false`, with two `SYNTHETIC_STATIC_FIXTURE` cabinet variants. SHA/size were recorded for beauty/front-closed/door previews/GLB/BLEND/geometry/golden observation; `.blend` reopen, finite pixels, cache/attempt/DAM/job/publication lineage and restart/history/download checks passed. This is **REAL_RENDER** for the render path only; physical CAD geometry, print validation, manufacturing readiness, NAS durability and power-loss evidence remain unproven.

| Truth | Classification / boundary |
|---|---|
| Local artifact flush and containing-directory sync | REAL_OS_IO_FLUSH on tested local surface only |
| Fresh child kill and reader | REAL_PROCESS_RECOVERY |
| Hash/size/verifier/publication ordering | REAL_LOGIC |
| Injected I/O and CI fixture artifacts | MOCK / FAULT_INJECTION_LOGIC |
| Namespace-sync uncertainty | PARTIAL / COMMIT_INDETERMINATE_DURABILITY |
| NAS/network filesystem | BLOCKED / NOT_TESTED |
| Physical power cut/reset | BLOCKED / NOT_TESTED |
| Physical product/print/manufacturing/global Production Ready | false |

Round 10 correction leaves `physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`, and `MERGE_AUTHORIZED=false`. No H3/LTX/Vision/CNC/LASER/PLC or production operation was used.


## Round 10 final correction — failure semantics and evidence closure

Supervisor final-correction instruction `215657aac77b3e3f175b47368d20ec6c720a8805` / decision [5707544987](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5707544987) required the smallest test-semantic closure. Final CODE is `0082b98bbaf9f233eda32a5382b9fc373f5a6236`; PR #15 remains DRAFT/OPEN/unmerged, `MERGE_AUTHORIZED=false`, PR #16 FROZEN, Round 11 HOLD.

The former namespace test is now explicitly named **post-replace namespace sync failure**: `os.replace()` may have installed complete bytes, then containing-namespace synchronization raises `CommitIndeterminate`; the call returns no success and the complete final may remain visible. A distinct **pre-replace file-flush failure** probe covers both `publish_binary()` and `publish_bytes()` and verifies the prior final remains byte-identical with no owned temp debris. A service-level regression injects `CommitIndeterminate` during generated artifact publication and proves `manifest.json`, `published.json`, and `latest.json` are not advanced. No retry, rollback, replay, second marker, DB or WAL was introduced.

Exact final CODE Actions [35176969210](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35176969210) passed on `0082b98bbaf9f233eda32a5382b9fc373f5a6236`: **Windows 1324 PASS / 0 skipped; Ubuntu 1320 PASS / 4 existing skips**. Local full pytest passed.

Clean final REAL acceptance `7ba7806e-aa18-4325-8c58-e704b7d2f729` ran after that exact CODE CI on Blender **5.2.1 LTS / OptiX**, `usedMock=false`, with two `SYNTHETIC_STATIC_FIXTURE` variants. Generated preview PNG plus manifest-authoritative PNG/BLEND/GLB/geometry/golden-observation artifacts have SHA/size records; PNG decode/reopen, `.blend` reopen, finite pixels, restart/history/download, cache/attempt/DAM/job/publication lineage and no duplicate publication checks passed. This is **REAL_RENDER** and local process/OS evidence only; it is not physical CAD, print, manufacturing, NAS or power-loss evidence.

The retained baseline A–D child-process evidence remains bound to accepted CODE `87ea4d3ba753c811f693cec8f4a3f465aca94364` and classified **REAL_PROCESS_RECOVERY / local filesystem only**. The final correction test classifications are: host flush **REAL_OS_IO_FLUSH** on exercised local surfaces; injected failure **MOCK / FAULT_INJECTION_LOGIC**; post-namespace uncertainty **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**; W2 extra hard-link ambiguity **PARTIAL / PRESERVED UNKNOWN**; hardware power cut/reset/controller cache and NAS **BLOCKED / NOT_TESTED**.

`physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`, and `MERGE_AUTHORIZED=false`. No H3/LTX/Vision/CNC/LASER/PLC or production operation was used.


## Round 11 — DAM artifact source identity

Supervisor instruction commit `e0417845f9aacf99c8455f95042157c3c8049eff` / blob `fcac50e5e60679f4f09b20ceb00d4e4e0379790c` and decision comment [5708290953](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5708290953) required evidence closure for PR #15. PR #15 remains DRAFT/OPEN/unmerged; `MERGE_AUTHORIZED=false`, `globalProductionReady=false`, PR #16 remains frozen, and Round 12 is HOLD.

### Accepted CODE baseline and correction

On accepted CODE `0082b98bbaf9f233eda32a5382b9fc373f5a6236`, a real local DAM object was registered, its source path was mutated after registration, and the old copy path accepted the mutated bytes. Stored digest `95fed465d4f73c401e132a26434b599a642ec4b2976571c0e68792bd5785ed2c` differed from the mutated/final copied digest `73eac7f4bd7c539d6b893c96d61938b15c910de5b1d653bb3ad012940f65ba8c`; the manifest was present. This is `REAL_OS_IO_INTEGRITY` evidence of the missing source-identity binding, not a production DAM claim.

Final CODE `74ef218e47f10958cb8a8a66a1bf4a6aa7df7cbd` adds strict `DamObject` identity validation and passes the stored SHA (plus valid authoritative size metadata when present) to `publish_binary()` from both worker artifact publishers. Missing, malformed or non-hex identity fails closed before manifest/meta/published/latest. Derived PNG `publish_bytes()` behavior is unchanged. Adversarial coverage proves stored mismatch, source-change-during-copy fault injection, correct source, malformed/missing identity, retained isolation failures, and no retry/rollback/replay.

Exact CODE Actions [35180923106](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35180923106) passed on both exact checkouts: Windows **1324 PASS / 0 skipped**, Ubuntu **1320 PASS / 4 existing skips**. Local full pytest passed. CI and injected TOCTOU paths are `MOCK / FAULT_INJECTION_LOGIC`; source-binding implementation and local filesystem result are `REAL_LOGIC` / tested local behavior.

### Clean REAL acceptance

Evidence `53b009bc-74f8-4fab-acba-38a967bc0271` ran after exact CODE CI on clean tree with Blender **5.2.1 LTS / OptiX**, `usedMock=false`, `realOptix=true`, and two `SYNTHETIC_STATIC_FIXTURE` cabinet generations. Both generations passed `.blend` reopen, finite pixels, artifact SHA/size and manifest publication records; cache/attempt/DAM/job/publication lineage and restart/history/download checks passed. Manifest SHA records were `3d18fbe1b08c37f5f6368a0f793ba0bf814dc8c65a265564173472975ee06acf` and `dc3d3cb49418796518c9910987a232cc2e7016f8f35ae37eb4387fb7c0bee72b`. This is `REAL_RENDER` for synthetic/static visual evidence only. It does not establish physical CAD truth, print validation, NAS durability, manufacturing readiness or Production Ready.

`physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`, and `MERGE_AUTHORIZED=false`. No live H3/LTX/Vision/CNC/LASER/PLC or production operation was used. After exact DOCS dual-CI, one READY_FOR_RE_GATE handoff is required, then STOP for Supervisor.
