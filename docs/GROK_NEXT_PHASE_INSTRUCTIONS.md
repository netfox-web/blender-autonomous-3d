# Development Agent 指令：PR #15 Round 10 — FINAL CORRECTION / EVIDENCE CLOSURE

> Supervisor checkpoint: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 9B CODE: `87ea4d3ba753c811f693cec8f4a3f465aca94364`
> Accepted Round 9B DOCS: `14a2c83528b3a0d76c0ec71a51afa40cc443e30b`
> Prior incomplete Round 10 CODE: `e128c44484bf8f8939a5725fb80306b0e8f5c376`
> Reviewed corrected Round 10 CODE: `febdd8b1bd471e7b0cf572fffc1135e761ad48db`
> Corrected CODE Actions: `35172649152` — Ubuntu SUCCESS / Windows SUCCESS on exact `febdd8b1...`
> Supervisor decision: **CHANGES REQUIRED / FINAL EVIDENCE CLOSURE**
> Round 11: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. Re-Gate result

The new CODE `febdd8b1...` closes the previously identified direct-final PNG write defect at source level and must be retained unless a concrete failing test proves otherwise:

- `durability.publish_bytes()` writes an exact target-bound same-directory temp with exclusive create;
- produced bytes are flushed through the existing host-file durability primitive before `os.replace()`;
- containing namespace synchronization is requested after replacement;
- `model_compositions.prepare()` no longer writes generated preview PNG directly to the final name;
- `print_preview.prepare()` no longer writes generated preview PNG directly to the final name;
- both production paths reopen/verify the final PNG after publication;
- exact CODE Actions `35172649152` completed SUCCESS on both Ubuntu and Windows.

Therefore the former **Blocker A is CLOSED at implementation level**.

This is **not yet Round 10 acceptance**. Do not start Round 11 and do not merge.

## 1. Remaining concrete correction — failure semantics test is still mislabeled

`tests/test_binary_publication.py` still contains a test named equivalent to:

`test_publish_binary_pre_namespace_failure_is_indeterminate_and_final_is_valid`

but it monkeypatches `namespace_committed()` after `os.replace()` has already installed the final file. That is **not a pre-namespace/pre-publication failure**. It is a **post-namespace-mutation durability-sync failure**.

Make the smallest possible correction:

1. rename/reword that test so its name and assertions say **post-replace / post-namespace-mutation sync failure**;
2. retain the contract: the call raises `CommitIndeterminate`, returns no success, while a complete final may already be visible;
3. add a distinct **pre-replace / file-flush failure** probe by injecting failure before `os.replace()` and prove the previous final is absent or byte-identical and no valid new publication is created;
4. apply the same semantic coverage to the new `publish_bytes()` path where useful;
5. add one service-level regression proving `CommitIndeterminate` from generated PNG/binary publication stops the caller before manifest / `published.json` / `latest.json` advancement.

Do not create a rollback protocol, second marker, DB, WAL, replay engine, or second authority.

## 2. Evidence already present and may be retained

The current PR evidence document contains the accepted-baseline Round 10 A–D child-process crash-window package against exact accepted CODE `87ea4d3...`:

- A — kill during artifact materialization;
- B — final artifact bytes before manifest;
- C — manifest/meta before publication boundary;
- D — publication/latest-pointer boundary.

If the JSON evidence remains byte-identical, runner-bound, and contains the recorded PID / kill point / file set / SHA-size / fresh-reader / verifier / replay-adoption fields, **do not rerun it just to manufacture a newer timestamp**. Preserve it as **REAL_PROCESS_RECOVERY / local filesystem evidence**, not power-loss evidence.

If any required field is absent or the JSON contradicts the MD summary, fail closed and rerun only the missing probe.

## 3. Exact final CODE gate

After the small test correction above, freeze one exact final Round 10 CODE SHA.

Required:

- focused artifact-publication tests pass;
- full local suite passes;
- exact GitHub Actions on that final CODE SHA completes Ubuntu + Windows SUCCESS;
- record exact run ID and pass/skip counts;
- CI/render fixtures remain **MOCK regression** and must not be promoted.

`35172649152` proves current `febdd8b1...` CI is green, but if you change code/tests after this instruction, a new exact final CODE run is mandatory.

