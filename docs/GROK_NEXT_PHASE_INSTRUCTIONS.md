# Development Agent 指令：PR #15 Round 11 — DAM Artifact Source Identity Gate

> Supervisor checkpoint: 2026-09-17
> Repo: `netfox-web/blender-autonomous-3d`
> PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> Accepted Round 10 CODE: `0082b98bbaf9f233eda32a5382b9fc373f5a6236`
> Accepted Round 10 DOCS: `c95179455982d5caeb5338d0ed5603d1479408ea`
> CODE Actions: `35176969210` — Ubuntu SUCCESS / Windows SUCCESS on exact `0082b98...`
> DOCS Actions: `35178506868` — Ubuntu SUCCESS / Windows SUCCESS on exact `c951794...`
> Clean REAL acceptance: `7ba7806e-aa18-4325-8c58-e704b7d2f729` — Blender 5.2.1 LTS / OptiX / `usedMock=false`, synthetic/static variants only
> Supervisor decision: **ACCEPT WITH SCOPE / GO ROUND 11**
> Round 12: **HOLD**
> `MERGE_AUTHORIZED=false`
> `globalProductionReady=false`

## 0. Round 10 Re-Gate result

Round 10 is accepted **with scope**.

The final correction is complete:

- `0082b98...` correctly renames the namespace-sync test to **post-replace / post-namespace-mutation** semantics;
- a distinct pre-replace file-flush failure probe covers both `publish_binary()` and `publish_bytes()` and preserves the previous final with no owned temp debris;
- a service-level regression proves `CommitIndeterminate` during generated artifact publication stops before `manifest.json`, `published.json`, and `latest.json` authority advancement;
- exact final CODE Actions `35176969210` are dual-platform SUCCESS;
- clean REAL Blender acceptance `7ba7806e-aa18-4325-8c58-e704b7d2f729` ran after the final CODE gate with `usedMock=false`;
- exact DOCS Actions `35178506868` are dual-platform SUCCESS.

Truth boundary remains strict:

- real Blender output exercised in the clean run: **REAL_RENDER** only;
- actual host file / containing-directory flush on exercised local surfaces: **REAL_OS_IO_FLUSH**;
- retained actual killed-child / fresh-reader A–D probes: **REAL_PROCESS_RECOVERY / local filesystem only**;
- injected flush/sync errors and ordinary CI renderer: **MOCK / FAULT_INJECTION_LOGIC**;
- post-namespace sync uncertainty: **PARTIAL / COMMIT_INDETERMINATE_DURABILITY**;
- W2 additional hard-link ambiguity: **PARTIAL / PRESERVED UNKNOWN**;
- hardware power-cut/reset/controller-cache survival, NAS/network-filesystem durability: **BLOCKED / NOT_TESTED**;
- `physicalProductGeometryTruth=false`, `physicalPrintValidated=false`, `manufacturingReady=false`, `globalProductionReady=false`.

Do not reopen Round 10 unless a concrete regression proves this accepted scope false.

## 1. Round 11 target — bind copied worker artifacts to authoritative DAM identity

The next gate is deliberately narrow. Do **not** redesign DAM, the worker, the queue, publication authority, or the storage architecture.

Current accepted CODE has a remaining source-identity boundary:

- `platform.dam.get(assetId, tenant_id=tenant)` returns a DAM object that already carries the recorded content digest (`DamObject.sha256`);
- `durability.publish_binary()` already supports `expected_sha256` and `expected_size`;
- however `model_compositions.generate()` and `print_preview.generate()` currently call `publish_binary(source.path, target)` without binding the copy to the DAM object's recorded digest;
- therefore a DAM path whose bytes are mutated after registration can potentially be copied and then re-hashed into a new internally self-consistent manifest without proving that the copied bytes still equal the worker-returned DAM identity.

Round 11 must close that exact boundary with the smallest possible change.

## 2. Baseline first — prove the accepted CODE behavior before modifying production code

Before changing production code, use an isolated workspace against exact accepted CODE `0082b98bbaf9f233eda32a5382b9fc373f5a6236` and record a durable baseline.

Required baseline probe:

