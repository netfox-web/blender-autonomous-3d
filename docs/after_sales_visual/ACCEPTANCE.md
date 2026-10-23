# Phase 1–14 集中驗收紀錄（待更新）

目前狀態：`PHASE_DONE — PENDING BATCH ACCEPTANCE` 僅限隔離 contract／fixture／CPU logic；不是 Supervisor PASS。

## CURRENT_TRUTH

- Repository: `netfox-web/blender-autonomous-3d`
- Base: `main@9c9f2835a35d31eea9066c1ebcafa4385f61fc14`
- Branch: `codex/issue-25-after-sales-visual`
- Primary Issue: #25；coordination: github-supervisor#134
- Open PR #16 is Draft/FROZEN. Scene/Fleet/render paths are untouched.
- Issue #1 2026-10-23 reconciliation says PR #19/Product DNA is merged. Old docs may still describe pre-merge state.
- CI workflow triggers on every pull request and uses `ubuntu-latest` + `windows-latest`; no approved self-hosted pool is proven for this repo. CI remains `BLOCKED` until coordinated. No PR/push should be used to consume hosted runners.
- Commander: Grok per github-supervisor#115. Runtime lease remains pending; only isolated owned paths are changed.

## REUSE / EXTEND / GAP

- REUSE: `kd.py` (`instructionsV2`, graph, labels, carton contents, misassembly risk), `safety.py`, `manual_pilot.py`, Product DNA contract.
- EXTEND: new `after_sales_visual` namespace, JSON schemas, synthetic fixtures, append-only demo store, non-executable ERP draft.
- GAP/BLOCKED: approved real SKU/BOM/manual provenance, ERP readonly endpoint agreement, deidentified pilot photos, human annotation policy, real provider evaluation, approved self-hosted CI.

## Evidence classes

- `FIXTURE`: 24 synthetic cases and hashes.
- `MOCK_REGRESSION`: deterministic observation provider.
- `REAL_LOGIC`: fail-closed identity, provenance, candidate rules, idempotency, intake bounds, append-only review, draft guard.
- `REAL_CPU_SANDBOX`: local test result will be recorded after execution.
- `REAL_INTEGRATION_NOT_RUN`: visual model, ERP, customer photos.
- `BLOCKED`: self-hosted CI and independent Supervisor gate.

## 2026-10-23 local isolated execution

- Fixture manifest SHA-256: `78509534856c7ee559b298d294ae129e1f1437692f18a59bb7c8ebdb30f62678` (24 cases).
- Runtime: cached `netfox-vision-api:latest@sha256:05e5e3c79e7c8e22b7bac3004a46a36eb2df4d4487d1256af3a0a17f2d9e4956`; ephemeral container, `--network none`, read-only source mount, tmpfs only.
- `python -m compileall` for the new package and tests: PASS.
- `PYTHONPATH=/workspace/src python tests/after_sales_visual/run_acceptance.py`: PASS, 24/24 expected statuses; live model NOT_RUN; external writes 0.
- The same runner also executed bounded existing-code smoke checks: Product DNA 1 engineering template→3 artwork hashes while engineering/manufacturing readiness remain false; existing `assembly_instruction_v2`, part labels, carton contents and `misassembly_risk` reuse all PASS.
- Bounded 24-case acceptance pass including cached-container startup: wall `2.17s`, max RSS `28,656 KB` (`/usr/bin/time`; one local observation, not an SLA).
- Targeted pytest specification exists, but pytest was NOT_RUN: host Python 3.14 has no pytest and the approved cached Python 3.12 image has no pytest. The repository's full pytest suite is therefore `BLOCKED/NOT_RUN`, not PASS. No package was installed and no hosted workflow was triggered.

## Rollback

All work is additive under the listed owned paths. Rollback is a normal revert of this feature commit; no migration, shared DB change, deployment, external send or production flag exists.
