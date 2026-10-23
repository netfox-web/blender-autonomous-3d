# Phase 1–14 集中驗收紀錄

目前狀態：`IMPLEMENTER_LOCAL_ACCEPTANCE_COMPLETE` 僅限隔離 contract／fixture／CPU logic；不是 Supervisor PASS，也不是 production readiness 聲明。

## CURRENT_TRUTH

- Repository: `netfox-web/blender-autonomous-3d`
- Base: `main@9c9f2835a35d31eea9066c1ebcafa4385f61fc14`
- Branch: `codex/issue-25-after-sales-visual`
- Primary Issue: #25；coordination: github-supervisor#134
- Open PR #16 is Draft/FROZEN. Scene/Fleet/render paths are untouched.
- Issue #1 2026-10-23 reconciliation says PR #19/Product DNA is merged. Old docs may still describe pre-merge state.
- Owner 已直接核准修改 workflow、推送指定分支、建立 Draft PR 與只執行已核實自架 CI；不含 runner registration/token/permission/hosted 費用。Repo runner registry 為 HTTP 200、`total_count: 1`，Linux runner ID 21 online。`pytest.yml` 保留事件與完整 Linux gate並移除 hosted labels；Windows 是獨立必敗 blocker，仍為 `BLOCKED/NOT_RUN`，整體不可自報 PASS。
- Commander: Grok per github-supervisor#115. Single-writer runtime lease 已於 github-supervisor#134 comment 6366590747 確認；只修改列明的隔離 owned paths。

## REUSE / EXTEND / GAP

- REUSE: `kd.py` (`instructionsV2`, graph, labels, carton contents, misassembly risk), `safety.py`, `manual_pilot.py`, Product DNA contract.
- EXTEND: new `after_sales_visual` namespace, JSON schemas, synthetic fixtures, append-only demo store, non-executable ERP draft.
- GAP/BLOCKED: approved real SKU/BOM/manual provenance, ERP readonly endpoint agreement, deidentified pilot photos, human annotation policy, real provider evaluation, approved self-hosted CI.

## Evidence classes

- `FIXTURE`: 24 synthetic cases and hashes.
- `MOCK_REGRESSION`: deterministic observation provider.
- `REAL_LOGIC`: fail-closed identity, provenance, candidate rules, idempotency, intake bounds, append-only review, draft guard.
- `REAL_CPU_SANDBOX`: 以下結果由 network-disabled、read-only source mount 的 ephemeral CPU container 執行。
- `REAL_INTEGRATION_NOT_RUN`: visual model, ERP, customer photos.
- `BLOCKED`: self-hosted CI and independent Supervisor gate.

## 2026-10-23 local isolated execution

- Fixture manifest SHA-256: `78509534856c7ee559b298d294ae129e1f1437692f18a59bb7c8ebdb30f62678` (24 cases).
- Runtime: cached `netfox-vision-api:latest@sha256:05e5e3c79e7c8e22b7bac3004a46a36eb2df4d4487d1256af3a0a17f2d9e4956`; ephemeral container, `--network none`, read-only source mount, tmpfs only.
- `python -m compileall` for the new package and tests: PASS.
- `PYTHONPATH=/workspace/src python tests/after_sales_visual/run_acceptance.py`: PASS, 24/24 expected statuses; live model NOT_RUN; external writes 0.
- 負例／相容性包含：跨 tenant 拒絕、same-hash different-case 不合併、schema/runtime shape、UNBOUND Product DNA、stale engineering version、numeric `instructionsV2.step`、遮擋照片只要求補拍而不判缺件。
- CLI 實跑 `--stop-after 5` 得 exit 75，checkpoint 保留；`--cancel` 保留 evidence；`--resume` 完成 24/24；changed-manifest resume 拒絕；重試結果冪等。
- The same runner also executed bounded existing-code smoke checks: Product DNA 1 engineering template→3 artwork hashes while engineering/manufacturing readiness remain false; existing `assembly_instruction_v2`, part labels, carton contents and `misassembly_risk` reuse all PASS.
- Bounded 24-case acceptance pass including cached-container startup: wall `2.17s`, max RSS `28,656 KB` (`/usr/bin/time`; one local observation, not an SLA).
- Targeted pytest specification exists, but pytest/ruff/mypy were NOT_RUN: host Python 3.14 has no pytest and the approved cached Python 3.12 image has none of the three binaries. The repository's full gates are therefore `BLOCKED/NOT_RUN`, not PASS. No package was installed and no hosted workflow was triggered.
- Exact checked commit SHA 由完成 commit 後的 github-supervisor#134 狀態留言記錄；舊 SHA 測試不得自動繼承。

## Rollback

All work is additive under the listed owned paths. Rollback is a normal revert of this feature commit; no migration, shared DB change, deployment, external send or production flag exists.