## 4. New clean REAL Blender acceptance is mandatory on final corrected CODE

The existing Round 10 clean REAL evidence in `PRODUCT_VARIANT_BATCH_ACCEPTANCE.md` was produced before `febdd8b1...` corrected derived-PNG publication. It cannot substitute for a clean acceptance of the final corrected code.

After exact final CODE dual-CI is green, run one new clean acceptance bound to that exact SHA:

- `FOX3D_MOCK_BLENDER=0`;
- Blender 5.2.1 LTS + OptiX;
- `usedMock=false`;
- clean working tree;
- at least two current synthetic/static variants;
- generated preview PNG + manifest-authoritative PNG/BLEND/GLB/geometry/golden-observation bytes included in evidence;
- SHA/size checks;
- PNG decode/reopen and BLEND reopen/finite checks;
- restart/history/download/publication-lineage checks;
- no duplicate publication;
- no temp adoption/replay;
- retained Round 9B durability/ownership/identity gates.

Classify only what was actually exercised:

- rendered outputs on real Blender: **REAL_RENDER**;
- actual host flush on named tested surface: **REAL_OS_IO_FLUSH**;
- killed child + fresh reader: **REAL_PROCESS_RECOVERY**;
- injected errors / ordinary CI renderer: **MOCK / FAULT_INJECTION_LOGIC**;
- post-namespace sync failure outcome: **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
- W2 extra hard-link ambiguity: **PARTIAL / PRESERVED UNKNOWN**;
- hardware power-cut/reset/controller-cache survival: **BLOCKED / NOT_TESTED**.

Keep `physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`.

## 5. Acceptance-document closure

Update only the existing authority package unless a canonical statement has actually become false:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

The final package must identify:

- accepted Round 9B baseline;
- retained A–D baseline evidence and classifications;
- incomplete `e128c444...` history;
- corrected `febdd8b1...` and any later final correction SHA;
- exact final CODE Actions and counts;
- exact files changed;
- real process/OS evidence separated from fault injection;
- new clean REAL acceptance ID bound to final CODE;
- artifact SHA/size/verifier results;
- remaining PARTIAL/BLOCKED items;
- exact DOCS SHA and exact DOCS dual-platform CI.

Important: the current Round 10 section still references earlier CODE/CI/REAL evidence. Do not leave it implying that `e128c444...` is the final accepted corrected code after `febdd8b1...` changed production publication behavior.

Do **not** rewrite these just to look current:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their existing truth boundaries remain valid: Mock pytest is not production evidence, CNC live control is BLOCKED, Vision Judge is MOCK, and global Production Ready remains false.

## 6. Final handoff gate

After final CODE + new clean REAL + acceptance docs are complete:

1. freeze exact DOCS/head SHA on PR #15;
2. run exact DOCS GitHub Actions;
3. Ubuntu + Windows both SUCCESS on that exact DOCS SHA;
4. verify checkout/head SHA exactly;
5. leave exactly one Issue #1 handoff headed:

`[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 10 artifact publication durability`

Include final CODE SHA, CODE Actions, new clean REAL ID, DOCS SHA, DOCS Actions, A–D summary, REAL/MOCK/PARTIAL/BLOCKED matrix, `globalProductionReady=false`, `MERGE_AUTHORIZED=false`, PR #15 DRAFT/OPEN/unmerged, PR #16 FROZEN, and **Round 11 HOLD**.

Then STOP for Supervisor Re-Gate.

## 7. Frozen boundaries

- No merge / retarget / rebase-to-main / cherry-pick.
- PR #15 stays DRAFT / OPEN / unmerged.
- PR #16 stays FROZEN DRAFT.
- PR #13 / #14 and Issue #6 gates unchanged.
- No live H3 / LTX / Vision / CNC / LASER / PLC work.
- No architecture rewrite.
- No second authority / durability ledger / replay subsystem.
- No Mock/FIXTURE promotion to Production Ready.
- No physical manufacturing-readiness claim.
- No hardware power-loss claim without actual destructive power/reset evidence.
- `MERGE_AUTHORIZED=false`.
- `globalProductionReady=false`.
- **Round 11 HOLD**.
