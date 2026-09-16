# Product variant batches — Round 8 immutable crash-window gate

Instruction `487301abac95d206cba391d0869fde5ba2f2c429` / [Supervisor comment5703707434](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5703707434). Round7 strict identity closure was **ACCEPT WITH SCOPE / GO Round8**. PR15 stays DRAFT/OPEN on `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`. **MERGE_AUTHORIZED=false; Round9 HOLD.**

## Exact gates

- CODE **`8129309c45b1db566385305e0db5a03f23c64e33`**; [Actions 35147126655](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35147126655): **Windows1285 PASS; Ubuntu1281 PASS +4 existing Windows-only skips**. Checkout SHA verified in both jobs. CI is regression, not REAL_RENDER.
- Local full suite on clean exact CODE: **1285 PASS**, zero skips/failures. Precommit combined focus301 PASS; final Round8 focus49 PASS. Clean exact-CODE reruns: Round8 **49**, persistence **30**, ownership **21**, state-temp **35**, strict identity **71** PASS.
- Clean exact-CODE REAL acceptance **`4c084b88-a7b3-4780-89e9-7bc60721d07e`**, after CODE CI success: Blender **5.2.1 LTS / OptiX**, `realOptix=true`, `usedMock=false`; two synthetic static cabinet variants. Artifact SHA/size, finite pixels, .blend reopen, restart/history/download, cache/attempt/DAM/job/publication lineage PASS; retained **30+21+35** logical matrices PASS.
- DOCS follows these gates. Its exact DOCS SHA and subsequent Ubuntu/Windows CI run are recorded in the final Issue1 handoff; this commit cannot self-reference its own future SHA.

## Baseline before production edits

Exact accepted CODE **`0c6bb2a0e8ed8a8a7d23b8a938b5670e83f3b6c1`**, clean detached worktree, actual child-process hard kills. Each window was exercised for **request.json, 0.json, terminal.json**: nine actual killed writers and nine fresh recovery processes. Test hooks paused existing os.link/Path.replace boundaries; production baseline behavior was unchanged. Full directory inventories, path types/link counts/inodes, exact bytes/size/SHA, killed/fresh PIDs and final verification results are embedded in JSON.

| Window | Accepted-CODE observation | Classification |
|---|---|---|
| W1: outer temp materialized, before link | Final absent; durable single-link UUID-only temp remains. Fresh process never adopts or replays it. | Unpublished bytes, but old name cannot bind an exact final: unknown, preserve. |
| W2: link completed, before temp unlink | Final and temp have equal SHA/bytes/inode and link count2. Final verifies; duplicate publish rejected without changing final bytes. | Final is immutable published authority. Extra hard link is ambiguous for auto-cleanup: preserve, never infer authority from it. |
| W3: inner atomic temp materialized, before replace | Final absent; nested UUID-only atomic temp survives. Fresh process never adopts/replays. | Unknown legacy debris; preserve. |

All nine baseline orphans remained after recovery. No baseline authority promotion or automatic generation was observed. This justifies recognizable future names and bounded cleanup, not a global sweep or authority redesign. Harness source hash and original failing harness attempts remain local: the first pre-baseline harness tried reading the locked owner byte; that instrumentation was corrected before the nine valid baseline cases. No failed run is PASS evidence.

## Minimal correction

Only `model_batches.py` production code changes. Batch request/row/terminal temps now use `<final>.once.<16 lowercase hex>.tmp`; nested atomic temps append the unchanged `.<8 lowercase hex>.tmp` contract. The target-bound name stays within the prior Windows path-length budget. Non-batch authority declarations keep their existing UUID-only temp names.

`scavenge_once_temps` requires a live held PreviewOwnership/open stream for the exact product workspace and explicit allowed immutable targets. It checks canonical batch UUID and final basename, direct directory scope, parent-directory reparse/alias checks, then candidate regular-file/single-link/reparse metadata. All candidates in the supplied set are validated before removal. Only matching direct children are considered; it does not read debris contents, use age/mtime/PID heuristics, recurse, or promote orphan bytes.

Terminal-state `current()` recovery takes the existing workspace guard, services request.json, validates the existing request identity, then services only identity-derived row paths and terminal.json before any interruption receipt write. A live owner blocks competing recovery. `_once(..., owner=...)` propagates cleanup failure before a replacement immutable write. Active queued/running reads retain the existing read path. No queue, PreviewOwnership, renderer, DAM, master, schema, hash or publication verifier redesign occurred. Relative workspace paths retain their previous support through lexical absolute normalization; reparse/alias checks remain enforced.

