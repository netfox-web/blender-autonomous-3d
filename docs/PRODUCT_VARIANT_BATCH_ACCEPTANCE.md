# Product variant batches — Round 7 strict serialized outer-state identity correction

Instruction `71d2c7f0d24e2cf4ac8a5ba940249bd68b4a8cde` / Supervisor [comment 5702286623](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5702286623). PR #15 DRAFT/OPEN on PR #12 `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`; merge authorization false, Round 8 HOLD. Prior Round 7 cleanup was accepted within its local scope; **overall prior Round 7 was CHANGES_REQUIRED**, because its retained mutable-state identity fence was not serialized-exact.

## Exact gates

- CODE **`0c6bb2a0e8ed8a8a7d23b8a938b5670e83f3b6c1`**, [Actions 35135148177](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35135148177): **Windows 1236 PASS; Ubuntu 1232 PASS +4 existing Windows-only skips**, exact checkout SHA verified in both jobs. Prior 1165 tests retained; 71 strict-identity regressions added. CI is non-Blender regression.
- Pre-commit combined focus **375 PASS**. Clean exact-CODE strict identity **71 PASS**, cleanup **35 PASS**, ownership **21 PASS**, persistence **30 PASS** including 3 REAL_OS_IO. No separate local full-suite rerun claimed.
- Clean exact-CODE REAL acceptance **`6e7d1d4f-17b2-48d4-abcb-518e878a5273`**: Blender **5.2.1 LTS / OptiX**, `realOptix=true`, `usedMock=false`, two synthetic static cabinet variants. Artifact SHA/size, finite pixels, .blend reopen, restart/history/download and job/cache/attempt/DAM/publication lineage PASS; **30+21+35** retained matrices PASS.
- Exact CODE dual-platform CI precedes clean REAL acceptance. DOCS commit follows these results; its own exact SHA and subsequent dual CI are recorded in the final Issue #1 handoff, not self-referentially invented here.

## Unchanged reviewed-CODE baseline

Before production edits, a clean detached worktree at **`eaa4d683937e09a7de2e4b30e7156772a98ca596`** reproduced both required fail-open cases with a held PreviewOwnership/open stream. S1 persisted `batchVersion=true` compared equal to expected integer 1; S2 expected absent key compared equal to persisted null. In both cases `_write_owned` returned without rejection and overwrote the original state. This violated mutable-state fencing; it was not evidence of physical/publication truth promotion. Full expected/persisted objects, exact before/after bytes/SHA, module source root, harness source and harness SHA are preserved in JSON.

| Case | Exact old CODE state SHA before → after | New exact CODE mismatch |
|---|---|---|
| S1 | `65b42ae0742bfcfac0a8e0e123108e105a054ebe8d9be0847dafcb4a17163100` → `dfa6ab6302baf5a5c54b5494aab960ca19f9da7d657c4d092e8fc629a4224752`; FAIL_OPEN | `65b42ae0742bfcfac0a8e0e123108e105a054ebe8d9be0847dafcb4a17163100` → same SHA; BLOCK/PASS |
| S2 | `c9e5f40ad42dc50ab08ad2df5ee1922d6fc199bb8073bbcc300adb8492c6c23c` → `d8f67ca1ccb2f8ee1412ae1d7c5ec64dd814ad175844cd233b0a0ad690906e78`; FAIL_OPEN | `c9e5f40ad42dc50ab08ad2df5ee1922d6fc199bb8073bbcc300adb8492c6c23c` → same SHA; BLOCK/PASS |

## Minimal correction and regression contract

Only `RecipePreviewService`'s outer-state comparator changed. `_same_state_identity(current, expected)` requires object states; taskId/inputHash keys must exist on both sides, values must be exact `str`, and values must match. BatchVersion key presence must match; if present, both values must have `type(value) is int` and exact equality. Boolean/string/float/null are rejected without conversion. Exact absent/absent and integer/integer writes still work. `_write_owned` also requires owner held and stream open. Mismatch raises before atomic_json, preserving original bytes; it does not repair or normalize them.

The 71 focused tests comprise 16 version-type/presence tamper cases; 3 positive writes; 32 required-string missing/type/value tests across both sides; 6 scalar-subclass tests; 6 non-object tests; 2 released/closed-stream tests; 4 `_run` on_job/finally cases covering S1/S2. Two additional status-recovery cases reject missing required keys without writing. The callback/finally cases tamper state during the generation callback, then assert zero subsequent atomic writes and byte-identical tampered state, while ownership still releases. Existing stale/newer-task fencing cases remain PASS. These are **MOCK/unit fixtures testing REAL_LOGIC**, not renderer evidence.

Local compatibility initially exposed two legacy normal-restart fixtures missing required identity fields. Those fixtures now contain valid taskId/inputHash; malformed-state rejection has its own two new tests. The cancelled intermediate CODE e1c6289 / Actions 35134020720 is not PASS evidence; original local failures are retained in JSON. No production relaxation was made.

