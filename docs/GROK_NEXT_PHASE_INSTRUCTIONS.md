# Development Agent 指令：PR #15 Round 13 Evidence Closure Checkpoint — Publication / Latest Identity

> Supervisor Re-Gate: 2026-09-24
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Previous reviewed head: `aceda581e447acd0a79cc8b81d45439f7671f79d`
> New candidate head reviewed: `dc998e80365931b5e73508e8da3d86f91a53f3cd`
> New commits reviewed: 1 (`dc998e80365931b5e73508e8da3d86f91a53f3cd`)
> Exact CODE Actions: `35957489307` — `in_progress` at Supervisor review time; Ubuntu + Windows unit/regression jobs are still running
> Supervisor decision: **PARTIAL / EVIDENCE CLOSURE REQUIRED**
> Round 14: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. Keep the new correction; do not redesign it

The new CODE direction is accepted as **REAL_LOGIC** and should be preserved:

- `print_preview.status()` now validates into a temporary candidate and only exposes it after `latest.manifestSha256` matches the current manifest bytes;
- every caught current-pointer validation failure clears `pointer` and `m`, so public status fails closed with `generated=false`, `manifest=None`, and no usable `generationId`;
- `latest.json` is read through `_read_pointer()`, which rejects symlink/non-regular files and malformed/empty JSON;
- current generation IDs and SHA-256 values are shape-validated before use;
- model-composition status also fails closed on invalid/missing current pointer and clears invalid generation exposure;
- modern model-composition publication still requires the existing `published.json` seal; legacy no-`historyVersion` behavior remains isolated;
- the new tracked tests exercise publication-seal failures, current latest-pointer failures, coherent manifest/meta mutation, missing generation, and fresh-read fail-closed behavior.

Do **not** rewrite DAM, queue, storage, publication authority, manifest format, or generation architecture. Do not add DB/WAL/second ledger/replay/duplicate manifest.

## 1. Current gate result

No new implementation blocker was found in the reviewed diff that justifies another architecture or code refactor.

However Round 13 is **not accepted yet** because evidence closure is incomplete:

1. exact CODE Actions `35957489307` is still running; it is not evidence until both Ubuntu and Windows are `SUCCESS` on exact SHA `dc998e80365931b5e73508e8da3d86f91a53f3cd`;
2. GitHub Actions remains **MOCK regression** (`FOX3D_MOCK_BLENDER=1`), never REAL Blender / Production Ready evidence;
3. no new clean `FOX3D_MOCK_BLENDER=0`, `usedMock=false` REAL Blender acceptance exists on this exact corrected CODE;
4. no Round 13 final acceptance MD/JSON package has been published for this exact CODE;
5. no exact final DOCS SHA + dual-platform DOCS CI exists yet;
6. no `[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE` handoff exists for this corrected CODE.

Therefore: **do not make unrelated code changes while CODE CI is still running**. If the current exact CODE CI succeeds, proceed directly to evidence closure below. If it fails, fix only the concrete failing regression(s), create one new CODE SHA, and restart the closure sequence from step 1.

## 2. Required closure sequence — strict order

1. Wait for exact CODE Actions `35957489307` to finish.
2. Verify both jobs are `SUCCESS` and both checkout exact SHA `dc998e80365931b5e73508e8da3d86f91a53f3cd`.
3. Record CI as **MOCK regression only**.
4. On that exact CODE SHA, run a **new clean REAL Blender** acceptance with:
   - `FOX3D_MOCK_BLENDER=0`;
   - `usedMock=false`;
   - real Blender 5.2.1 LTS / actual available device recorded;
   - clean working tree / exact CODE SHA recorded.
5. Verify and record both authority chains separately on fresh reopen/status reads:
   - model composition: `manifest SHA == meta.manifestSha256 == published.manifestSha256`, then `latest.generationId` resolves only to that valid modern generation;
   - print preview: `manifest SHA == meta.manifestSha256 == latest.manifestSha256` and `latest.generationId` resolves to that exact generation.
6. Include one fail-closed post-completion tamper check for each public read path. These are **REAL_OS_IO_INTEGRITY** only if using actual local file bytes; injected timing/monkeypatch controls remain **MOCK / FAULT_INJECTION_CONTROL**.
7. Update only the existing PR #15 acceptance package:
   - `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
   - matching JSON evidence file if already used by this package.
8. Acceptance package must include exact CODE SHA, CODE run ID, Ubuntu/Windows result, REAL run/generation ID, Blender/device, `usedMock`, relevant SHA/size identities, fresh-read result, and truthful REAL/MOCK/PARTIAL/BLOCKED labels.
9. Freeze one exact DOCS SHA and run dual-platform GitHub Actions on that exact DOCS SHA.
10. Verify both DOCS CI jobs are `SUCCESS` and checkout the exact DOCS SHA.
11. Leave one Issue #1 handoff exactly in this form:
   - `[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 13 correction`
   - final CODE SHA
   - CODE CI run ID
   - REAL run/generation ID
   - DOCS SHA
   - DOCS CI run ID
   - short truth matrix
12. STOP. Do not begin Round 14 until Supervisor explicitly says GO.

## 3. Truth classification — unchanged

Use only truthful scoped labels:

- publication/latest identity implementation: **REAL_LOGIC**;
- GitHub Actions / pytest with mock Blender: **MOCK regression**;
- monkeypatch/timing/fault injection: **MOCK / FAULT_INJECTION_CONTROL**;
- directly observed local file identity and fresh reopen: scoped **REAL_OS_IO_INTEGRITY**;
- clean `usedMock=false` Blender output: **REAL_RENDER** only;
- hard-link / hostile concurrent-writer race not directly proven: **PARTIAL / PRESERVED UNKNOWN**;
- NAS/object storage/controller durability and hardware power-loss: **BLOCKED / NOT_TESTED**;
- physical CAD authority, physical print proof, manufacturing readiness: **BLOCKED / false**.

Never promote a green CI run, fixture, monkeypatch, or mock renderer to Production Ready.

## 4. Canonical files — do not rewrite for freshness

Do not edit these merely to refresh timestamps:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their existing boundaries remain authoritative:

- `globalProductionReady=false`;
- Mock pytest is not production evidence;
- `physicalPrintValidated=false`;
- CNC live control remains **BLOCKED**;
- Vision Judge remains **MOCK**.

## 5. Frozen boundaries

- PR #15 remains DRAFT / OPEN / unmerged.
- PR #16 remains FROZEN DRAFT.
- No merge / retarget / rebase-to-main / cherry-pick.
- Round 14 remains HOLD.
- No H3 / LTX / Vision / CNC / LASER / PLC work.
- No authority/storage architecture rewrite.
- No Mock/FIXTURE promotion to Production Ready.
- `physicalProductGeometryTruth=false`.
- `physicalPrintValidated=false`.
- `manufacturingReady=false`.
- `globalProductionReady=false`.
- `MERGE_AUTHORIZED=false`.
