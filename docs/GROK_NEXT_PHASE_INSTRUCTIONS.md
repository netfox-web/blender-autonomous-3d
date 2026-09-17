# Development Agent 指令：PR #15 Round 13 Correction Checkpoint — Fail-Closed Publication / Latest Identity

> Supervisor Re-Gate: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Reviewed candidate head: `aceda581e447acd0a79cc8b81d45439f7671f79d`
> New commits reviewed: `ef62e3321586cd3f16a237a58d1751a3791c191a`, `5978817f45976a8f9128bb1f34a6b1baaece2542`, `72a210076995ca6bfe52e82b79e2418eb1222568`, `aceda581e447acd0a79cc8b81d45439f7671f79d`
> Exact head Actions: `35217851646` — still `in_progress` at Supervisor review time; even if green it is MOCK regression because `FOX3D_MOCK_BLENDER=1`
> Supervisor decision: **CHANGES REQUIRED / ROUND 13 CORRECTION ONLY**
> Round 14: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. Keep the valid narrow fixes

Do not revert or redesign the current direction.

Accepted implementation intent in the new candidate:

- `verify_publication_seal()` rejects symlink/non-regular modern `published.json` and pins `manifestSha256`;
- model-composition modern read path uses that publication-seal verifier;
- print-preview `latest.json` now carries `{generationId, manifestSha256}`;
- print-preview status rejects obvious symlink/non-regular `latest.json` before parsing;
- print-preview final writer uses the captured manifest digest when advancing `latest.json`;
- no DB/WAL/new ledger/replay/storage architecture rewrite was introduced.

These are **REAL_LOGIC** changes only. GitHub Actions remains **MOCK regression**. No new final `usedMock=false` REAL Blender acceptance has been supplied for this corrected head.

## 1. Critical blocker — digest mismatch can still return `generated=true`

Current `print_preview.status()` does this sequence:

1. `m = validate(generation)`;
2. compare `latest.manifestSha256` against current `manifest.json` SHA;
3. on mismatch, raise `ValueError` and only set `error` in `except`;
4. return `generated = bool(m)`.

Because `m` was already populated before the pointer-digest check, a stale/tampered pointer can produce an error **while still returning `generated=true` and exposing the manifest**.

That violates the Round 13 fail-closed requirement.

### Required minimal correction

Do one of these, without adding a new authority layer:

- validate into a temporary variable, verify pointer digest, and assign `m` only after all pointer checks pass; **preferred**;
- or clear `m=None` on every pointer-validation exception before returning.

For every invalid current-schema pointer condition, public status must satisfy:

- `generated == false`;
- `manifest == null`;
- invalid generation is not exposed as usable/current;
- no `latest.json` advancement or silent repair occurs.

## 2. Required current-schema latest-pointer behavior

Keep the existing `latest.json`; do not create a second seal.

For new/current print-preview generations, fresh status must fail closed when any of these is true:

- `latest.json` missing after a completed current-schema generation;
- symlink;
- directory/non-regular file;
- malformed/empty JSON;
- missing `generationId`;
- malformed `generationId`;
- generation directory missing;
- missing `manifestSha256`;
- wrong `manifestSha256`;
- manifest/meta pair changed consistently after completion while `latest.manifestSha256` remains frozen.

`read_json()` returning `{}` on malformed JSON is acceptable only if the public result is unambiguously fail-closed (`generated=false`, no manifest exposure). Do not auto-repair the pointer.

Legacy compatibility, if still intentionally supported, must be explicit and covered by a regression test. Do not let legacy absence silently satisfy the current-schema truth gate.

## 3. Production-caller adversarial tests are still incomplete

The reviewed correction changed only `tests/test_model_compositions.py`, adding the publication-symlink case/fixup. That does **not** satisfy the previously required production-caller matrix.

Add tracked tests through real production service/caller paths, not helper-only assertions.

### Model composition — required cases

1. regular matching `published.json` succeeds;
2. missing publication seal fails closed;
3. publication seal symlink to the **same valid JSON bytes** fails closed;
4. publication seal directory/non-regular fails closed;
5. malformed/empty publication JSON fails closed;
6. missing/wrong `manifestSha256` fails closed;
7. manifest changed after initial validation / before publication does not advance latest;
8. meta changed after initial validation / before publication does not advance latest;
9. correct completed modern generation remains readable with `manifest SHA == meta SHA == published SHA`;
10. explicitly supported legacy no-`historyVersion` behavior stays isolated and cannot inherit modern truth.

