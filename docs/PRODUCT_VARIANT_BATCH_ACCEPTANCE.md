# Product variant batches — Round 7 scoped crash-debris acceptance

Instruction `3f70403b19596c723995e14aca29e94eaeb637a8` / Issue #1 comment 5700808414. Existing PR #15 remains DRAFT/OPEN on PR #12 `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`. No merge authorization, runtime deployment, scene feature or architecture rewrite.

## Current gate

- Exact CODE `eaa4d683937e09a7de2e4b30e7156772a98ca596`: [Actions 35124100743](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35124100743). Actual checkout SHA verified on both jobs: **Windows 1165 PASS; Ubuntu 1161 PASS + 4 existing Windows-only skips**. CI artifacts remain MOCK regression, not real Blender evidence.
- Pre-commit focus **182 PASS**. New clean exact-CODE focus **35 PASS: six actual subprocess/OS cases + 29 unit/fault regressions**. Retained clean ownership focus 21 PASS; persistence focus 30 PASS including three REAL_OS_IO cases. No separate local full-suite rerun claimed.
- Superseded CODE `6203a87ecc8aa86de628038a591c6f52e66921e2`, Actions 35123515020 **CANCELLED**, not PASS. A test-only fixture mock leaked into the parent verifier; the final CODE restores the original functions and adds an isolation regression before formal acceptance.
- Clean exact-CODE REAL acceptance `61493611-302a-4503-a6a0-0a93e374e468`: Blender **5.2.1 LTS / OptiX**, `realOptix=true`, `usedMock=false`, two synthetic static variants. Artifact SHA/size, finite pixels, `.blend` reopen, restart/history/download and lineage PASS; retained **30 + 21 + 35** matrices PASS.
- CODE CI precedes clean REAL acceptance; DOCS is committed only after this evidence exists. Exact DOCS CI identity/results are reported in the subsequent Issue #1 handoff because a commit cannot contain its own SHA.

## Baseline and narrow correction

Unchanged clean accepted CODE `70587508bb8afc2ebe876cebd4304c369be7ed76` reproduced six actual hard-kill cases. Exact orphan outer-state temps survived fresh ownership. Authoritative destination bytes (or absence) remained intact; orphan bytes were never adopted and no automatic replay occurred. Baseline F allowed an explicit submission while an orphan was locked because there was no cleanup gate; that is missing hygiene, not a publication-authority promotion. Original and refined raw captures are preserved locally; complete refined state bytes/hash, temp SHA/size, PIDs, inventories, outcomes and logs are embedded in JSON. [Baseline checkpoint](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5701064895).

`scavenge_state_temps()` requires a live held `PreviewOwnership` object, an open guard stream, exact `state.json` target and matching resolved workspace. It matches only direct children with **`state.json.[0-9a-f]{8}.tmp`**, using the actual atomic writer's eight-character UUID token contract. All candidates are checked for regular-file type, one link and absence of reparse attributes before deletion starts. Unknown/nested files are untouched. Type ambiguity, permission denial or unlink failure propagates before a fresh state write. A partial cleanup is not reported as success; a fresh retry can complete after external conditions are removed.

Call sites: `RecipePreviewService.status()` after acquiring ownership and before interrupted-state recovery; `submit()` after ownership and before the initial queued-state write. A live competitor cannot acquire the guard, performs no cleanup and cannot submit a second writer. Normal same-process active reads do not scavenge. No candidate contents, mtime, age, PID, lease, wildcard recursion or lock-file deletion is used. Cleanup emits an INFO log per basename; it adds no product/publication metadata and grants no availability/readiness or replay authority.

| Case | Baseline PID / outcome | Exact CODE killed → fresh PID / outcome | Baseline orphan evidence |
|---|---|---|---|
| A | 43156 / FAIL cleanup | 31320 → 24320 / PASS | `state.json.91e8d61f.tmp` SHA `13ac2e7874cb50be9d14877abf1981d9f9919bff5f460116729dd5798de33dd9` (220 bytes) |
| B | 31488 / FAIL cleanup | 33500 → 29972 / PASS | `state.json.e5d30e55.tmp` SHA `cef04692e86336dc6124aefa1a7d91267ec44eeeaea8f86f47666026eb0a5391` (220 bytes) |
| C | 22612 / FAIL cleanup | 31024 → 44772 / PASS | `state.json.bd8d6be0.tmp` SHA `2f805f24bfe0b32b5e02d23d157eecb9d987b153f6975e33857bf880b0c44da3` (220 bytes) |
| D | 43556 / FAIL cleanup | 27344 → 7980 / PASS | `state.json.c01b7eb1.tmp` SHA `28a4f5f06274486f6f4bd9747fae3049d0a24787d0c7bf9114c86f1432d51428` (220 bytes) |
| E | 44060 / FAIL cleanup | 44172 → 46880 / PASS | `state.json.602f279b.tmp` SHA `8fc82cc8baa8e0f17097932755c2a3ce6a1b08e753ceb7d1d91a7d311e834d97` (220 bytes) |
| F | 45948 / FAIL cleanup | 44216 → 33488 / PASS | `state.json.581429af.tmp` SHA `6602b6bf890385f8808dd0f0f993d8a8f8d1d2486364ff6eb8bc6450a6e8c0eb` (220 bytes) |