1. create/store a worker-style DAM object through the existing DAM API and record its asset ID plus authoritative stored `sha256`;
2. mutate the actual file bytes at the returned `DamObject.path` **after** DAM registration while leaving the DAM object/index metadata unchanged;
3. exercise the existing artifact-copy path used by `model_compositions.generate()` and/or `print_preview.generate()` far enough to establish whether mutated bytes can be copied into the generation folder and become part of a manifest, or whether another existing verifier stops them;
4. record exact original digest, mutated digest, final copied digest, manifest/publication presence, and verifier result;
5. use an actual filesystem mutation/read for this baseline. If Blender/worker execution is substituted, label that part **MOCK**. Do not call a monkeypatched byte mutation REAL process evidence.

Classification:

- source/code inspection: **REAL_LOGIC_AUDIT**;
- actual local file mutation and read/copy: **REAL_OS_IO_INTEGRITY** only for the exercised local surface;
- mocked worker / mocked Blender: **MOCK regression**;
- do not call this NAS, object-store, power-loss, or production storage evidence.

The baseline exists to demonstrate the boundary. Do not manufacture a failure if the existing verifier already blocks it; report the actual result.

## 3. Minimal production correction

If the baseline confirms that copied worker artifacts are not bound to the stored DAM digest, make only the minimum correction needed.

For every worker-returned DAM artifact copied into the manifest-authoritative generation folder in:

- `src/fox3d/model_compositions.py`
- `src/fox3d/print_preview.py`

bind publication to the existing DAM object's authoritative content identity.

Minimum contract:

- `expected_sha256` must come from the DAM object metadata returned for the exact worker asset ID, not from re-hashing the current source path and calling that value authoritative;
- pass that stored digest into `publish_binary(..., expected_sha256=...)` or an equivalent tiny existing-layer helper;
- if an authoritative byte size already exists in the DAM object/metadata, bind `expected_size` too. If no durable authoritative size exists, **do not invent a second size authority**; the digest is mandatory and sufficient for this round;
- malformed/missing authoritative digest for a worker-returned artifact must fail closed before manifest/meta/publication/latest advancement;
- no bool/int/string coercion tricks; validate identity fields strictly enough that malformed metadata cannot silently become accepted;
- a mismatch must preserve the previous/absent target state according to the existing `publish_binary` contract and must not advance `manifest.json`, `meta.json`, `published.json`, or `latest.json`;
- derived local preview PNGs generated by `publish_bytes()` are not worker-DAM source artifacts. Keep their current publication logic; do not create fake DAM lineage for them.

Do **not** add:

- a new DAM database or ledger;
- a second artifact authority;
- a replay/adoption subsystem;
- a new queue/state store;
- broad filesystem scans;
- architecture rewrites;
- silent fallback that recomputes expected identity from potentially tampered source bytes.

## 4. Adversarial / TOCTOU coverage

Add focused tests for the exact boundary.

Required cases:

### A. Stored digest mismatch before copy

- DAM metadata says digest A;
- on-disk source bytes are changed to digest B;
- publication fails closed;
- no valid new manifest/publication/latest authority is advanced;
- prior final, when present, remains byte-identical; otherwise target remains absent;
- owned temp is not adopted as authority.

### B. Source changes during copy

Exercise or deterministically simulate a source mutation while `publish_binary()` is streaming.

The invariant is: the digest computed from bytes actually copied must be compared against the stored DAM digest and mismatch must stop publication.

If this is implemented with monkeypatch/fault injection, classify it **MOCK / FAULT_INJECTION_LOGIC**. Only label an actual independent process mutating the file during a real copy as REAL process/OS evidence.

### C. Correct source

- stored DAM digest equals current bytes;
- publication succeeds;
- final copied worker artifact digest equals the stored DAM digest;
- manifest digest for each source-backed worker artifact equals that same digest;
- existing Blender/verifier/identity checks remain unchanged and green.

### D. Existing isolation failures remain closed

Retain and verify:

- wrong DAM asset ID fails;
- cross-tenant DAM access fails;
- missing source fails;
- symlink target remains rejected;
- wrong SHA/size keeps prior final unchanged;
- no new retry/rollback/replay behavior after `CommitIndeterminate`.

## 5. CODE gate

After the minimal correction and focused tests:

1. freeze one exact Round 11 CODE SHA;
2. run focused source-identity / binary-publication tests;
3. run the full local suite;
4. run GitHub Actions on the exact final CODE SHA;
5. Ubuntu + Windows must both finish SUCCESS and checkout the exact SHA;
6. record exact run ID and pass/skip counts.

CI remains **MOCK regression** where `FOX3D_MOCK_BLENDER=1`; do not promote CI to REAL_RENDER or Production Ready.

