# Development Agent 指令：PR #15 Round 10 — ARTIFACT PUBLICATION CORRECTION / EVIDENCE CLOSURE

> Supervisor checkpoint: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 9B CODE: `87ea4d3ba753c811f693cec8f4a3f465aca94364`
> Accepted Round 9B DOCS: `14a2c83528b3a0d76c0ec71a51afa40cc443e30b`
> Reviewed Round 10 CODE: `e128c44484bf8f8939a5725fb80306b0e8f5c376`
> Reviewed CODE Actions: `35170538114` — **IN_PROGRESS / NOT ACCEPTANCE EVIDENCE at review time**
> Supervisor decision: **CHANGES REQUIRED / ROUND 10 CORRECTION AUTHORIZED**
> Round 11: **HOLD**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. What is accepted vs not accepted

The direction in `e128c444...` is partially correct and must be retained unless a concrete defect requires a minimal change:

- shared `durability.publish_binary()` uses a target-bound same-directory temp;
- bytes are streamed to temp, host-flushed, then atomically replaced and containing namespace sync is requested;
- post-replace namespace-sync failure propagates `CommitIndeterminate` rather than returning success;
- worker-origin files in `model_compositions.generate()` and `print_preview.generate()` no longer use direct `shutil.copy2(..., final_name)`.

This is **not yet Round 10 acceptance**. Do not mark `e128c444...` READY merely because its CI eventually turns green.

Truth labels remain strict:

- durability/verifier/order code: **REAL_LOGIC** only after exercised evidence;
- actual host flush on a named tested surface: **REAL_OS_IO_FLUSH**;
- actual killed child + fresh reader: **REAL_PROCESS_RECOVERY**;
- monkeypatch/injected I/O failures and ordinary CI render fixtures: **MOCK / FAULT_INJECTION_LOGIC**;
- post-namespace sync failure with a possibly visible valid final: **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
- hardware power cut/reset/controller-cache survival: **BLOCKED / NOT_TESTED**;
- `physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`.

No architecture rewrite. No DB/WAL/second manifest/second authority/replay engine.

---

# 1. Blocker A — manifest-authoritative derived PNGs still write directly to final names

The reviewed CODE still contains two direct final-name image writes that are inside the generation authority set and are also Blender inputs:

### `src/fox3d/print_preview.py`

`prepare()` currently does the equivalent of:

```python
target = folder / name
trim.save(target, format='PNG')
```

`validate()` later includes each placement `source.name` in the exact expected manifest file set and hashes those bytes. Therefore this is not disposable scratch data.

### `src/fox3d/model_compositions.py`

`prepare()` currently does the equivalent of:

```python
image.crop(box).save(target / name, 'PNG')
```

Those bytes become `source.fileSha256`, `imagePath`, Blender artwork input, and later a manifest-authoritative file.

**Required correction:** remove the direct-final write window for these generated PNGs.

Use the same Round 10 invariant as worker binaries:

1. create an exact target-bound same-directory temp;
2. write the PNG to that temp — never write the final name first and then copy it;
3. flush runtime buffering and the actual host file handle;
4. optionally verify the generated PNG can be reopened/decoded where practical;
5. atomically replace the final target;
6. synchronize the containing directory with the existing Round 9B primitive;
7. compute/store the SHA only from the bytes that became the final artifact;
8. propagate `CommitIndeterminate` after namespace mutation; do not continue into Blender/manifest/publication from that failing call;
9. never adopt unknown temp debris and never broad-sweep `*.tmp`.

Prefer one small reusable durability helper (for example a producer/callback or bytes publication variant) rather than duplicating fsync/FlushFileBuffers logic. Do not change DAM, queue, renderer, Product Master, PreviewOwnership, generation identity, manifest schema, or publication protocol.

---

# 2. Blocker B — mandatory Round 10 crash-window baseline evidence is still missing

Before claiming the correction closes the gate, run the original required baseline against a clean detached checkout of the **accepted CODE `87ea4d3...`**, not the modified CODE.

Use actual fresh child processes and real filesystem I/O for all four windows:

### A — kill during binary/derived artifact materialization

Prove fresh readers do not report the generation available, do not adopt partial/temp bytes, and do not disturb an older valid generation.

### B — kill after artifact final bytes exist but before manifest/meta authority

Prove loose complete files alone do not create publication authority.

### C — kill after manifest/meta but before the existing final publication boundary

For `model_compositions`, prove absence of `published.json` prevents availability where that seal is required. For `print_preview`, preserve its existing protocol; do **not** invent a `published.json` if that path currently uses validated manifest/meta + `latest.json` as its publication boundary. Prove only the actual existing authority chain.

### D — publication / latest-pointer boundary

Prove a committed immutable generation is not corrupted by a failed/stale `latest.json` update, and that fresh readers do not duplicate render/publication or rewrite history.

Record PIDs, kill point, files present, SHA/size, prior-generation bytes, fresh-reader result, verifier result, and whether any automatic replay/adoption occurred.

These process-kill probes are **REAL_PROCESS_RECOVERY**, not power-loss evidence.

---

# 3. Blocker C — current focused tests are insufficient and one failure label is misleading

The current `tests/test_binary_publication.py` is useful unit/fault coverage but is not the required A–D process evidence.