### Print preview — required cases

11. regular latest pointer succeeds with `manifest SHA == meta SHA == latest.manifestSha256`;
12. latest symlink fails closed;
13. latest directory/non-regular fails closed;
14. malformed/empty latest JSON fails closed;
15. missing/malformed `generationId` fails closed;
16. missing `manifestSha256` fails closed;
17. wrong `manifestSha256` returns **`generated=false` and `manifest=None`** — this is the critical regression test;
18. after successful completion, coherently mutate manifest + meta while leaving latest untouched; fresh status must return `generated=false`;
19. pointer to missing generation fails closed;
20. fresh status after every rejected pointer attempt must not expose an invalid generation as current.

You may organize/parameterize these tests to avoid duplication. The requirement is coverage of the production boundaries, not a specific test-function count.

Retain all Round 9B–12 durability, DAM identity, publication receipt, tenant isolation, revocation, wrong SHA/size, indeterminate commit, no replay/rollback/adoption regressions.

## 4. Evidence classification must remain truthful

Use only these labels for this round:

- publication/latest identity code: **REAL_LOGIC**;
- GitHub Actions with `FOX3D_MOCK_BLENDER=1`: **MOCK regression**;
- monkeypatch/timing/fault triggers: **MOCK / FAULT_INJECTION_CONTROL**;
- directly observed local file bytes/read/write identity: scoped **REAL_OS_IO_INTEGRITY**;
- clean `FOX3D_MOCK_BLENDER=0`, `usedMock=false` output: **REAL_RENDER** only;
- hard-link / hostile concurrent writer not directly proven: **PARTIAL / PRESERVED UNKNOWN**;
- NAS/object storage/controller durability/hardware power-loss: **BLOCKED / NOT_TESTED**;
- physical CAD authority, physical print proof, manufacturing readiness: **BLOCKED / false**.

Do not promote CI or mock/fault tests to Production Ready. `globalProductionReady=false` remains mandatory.

## 5. Final evidence closure order

Do this in order; stop on any failure.

1. Apply only the minimal fail-closed correction above and add the missing production-caller tests.
2. Run focused tests.
3. Run full local pytest.
4. Freeze one exact final Round 13 CODE SHA.
5. Run exact CODE GitHub Actions; Ubuntu + Windows must both SUCCESS and checkout that exact SHA.
6. Only after CODE CI is green, run a **new clean REAL Blender** acceptance on the exact final CODE with `FOX3D_MOCK_BLENDER=0`, `usedMock=false`.
7. Record the two authority chains separately:
   - model composition: `manifest -> meta -> published -> latest generation`;
   - print preview: `manifest -> meta -> latest.manifestSha256 + latest.generationId`.
8. REAL run must include fresh status/reopen verification after success; also capture the fail-closed pointer-digest mismatch outcome without calling it REAL render evidence.
9. Update only the existing PR #15 acceptance package `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md/.json` with exact CODE SHA, CI run, REAL generation/run identity, hashes/sizes, and truthful REAL/MOCK/PARTIAL/BLOCKED labels.
10. Freeze one exact DOCS SHA and run exact DOCS dual-platform CI.
11. Leave one Issue #1 handoff: `[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 13 correction`, including final CODE SHA + CODE run ID + REAL run/generation ID + DOCS SHA + DOCS run ID.
12. STOP. Do not begin Round 14 until Supervisor explicitly says GO.

## 6. Canonical files — do not rewrite for freshness

Do not rewrite these merely to update timestamps:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their truth boundaries remain authoritative:

- Mock pytest is not Production Ready;
- `globalProductionReady=false`;
- `physicalPrintValidated=false`;
- CNC live control remains **BLOCKED**;
- Vision Judge remains **MOCK**.

## 7. Frozen boundaries

- No merge / retarget / rebase-to-main / cherry-pick.
- PR #15 remains DRAFT / OPEN / unmerged.
- PR #16 remains FROZEN DRAFT.
- Round 14 stays HOLD.
- No H3 / LTX / Vision / CNC / LASER / PLC work.
- No DAM/queue/storage/authority architecture rewrite.
- No DB/WAL/second ledger/replay subsystem/duplicate manifest.
- No Mock/FIXTURE promotion to Production Ready.
- `physicalProductGeometryTruth=false`.
- `physicalPrintValidated=false`.
- `manufacturingReady=false`.
- `globalProductionReady=false`.
- `MERGE_AUTHORIZED=false`.