**W2 remains deliberately fail-closed:** multi-link candidates are preserved, final bytes verify unchanged, and recovery reports ambiguity. No automatic hard-link deletion is claimed. The old unbound UUID-only names, unknown files, retired batches and generic/global cleanup remain **PARTIAL / UNCLAIMED**. Cleanup never supplies request/receipt/terminal authority or turns interrupted work into success.

## Current exact-CODE process evidence

| Window | Target | Killed → fresh PID | Result |
|---|---|---|---|
| W1 | request.json | 19688 → 35604 | Recognized debris removed; no adoption/replay |
| W2 | request.json | 45932 → 33624 | Preserved; final verified, duplicate blocked; recovery fails closed |
| W3 | request.json | 45668 → 16928 | Recognized debris removed; no adoption/replay |
| W1 | 0.json | 34124 → 36820 | Recognized debris removed; no adoption/replay |
| W2 | 0.json | 32448 → 26344 | Preserved; final verified, duplicate blocked; recovery fails closed |
| W3 | 0.json | 37740 → 45188 | Recognized debris removed; no adoption/replay |
| W1 | terminal.json | 31568 → 5224 | Recognized debris removed; no adoption/replay |
| W2 | terminal.json | 44352 → 40848 | Preserved; final verified, duplicate blocked; recovery fails closed |
| W3 | terminal.json | 46224 → 17760 | Recognized debris removed; no adoption/replay |

Every case also runs an independent live competitor while the original owner is held: competitor returns PreviewBusy with identical before/after inventories, zero cleanup and zero immutable write. Final request/row/terminal/publication records present before restart remain byte-identical. Actual Windows junction/reparse and delete-sharing denial tests PASS; corresponding Ubuntu tests exercise POSIX symlink and directory-permission behavior. Failed deletion blocks publication before a new write. These are **REAL_PROCESS_RECOVERY / REAL_OS_IO** with **MOCK artifact validation**, not real renders. The49 focus tests include9 process cases,2 OS cases and38 unit/fault/fixture regressions.

## Retained gates and REAL rendering

Round5 persistence30, Round6 ownership21, Round7 state-temp35 and strict-identity71 PASS on clean current CODE. Six previous cleanup kill/restart cases, six concurrency cases plus two isolation cases, and all five actual Windows recovery cases remain PASS. The retained B/C recovery paths and a separate one-winner/one-busy-loser trial use real Blender/full publication verification; loser performs zero writes/render entry. The two-variant acceptance also verifies restart/history/download and published lineage. Server retry warnings: 1; acceptance-process retry warnings: 0.

Superseded CODE ed63440459021f79348c3cba8f9daf8f26d2b01f / Actions35146743812 was **CANCELLED**, not PASS, when relative-root compatibility was identified before final freeze. Its local full suite was terminated and has no PASS claim. Earlier focused301 passed on that version; all required current gates above are rerun on final CODE. The first precommit 32-character token caused a Windows long-path failure;16 characters restores the old temp path budget and all final process cases pass. Neither precommit failure is hidden or used as successful evidence.

[Prior accepted Round7 evidence](https://github.com/netfox-web/blender-autonomous-3d/blob/d36600e4831d7a86e29a4647cf72560b62b744d3/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json) preserves the true-vs-int and absent-vs-null baselines, prior process failures and earlier cancelled runs. Current retained evidence replaces only current-run fields; historical provenance remains linked by immutable SHA.

## Truth boundary

| Evidence | Classification / limit |
|---|---|
| Exact publication identity, scoped cleanup and serialized fencing | REAL_LOGIC |
| Actual killed/fresh process and live competitors | REAL_PROCESS_RECOVERY / REAL_PROCESS_CONCURRENCY |
| Actual link/lock/reparse/delete-denial operations | REAL_OS_IO, platform-specific |
| Separate Blender winner and two synthetic variants | REAL_RENDER, synthetic visual input only |
| Unit/fault fixtures and CI artifact validation | MOCK regression |
| Legacy/global/retired temp cleanup; full-room product workflow | PARTIAL / UNCLAIMED |
| W2 extra hard link | UNKNOWN / PRESERVED / FAIL_CLOSED |
| Physical geometry/print/manufacturing/global readiness | false |

`inputTruth=SYNTHETIC_STATIC_FIXTURE`; `physicalProductGeometryTruth=false`; `physicalPrintValidated=false`; `manufacturingReady=false`; `globalProductionReady=false`. Fixture renders are not physical CAD truth or production readiness. PR16 FROZEN DRAFT; PR13/14 unchanged; Issue6 BLOCKED_PR14_NOT_ON_MAIN. No merge, retarget, rebase-to-main, cherry-pick or live H3/LTX/Vision/CNC/LASER/PLC work. After exact DOCS dual CI, report READY_FOR_RE_GATE once and STOP; Round9 needs a new Re-Gate.