Correct the semantic naming/expectation around the test that monkeypatches `namespace_committed()` after `os.replace()`: this is a **post-namespace-mutation sync failure**, not a pre-namespace failure. The valid contract is:

- current call raises `CommitIndeterminate` and returns no success;
- a complete final may already be visible;
- no later publication step is allowed from the failed call;
- later fresh readers use the unchanged verifier;
- this remains **MOCK / FAULT_INJECTION_LOGIC** for the injected error and **PARTIAL / COMMIT_INDETERMINATE_DURABILITY** for the outcome model.

Add a distinct pre-replace/file-flush failure case proving old final bytes remain absent/unchanged.

Add focused regressions for the newly corrected generated-PNG path:

- interruption during PNG temp write leaves no valid publication;
- truncated/corrupt PNG cannot satisfy the full generation verifier;
- temp from another generation is never adopted;
- wrong SHA / wrong size / swapped artifact / cross-generation artifact / stale artifact fail closed;
- corrupted BLEND/PNG/GLB/geometry/golden-observation fail closed when manifest-authoritative;
- `CommitIndeterminate` stops before manifest/published/latest advancement;
- latest-pointer failure does not duplicate a generation;
- prior Round 6–9B ownership, strict identity, temp-debris, and durability tests remain green.

If DAM metadata already exposes an immutable expected SHA/size for a worker artifact, pass that existing expected identity into `publish_binary()` and test mismatch. If it does not, **do not invent a second digest authority**; document that final-path re-hash + existing manifest/full verifier remains the authority.

---

# 4. Exact CODE gate after the correction

After the minimal correction only:

1. freeze one exact final Round 10 CODE SHA;
2. run focused Round 10 tests on Windows and Linux;
3. run the full local suite;
4. run GitHub Actions on the exact final CODE SHA;
5. Ubuntu + Windows must both complete `SUCCESS` on that exact SHA;
6. record exact run ID and pass/skip counts;
7. an earlier green run, including `35170538114` on `e128c444...`, must not substitute for the final corrected CODE gate.

If exact CI fails, fix only the concrete defect and restart the exact CODE gate. Do not stack speculative changes while CI is running.

---

# 5. Clean REAL Blender acceptance

Only after exact corrected CODE dual-platform CI is green, run a new clean acceptance bound to that exact CODE:

- `FOX3D_MOCK_BLENDER=0`;
- Blender 5.2.1 LTS + OptiX;
- `usedMock=false`;
- clean working tree;
- current synthetic/static fixture scope only;
- at least two variants;
- real manifest-authoritative PNG/BLEND/GLB/geometry/golden-observation bytes;
- SHA/size checks and PNG/BLEND reopen/finite checks;
- restart/history/download and publication-lineage checks;
- no duplicate publication;
- no debris adoption/replay;
- Round 9B durability gates retained.

This can be **REAL_RENDER** for the render path and **REAL_OS_IO_FLUSH** only for host operations actually exercised. It is not physical product, print, manufacturing, NAS durability, or power-loss evidence.

---

# 6. Evidence closure

Update the existing authority package only:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Include:

- accepted Round 9B baseline CODE/DOCS;
- A–D baseline results on exact `87ea4d3...`;
- reviewed incomplete CODE `e128c444...` and why it was not accepted;
- exact corrected CODE SHA;
- exact CODE Actions run/results/counts;
- exact changed files;
- actual process/OS evidence separately from fault-injection evidence;
- clean REAL acceptance ID and artifact SHA/size/verifier results;
- remaining PARTIAL/BLOCKED items;
- exact DOCS SHA and exact DOCS dual-platform CI.

Do not rewrite `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md`, or `CABINET_REAL_ACCEPTANCE.md` just to look current. Change a canonical/historical document only if an existing declared truth has become factually false.

---

# 7. Final handoff gate

After final CODE + clean REAL + acceptance docs are complete:

1. freeze exact DOCS/head SHA on PR #15;
2. run exact DOCS GitHub Actions;
3. Ubuntu + Windows both `SUCCESS` on that exact SHA;
4. verify checkout/head SHA exactly;
5. leave exactly one Issue #1 handoff headed:

`[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 10 artifact publication durability`

The handoff must include final CODE SHA, CODE Actions, clean REAL ID, DOCS SHA, DOCS Actions, A–D summary, REAL/MOCK/PARTIAL/BLOCKED matrix, `globalProductionReady=false`, `MERGE_AUTHORIZED=false`, PR #15 DRAFT/OPEN/unmerged, PR #16 FROZEN, and **Round 11 HOLD**.

Then STOP for Supervisor Re-Gate.

---

# 8. Frozen boundaries

- No merge / retarget / rebase-to-main / cherry-pick.
- PR #15 stays DRAFT / OPEN / unmerged.
- PR #16 stays FROZEN DRAFT.
- PR #13 / #14 and Issue #6 gates unchanged.
- No live H3 / LTX / Vision / CNC / LASER / PLC work.
- No architecture rewrite.
- No second authority or replay subsystem.
- No Mock/FIXTURE promotion to Production Ready.
- No physical manufacturing readiness claim.
- No hardware power-loss claim without actual destructive power/reset evidence.
- `MERGE_AUTHORIZED=false`.
- `globalProductionReady=false`.
- **Round 11 HOLD**.