A preserves absent state and cleans before explicit resubmit. B preserves existing authoritative bytes exactly. C uses actual Windows destination delete-sharing conflict/probe 32 and bounded writer retry before external TerminateProcess; the destination lock is released before fresh cleanup. Ubuntu runs the corresponding real SIGKILL/temp-exists case without claiming Windows semantics. D keeps the owner alive while another process reads/submits: the competitor is read-only/busy, has zero cleanup/writes/render entry, and the live temp remains intact. E cleans multiple exact direct candidates while unknown names, nested temps, owner.lock and immutable request/row/terminal/publication/authority sentinels remain byte-identical. F denies deletion through an actual Windows handle (Ubuntu directory permission denial under non-root runner): submission surfaces failure with unchanged state/inventory, then succeeds after external release. All six use actual external process termination and fresh independent processes. Their publication artifacts/validators are **MOCK**; none is REAL_RENDER.

## Retained product and persistence behavior

Current exact CODE retains Round6 A–F ownership/fencing and two isolation cases, all PASS. A separate clean real-Blender double-submit trial has one render winner and a busy loser with zero writes/render entry. Round5 A/A_PROGRESS/B/C/D reran and passed; B/C use real Blender publications and the canonical verifier. Round5 generic `atomic_json` case D still leaves its orphan: it is outside the RecipePreviewService cleanup boundary. The existing 30 persistence tests, exclusive immutable records, bounded Windows replace retry and 30+21+35 authority/tamper/type matrices remain intact. Server retry warnings: 1; acceptance-process retry warnings: 0.

The existing batch feature binds artwork/scene selections to exact tenant/master/revision/input/authority identities and preserves independently verified history. Current batch completion requires the current revision/hash and active declaration; historical downloads retain their original snapshot and verifier. Progress, latest pointers, lock files and cleanup outcomes confer no publication truth. Synthetic, reference and operator-declared unmeasured inputs are supported only within their declared visual scope; measured/CAD authority remains unavailable. Prior accepted implementation details and original failures are preserved at [Round6 DOCS `7c01e0306db106cee146e70f04e8f7b6c8e452bd`](https://github.com/netfox-web/blender-autonomous-3d/blob/7c01e0306db106cee146e70f04e8f7b6c8e452bd/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md) and its full JSON; current reruns and all original Round5/6 baselines are retained in this JSON.

## Truth and stop boundary

| Evidence | Classification / limit |
|---|---|
| Publication/authority and scoped cleanup logic | REAL_LOGIC |
| Live independent owner/competitor and isolation | REAL_PROCESS_CONCURRENCY |
| Actual killed child and fresh recovery | REAL_PROCESS_RECOVERY |
| Real local OS guard / Windows sharing handle / POSIX permission | REAL_OS_IO, platform-specific |
| Separate clean Blender winner and two variants | REAL_RENDER; synthetic visual fixture only |
| Unit/fault tests and CI/cleanup artifacts | MOCK regression; no physical/render claim |
| Other atomic destinations/global cleanup/product-room workflow | UNCLAIMED / PARTIAL |
| Physical geometry / printing / manufacturing / global readiness | BLOCKED / false |

`inputTruth=SYNTHETIC_STATIC_FIXTURE`; `physicalProductGeometryTruth=false`; `physicalPrintValidated=false`; `manufacturingReady=false`; `globalProductionReady=false`. No physical CAD truth or Production Ready cabinet claim. Scope is trusted local filesystems/cooperating services, not distributed storage, arbitrary ACL, disk/power-loss durability or hostile replacement.

PR #16 remains FROZEN DRAFT; PR #13/#14 unchanged; Issue #6 BLOCKED_PR14_NOT_ON_MAIN; `MERGE_AUTHORIZED=false`. No live H3/LTX/Vision/CNC/LASER/PLC or user-runtime deployment. After exact DOCS Ubuntu/Windows CI PASS and one READY_FOR_RE_GATE handoff, STOP for Supervisor Re-Gate; do not start Round 8 automatically.
