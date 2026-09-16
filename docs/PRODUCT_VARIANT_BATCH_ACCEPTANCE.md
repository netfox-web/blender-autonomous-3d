# Product variant batches — Round 5 abrupt process recovery acceptance

Instruction `11c931d422b64b4852480beb6aab9c579dbead96` / Issue #1 comment 5697016103. Existing PR #15 stays based on unmerged PR #12 `codex/model-category-tree` at `68f64d604bb750c0c48830c0d50516ef5157d296`. No merge, retarget, rebase or new PR.

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

- CODE `f5ac3a6773d99f30709a84dc9adb97231ca53ba9`: [Actions 35094237439](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35094237439); **Windows 1109 PASS; Ubuntu 1105 PASS + 4 Windows-only skips**. Actual checkout SHA verified for both jobs. CI is non-Blender regression. The retained 3 Windows handle-lock cases are REAL_OS_IO; 5 Windows / 4 Ubuntu actual subprocess cases are REAL_PROCESS_RECOVERY with MOCK artifacts and artifact validation. Windows Case D also uses a real handle. Other cases remain MOCK/unit regression.
- Local Windows full suite **1109 PASS**; combined focus **205 PASS**. New recovery focus: 5 actual subprocess cases plus 5 unit regressions. Retained persistence focus **30 PASS** includes 3 REAL_OS_IO cases. Existing 1099 tests retained.
- Clean exact-CODE REAL acceptance `5588ea74-2db7-47b4-b8d4-9ce7cec7d828`: two static synthetic cabinet artwork variants, Blender **5.2.1 LTS / OPTIX**, `realOptix=true`, `usedMock=false`.
- Both renders pass SHA/size, finite nonuniform 800×800 image, `.blend` reopen, original queue/job/attempt/cache/DAM/publication lineage. Geometry hashes match and artwork pixels differ.
- Actual server restart preserves and re-verifies exact authority identity. The 30 Round 2 corruption/restoration outcomes still pass on these new artifacts.
- **21 authority outcomes** pass: current master content/hash contradiction, stored hash/reference/version tampering (including numeric/boolean type contradictions), missing snapshot/control, cross-tenant content, forged measured type/declaration, revocation, downgrade, and publication authority mismatch even with recomputed ordinary manifest/publication seals. Category metadata, historical identity, restart and restored visual download checks pass.
- Interruption remains `SIMULATED_INTERRUPTION_REAL_ARTIFACTS`, not a killed-render claim.