No cleanup algorithm, queue, renderer, DAM, master, request, receipt, publication or authority design changed. Round 7 scoped scavenging still fullmatches direct `state.json.[0-9a-f]{8}.tmp`, requires exact workspace ownership, prevalidates candidate type/link/reparse metadata, and propagates deletion failure before a fresh outer write. No content adoption, replay, age/PID/lease or recursive cleanup was introduced.

## Retained cleanup and process gates on new CODE

| Cleanup case | Actual killed child → fresh process PID | Result |
|---|---|---|
| A | 42376 → 23820 | PASS; all recorded invariants true |
| B | 44564 → 44528 | PASS; all recorded invariants true |
| C | 39208 → 39092 | PASS; all recorded invariants true |
| D | 40752 → 27852 | PASS; all recorded invariants true |
| E | 10940 → 18548 | PASS; all recorded invariants true |
| F | 38148 → 12540 | PASS; all recorded invariants true |

A preserves absence; B preserves prior state bytes; C performs Windows delete-sharing/probe32 bounded-retry hard kill and fresh cleanup after external release (Ubuntu corresponding SIGKILL case, not Windows evidence). D's live competitor is read-only/busy with zero cleanup/writes/render entry and live temp intact. E removes only exact direct candidates while unknown/nested temps, owner.lock and immutable request/row/terminal/publication/authority sentinels remain byte-identical. F's actual locked candidate/permission failure is surfaced before new state writes, then external release permits retry. All six actual-process/OS cases pass on new CODE; their artifacts/validator remain MOCK. Original cleanup baseline on 70587508 and all full inventories/logs remain in JSON.

Retained Round 6 A–F process ownership/fencing plus two isolation cases PASS. A separate clean real-Blender identical-submit trial still has one winner/render, and a busy loser with zero writes/render entry. Round 5 A/A_PROGRESS/B/C/D actual recovery PASS; B/C use real Blender/full canonical verifier. Round 5 generic atomic_json D orphan remains intentionally untouched: **global/generic cleanup is UNCLAIMED/PARTIAL**. The30 persistence regressions retain bounded Windows retry and immutable-write semantics. Server retry warnings: 1; acceptance-process warnings: 0.

## Product contract and historical evidence

Batch selections retain exact tenant/master/revision/input/authority identities; completed results and history require the canonical publication verifier. Mutable progress, latest pointers, locks, cleanup outcomes and identity checks confer no physical or publication authority. Current completion requires current revision/hash and an active declaration. Historical downloads retain their original authority snapshot and verifier. Fixture/reference/operator-declared unmeasured inputs remain visual-only; no measured/CAD approval provider is added.

[Prior Round 7 report and raw evidence](https://github.com/netfox-web/blender-autonomous-3d/blob/1b8687e1feb12ff305c3478b675c138d2f7b1666/docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md) preserve the earlier accepted-in-scope cleanup and original failures; current exact reruns are in this JSON. Prior Round 6 evidence remains linked by immutable DOCS SHA. Earlier superseded CODE 6203a87 / run 35123515020 remains CANCELLED, not PASS; no cancelled/superseded run is reused as current success.

## Truth boundary and stop

| Evidence | Classification / limit |
|---|---|
| Serialized identity rejection, publication/authority/scoped cleanup | REAL_LOGIC |
| Actual independent competitors and isolation | REAL_PROCESS_CONCURRENCY |
| Actual killed child and fresh recovery | REAL_PROCESS_RECOVERY |
| Directly exercised local guards/OS handles/permissions | REAL_OS_IO, platform-specific |
| Separate clean winning Blender paths/two variants | REAL_RENDER; synthetic visual inputs only |
| Strict comparator/callback fixtures and CI/cleanup artifacts | MOCK regression |
| Generic/global temp cleanup and product-room workflow | UNCLAIMED/PARTIAL |
| Physical geometry/printing/manufacturing/global readiness | BLOCKED/false |

`inputTruth=SYNTHETIC_STATIC_FIXTURE`; `physicalProductGeometryTruth=false`; `physicalPrintValidated=false`; `manufacturingReady=false`; `globalProductionReady=false`. REAL Blender visual evidence is not physical CAD, print proof or manufacturing readiness. No distributed-filesystem, hostile-admin or arbitrary disk/power-loss guarantee.

PR #15 DRAFT/OPEN/unmerged; Round 8 HOLD; PR #16 FROZEN DRAFT; PR #13/#14 unchanged; Issue #6 BLOCKED_PR14_NOT_ON_MAIN; `MERGE_AUTHORIZED=false`. No live H3/LTX/Vision/CNC/LASER/PLC, merge/retarget/rebase/cherry-pick or runtime deployment. After exact DOCS dual CI PASS and one READY_FOR_RE_GATE handoff, STOP; do not start Round 8 automatically.