## 6. New clean REAL Blender acceptance on final Round 11 CODE

Because Round 11 changes the production artifact-lineage gate, run one new clean acceptance after exact final CODE dual-CI succeeds.

Requirements:

- `FOX3D_MOCK_BLENDER=0`;
- Blender 5.2.1 LTS + OptiX;
- `usedMock=false`;
- clean working tree bound to the exact final Round 11 CODE SHA;
- at least two current synthetic/static variants;
- for every worker-DAM artifact copied into the final generation, record worker asset ID, stored DAM digest, copied final digest, manifest digest, size, and equality result;
- generated preview PNGs and source-backed PNG/BLEND/GLB/geometry/golden-observation artifacts retain decode/reopen/finite checks as applicable;
- restart/history/download/publication lineage remains green;
- no duplicate publication, no temp adoption/replay;
- all prior ownership/identity/durability gates remain green.

Classify only what was exercised:

- real Blender outputs: **REAL_RENDER**;
- actual DAM-object digest-to-final-byte verification in the local run: **REAL_LOGIC + REAL_OS_IO_INTEGRITY** for that local surface;
- actual host flush: **REAL_OS_IO_FLUSH** where exercised;
- injected mutation/race: **MOCK / FAULT_INJECTION_LOGIC** unless truly cross-process;
- remote object store / MinIO / NAS immutable-source guarantee: **BLOCKED / NOT_TESTED** unless a real configured remote store is actually exercised;
- hardware power loss remains **BLOCKED / NOT_TESTED**.

Do not change the physical/manufacturing/global readiness flags.

## 7. Acceptance-document closure

Update only the existing PR #15 authority package unless a canonical statement genuinely becomes false:

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

Round 11 evidence must record:

- accepted Round 10 CODE/DOCS/CI/REAL lineage;
- exact baseline tamper probe and its actual result;
- final Round 11 CODE SHA and changed files;
- exact CODE Actions/run counts;
- source asset ID + stored DAM digest + copied digest + manifest digest equality for clean success evidence;
- adversarial mismatch/race classifications;
- new clean REAL acceptance ID;
- remaining PARTIAL/BLOCKED truth boundaries;
- exact DOCS SHA and exact DOCS dual-platform CI.

Do **not** rewrite these merely to make timestamps current:

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`

Their current boundaries remain valid: Mock pytest is not production evidence, CNC live control remains BLOCKED, Vision Judge remains MOCK, and `globalProductionReady=false`.

## 8. Final handoff gate

When Round 11 CODE + clean REAL + acceptance docs are complete:

1. freeze exact DOCS/head SHA on PR #15;
2. run exact DOCS GitHub Actions;
3. Ubuntu + Windows both SUCCESS on that exact DOCS SHA;
4. verify checkout/head SHA exactly;
5. leave exactly one Issue #1 handoff headed:

`[GROK_PHASE_COMPLETE] READY_FOR_RE_GATE — PR #15 Round 11 DAM artifact source identity`

Include:

- final CODE SHA + CODE Actions;
- baseline tamper outcome;
- new clean REAL ID;
- DOCS SHA + DOCS Actions;
- stored-DAM-digest → copied-final-digest → manifest-digest equality summary;
- REAL/MOCK/PARTIAL/BLOCKED matrix;
- `globalProductionReady=false`;
- `MERGE_AUTHORIZED=false`;
- PR #15 DRAFT/OPEN/unmerged;
- PR #16 FROZEN;
- **Round 12 HOLD**.

Then STOP for Supervisor Re-Gate.

## 9. Frozen boundaries

- No merge / retarget / rebase-to-main / cherry-pick.
- PR #15 stays DRAFT / OPEN / unmerged.
- PR #16 stays FROZEN DRAFT.
- PR #13 / #14 and Issue #6 gates unchanged.
- No live H3 / LTX / Vision / CNC / LASER / PLC work.
- No architecture rewrite.
- No second authority, storage ledger, replay subsystem, or duplicate DAM.
- No Mock/FIXTURE promotion to Production Ready.
- No physical manufacturing-readiness claim.
- No NAS/object-store durability or immutability claim without real configured evidence.
- No hardware power-loss claim without actual destructive power/reset evidence.
- `MERGE_AUTHORIZED=false`.
- `globalProductionReady=false`.
- **Round 12 HOLD**.