Full evidence: [JSON](PRODUCT_VARIANT_BATCH_ACCEPTANCE.json). Prior accepted [Round 2 report](https://github.com/netfox-web/blender-autonomous-3d/blob/7ca89384c1328710a60ddbff18c160c64e7680d1/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md) is historical context only. Exact DOCS SHA and its dual-platform CI are reported in Issue #1 after success; no circular self-SHA claim.

## Serialized identity correction

Supervisor found that Python numeric equality could accept JSON `true` as integer `1` at neighboring persisted batch/publication boundaries. Before correction, 46 targeted tests on isolated exact CODE `d684686f076fb91c1d9a87ca996a9bd917f1a735` produced **27 FAIL / 19 PASS**, with actual `DID NOT RAISE ValueError` failures. This is MOCK regression reproduction, not REAL rendering. [Reproduction record](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5694802662).

The existing request verifier now requires exact integer identityVersion, sourceRevision, draft batchVersion/masterRevision and selection masterRevision. Queue/service batchVersion is strict, including pending requests. Terminal receipt rows use canonical hashes rather than Python dict numeric equality. The canonical generation verifier and batch verifier require exact publication historyVersion/sourceRevision and matching draft masterRevision. Authority-bound results cannot remove historyVersion to enter legacy handling; independent pre-V1 history keeps its original visual-only path.

The new exact-CODE REAL run passes **35 serialized-type outcomes** alongside the prior **30 durable-lineage** and **21 authority** outcomes. It tests bool/float/string substitutions in request version/revisions, service batchVersion, terminal row indices 0 and 1, publication historyVersion/sourceRevision/draft revision, plus missing authority publication historyVersion. Publication and meta seals are recomputed in manifest trials; invalid identity still blocks availability/download. Each of the 34 corruption trials restores exact bytes and verifies valid availability/download again; the final outcome records restored readiness. Physical and manufacturing flags remain false.

The [previous Round 3 report](https://github.com/netfox-web/blender-autonomous-3d/blob/91111ed57039df2d537a717b8897d1be82b80625/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md) is retained as historical evidence; it does not substitute for this correction run.

The historical Round 3 attempt `02c928e7-06ec-4001-859a-844e21c6d82e` remains FAIL (Windows WinError 5); its later unchanged-CODE rerun passed but did not claim a fix. Round 4 now reproduces a real delete-sharing lock with the same error and validates the bounded behavior below. This does not certify arbitrary ACL, disk, network, crash or power-loss durability.

## Round 5 — actual abrupt process recovery

The commit-point map was written before changing accepted CODE `65299811abd076645edbe1cd0777b12b63968c0b`:

| Sequence | File / writer | Meaning |
|---|---|---|
| 0 | RecipePreviewService.submit/_run state.json queued/running | Mutable outer operational state; request hash/task binding checked, never proves publication |
| 1 | model_batches.generate -> _once(request.json) | Immutable request identity: tenant, model, batch, revision, selections and authority snapshots |
| 2 | atomic_json(batches/<batchId>.json) initial queued then running rows | Mutable operational progress/cache; cannot confer success/availability |
| 3 | model_compositions.generate: artifact/manifest/meta validation, current authority check, published.json, latest.json; model_batches._published | Per-generation publication seal and canonical verifier establish exact artifact/selection/authority lineage; latest.json only a convenience pointer |
| 4 | _once(<rowIndex>.json) after _published | Immutable row terminal fact bound to request identity and deterministic row generation; availability still requires re-verifying publication |
| 5 | atomic_json(batches/<batchId>.json) after row receipt | Mutable progress update; crash can leave it behind the immutable receipt |
| 6 | _once(terminal.json) after all rows | Immutable outer batch terminal fact; successful outer result requires this exact successful receipt |
| 7 | RecipePreviewService._run finally state.json succeeded/failed/cancelled | Mutable service transition; cannot supersede terminal authority or fabricate success |

The baseline ran unchanged in a clean detached checkout. A test-only wrapper observes a real committed write, signals the parent and blocks at the boundary; the parent externally **TerminateProcess** kills the actual child Python service process. A fresh Python process calls the existing API/service recovery. No injected exception substitutes for termination, and no production crash API was added. B/C create actual Blender publications and run the full existing verifier. No Blender renderer process was killed, and no power-loss/fsync durability is claimed.

| Case | Baseline actual result | Clean new CODE result |
|---|---|---|
| A: request committed, initial progress missing | **FAIL recovery presentation**: HTTP 422; exact request preserved, no replay or false success | PASS: interrupted, 0 available rows, exact request preserved, no replay |
| A_PROGRESS: initial progress, no row receipt | PASS: interrupted, 0 available rows | PASS |
| B: first publication and receipt, mutable row still running | PASS: exact first output recovered, second unavailable | PASS: full publication check; tamper blocks availability, restoration restores it |
| C: both receipts, no terminal commit | PASS: individual outputs recoverable, outer interrupted | PASS: never promotes outer success from row count |
| D: Windows real sharing failure/retry then hard-kill | PASS non-corruption: old JSON A valid, owned orphan remains | PASS: actual old JSON A remained valid; later exact B write succeeds; orphan and other-writer sentinel preserved |

The only production correction reconstructs an **in-memory progress view** when progress is absent and the exact-bound outer service is failed/cancelled. Request, row and terminal receipts retain exclusive `_once()` authority; successful row availability still requires exact generation/selection/authority/publication verification. Existing malformed progress is rejected; missing progress for running/succeeded outer state is rejected. No new store or automatic replay was added. Five unit regressions cover those boundaries. Baseline HTTP 422 failure evidence remains in the JSON and [baseline report](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5697152989).

After CODE CI, all five actual Windows interruption/restart cases passed on clean exact CODE; B/C use full publication verification. A/A_PROGRESS have no completed publication, and D exercises atomic JSON only. Immutable request/row/generation bytes remain unchanged, repeated API reads are stable, and duplicate immutable writes raise FileExistsError. Valid completed rows are individually downloadable; unfinished rows are not. The existing separate clean REAL Blender run also passes 30 + 21 + 35 matrices.

CI uses actual child processes on both OSes (A/A_PROGRESS/B/C everywhere, D only Windows), but **MOCK publication artifacts/artifact validator** for speed and lack of Blender; those CI tests are REAL_PROCESS_RECOVERY, never REAL_RENDER. The local full-publication evidence is recorded separately.

Hard termination bypasses Python finally: one owned atomic-write orphan is observed in D and left intact. Loader paths ignore it; a fresh valid write works, and another writer's sentinel temp is preserved. **Hard-kill cleanup remains PARTIAL / NOT SCAVENGED**. Normal Round 4 success/caught-error cleanup still passes; zero-orphan crash cleanup, fsync, disk/power loss, network filesystem and hostile-admin durability are not claimed.

The [accepted Round 4 report](https://github.com/netfox-web/blender-autonomous-3d/blob/c9deeeaeab3411c4fc66e03f7a6c54980ee07e52/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md) remains historical and is not substituted for this CODE's evidence.

## Retained Round 4 — Windows atomic persistence

The clean pre-fix accepted CODE `6b118898ebd430592e293c04c5cabe4bc30f37d8` was exercised with a real Windows CreateFileW handle (READ/WRITE sharing allowed, DELETE sharing denied) held for 400 ms. atomic_json immediately raised actual **PermissionError / WinError 5** before release; destination remained exact, parse-valid JSON A; one orphan temp remained. A non-mutating DELETE-access probe returned actual sharing violation **32**. [Reproduction record](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5696334025). No injected error was used in this baseline reproduction.

The existing helper still writes a same-directory temp and atomically replaces its target. It now owns the temp via exclusive creation and tries at most **8 replacements**, with **25/50/100/200/200/200/200 ms** backoff (**975 ms cumulative scheduled sleep**, excluding OS call/scheduling time). Only Windows error 32/33 or error 5 corroborated by a DELETE-access probe returning 32/33 qualifies. Bare permission/ACL denial, ENOSPC, invalid paths, serialization/encoding/write errors and unrelated I/O do not retry. Terminal errors propagate, the previous target remains unchanged when no replacement happened, and owned temp files are removed. A colliding pre-existing temp is never overwritten or deleted. `_once()` exclusive hard-link semantics remain unchanged.

After exact CODE CI passed, the clean exact CODE persistence suite passed **30** tests. Three use actual Windows handles: two bounded transient holds (50/200 ms after first real failure) complete with exact JSON B and no orphan temp; one sustained hold exhausts eight attempts, raises the actual typed error, retains exact JSON A and cleans its temp. The 27 other focused cases use normal/unit or injected failures and are not REAL_OS_IO evidence. Exact timings/error lists and the pre-fix orphan observation are retained in the JSON report.

The subsequent clean REAL Blender run passes all **30 + 21 + 35** prior matrices and completes atomic batch progress writes. Observed contention during that run: **1 server retry warning; 0 acceptance-process retry warnings**. Retry events are logged rather than hidden; a terminal persistence failure still fails the caller/acceptance. This controlled test establishes bounded Windows sharing-lock handling, not blanket Production Ready or power-loss safety.

The [accepted Round 3 evidence](https://github.com/netfox-web/blender-autonomous-3d/blob/1e70faa99088e5a6f0189f5a19a6ffa8d903285c/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md) remains historical; its render/CI evidence is not substituted for the new CODE run.

## Truth matrix

| Area | Evidence / readiness |
| --- | --- |
| Durable batch lineage | REAL_LOGIC |
| Input authority enforcement | REAL_LOGIC |
| Serialized identity exactness | REAL_LOGIC |
| Blender execution | REAL_RENDER, usedMock=false |
| Geometry inputs | SYNTHETIC / REFERENCE; not physical truth |
| GitHub CI | Non-Blender MOCK/unit; real subprocesses use MOCK artifacts, Windows actual handles identified separately |
| Process kill / fresh-process recovery | REAL_PROCESS_RECOVERY; local full publication verifier, CI MOCK artifacts |
| Hard-kill orphan cleanup | PARTIAL / NOT SCAVENGED; ignored as authority |
| Windows delete-sharing lock integration | REAL_OS_IO; Ubuntu skips 3 retained Round 4 tests and Round 5 Case D |
| Physical geometry authority | BLOCKED / false for fixture/reference inputs |
| Physical print / manufacturing release | BLOCKED / false |
| Live H3/LTX/Vision | Unchanged, BLOCKED or MOCK |
| Live CNC/LASER/PLC | BLOCKED |
| Global Production Ready | false |

`inputTruth=SYNTHETIC_STATIC_FIXTURE`, `physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`, `MERGE_AUTHORIZED=false`.

PR #16 stays FROZEN DRAFT; none of its room-scene code/evidence is used. PR #13/#14 remain unchanged and Issue #6 stays `BLOCKED_PR14_NOT_ON_MAIN`. No DOOR_OPEN claim, articulation copy/cherry-pick, legacy-angle promotion, live provider call or machine control. STOP after handoff for Supervisor Re-Gate.
