# Development Agent 指令：PR #15 Round 2 Re-Gate Correction — Evidence Closure Hold

> Supervisor checkpoint: 2026-09-16
> Current main before this instruction: `29f45051cb7fc2153dca695f628bb854fc307394`
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR #15 base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> New CODE reviewed: `155fd2b602ea6d9c0519a28d28150e5d2a43b275`
> Decision: **CHANGES REQUIRED / EVIDENCE CLOSURE HOLD**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Supervisor decision

本輪有新實質 CODE。`155fd2b602ea6d9c0519a28d28150e5d2a43b275` 已對 PR #15 Round 2 做 additive durable batch-state / request-row-publication lineage hardening，方向符合上一輪 instruction，沒有重寫 Scheduler / Queue / DAM / render architecture。

靜態 code review 可接受的部分包括：

- versioned `IDENTITY_VERSION=1`；
- tenant / master / batchId / sourceRevision / immutable draft/selection lineage；
- deterministic row identity / generationId / index / SKU / scene / selectionHash；
- write-once request / row / terminal receipts；
- `model_batches.current()` 在 UI/API 前重新核對 persisted state；
- succeeded row 重新走既有 canonical published-generation verifier；
- publication / manifest / artwork / stale geometry fail-closed；
- restart / cancel / interrupted 不 replay；
- MOCK tests 明確標示不是 REAL render evidence；
- `SYNTHETIC_STATIC_FIXTURE`、physical truth 與 global Production Ready 邊界沒有被提升。

但 **Re-Gate 尚未合格**，因為 exact CODE gate 尚未閉合：

- CODE workflow run `35054721048` 對 exact SHA `155fd2b...` 的 attempt 1 為 **CANCELLED**，Ubuntu / Windows 都沒有 SUCCESS conclusion；
- Supervisor 已對同一 run 啟動 rerun；目前仍不能把 in-progress/cancelled job 當 PASS；
- 尚未看到 exact CODE dual-platform SUCCESS 後產出的 clean Round 2 REAL Blender acceptance；
- 尚未有 Round 2 DOCS/evidence SHA 與 exact DOCS Ubuntu + Windows SUCCESS；
- Issue #1 尚未有此 Round 2 的 `READY_FOR_RE_GATE` 完整 contract。

因此目前分類：

- durable batch identity / verifier implementation：**REAL_LOGIC candidate / PARTIAL until CI+acceptance closure**；
- GitHub CI Blender path：**MOCK regression only**；
- prior 6 static Blender outputs：**REAL_RENDER + SYNTHETIC_STATIC_FIXTURE**，只屬 Round 1；
- Round 2 clean REAL tamper/restart acceptance：**BLOCKED_PENDING_EVIDENCE**；
- physical CAD / print / live provider / Vision / machines / global Production Ready：**BLOCKED**。

不要為了讓 CI 變綠去新增無關功能，不要開 PR #17，也不要改寫架構。

---

## 1. 立即處理：關閉 exact CODE CI gate

以 **同一個 CODE SHA `155fd2b602ea6d9c0519a28d28150e5d2a43b275`** 完成完整 pytest workflow rerun。

必須拿到：

- Ubuntu：SUCCESS
- Windows：SUCCESS
- checkout/head SHA 都是 `155fd2b602ea6d9c0519a28d28150e5d2a43b275`

若 rerun 本身因平台/runner/人工取消而中止，可重新 rerun **同一 SHA**；不要用空 commit 或功能 commit 只為換一個綠燈 SHA。

若 pytest 真正 FAIL：

1. 只修造成 failure 的最小問題；
2. 新 CODE SHA 後重新跑 Ubuntu + Windows；
3. 在 Issue #1 明確列出原 failure 與修正；
4. 不得跳過或把 cancelled / skipped 當 SUCCESS。

CI 仍使用 `FOX3D_MOCK_BLENDER=1`，所以即使雙平台綠燈仍只能算 **MOCK/unit/regression evidence**。

---

## 2. exact CODE CI 雙綠後，跑 clean Round 2 REAL acceptance

沿用既有 `scripts/run_model_batches_e2e.py --round2`；不要建立第二套 acceptance runner。

要求：

- working tree clean；
- evidence 綁 exact CODE SHA；
- Blender 5.2.1 LTS；
- OptiX / `realOptix=true`；
- `usedMock=false`；
- 至少 2-row synthetic batch；
- 真實 artifact bytes / SHA / size；
- `.blend` reopen；
- exact request / batch / row / generation / publication lineage；
- service restart 後 completed rows 保留、未完成不 replay；
- historical non-latest generation仍可在 authority有效時下載；
- geometry stale / artwork revoke 後 unavailable；
- tamper matrix fail-closed。

Tamper matrix 至少要實際證明：

1. batchId / tenant / master / masterInputHash / revision / selectionHash tamper → BLOCK；
2. unknown/missing identity version → BLOCK；
3. row insert/delete/reorder → BLOCK；
4. duplicate/malformed generationId → BLOCK；
5. SKU / scene / row identity tamper → BLOCK；
6. request / service task/inputHash contradiction → BLOCK；
7. succeeded without row receipt → BLOCK；
8. publication seal / manifest tamper → unavailable / download blocked；
9. cancelled/interrupted 不可被 progress state 復活成 succeeded；
10. stray REAL publication 不可讓未完成 row 自動 replay 或升格 success。

`os.link` write-once 是 local trusted-filesystem behavior；不要宣稱它可抵抗 hostile filesystem owner。這個 security boundary 要在 acceptance 明寫。

---

## 3. REAL acceptance PASS 後才做 DOCS commit

更新既有：

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`
- `docs/PRODUCT_VARIANT_BATCH_GUIDE.md`（只有 operator behavior 有變才改）

文件必須分開標示：

- Round 1 REAL static-render evidence；
- Round 2 REAL_LOGIC durable-lineage acceptance；
- GitHub CI = MOCK regression；
- `inputTruth=SYNTHETIC_STATIC_FIXTURE`；
- `physicalProductGeometryTruth=false`；
- `physicalPrintValidated=false`；
- `globalProductionReady=false`。

DOCS commit 後再跑 exact DOCS SHA Ubuntu + Windows CI；兩邊都 SUCCESS 才能 `READY_FOR_RE_GATE`。

---

## 4. PR #16 必須繼續 FROZEN

PR #16 已在本 instruction 之前建立，因此不追究其存在；但目前只准 **freeze**：

- 不新增 PR #16 功能 commit；
- 不 merge；
- 不 rebase-to-main；
- 不把 PR #16 scene evidence 混入 PR #15 Round 2 acceptance；
- PR #15 Round 2 Re-Gate 完成前，不以 PR #16 宣稱新的 Supervisor acceptance。

PR #16 已存在的 living-room/kitchen scene render evidence，只保留為另一個未審範圍，不是本輪 PASS 條件。

---

## 5. Issue #6 / PR #13 / PR #14 gate 不變

- PR #14：ACCEPT WITH SCOPE / NO MERGE AUTHORIZATION；仍未在 current main。
- PR #13 Round 3B：`BLOCKED_PR14_NOT_ON_MAIN`。
- 禁止 copy/cherry-pick authority、legacy 75°、worker observation、mesh/Vision inference 當 engineering authority。
- 本輪不得產生或宣稱 DOOR_OPEN REAL evidence。

---

## 6. Final handoff contract

只有下列全部完成，才在 Issue #1 回報 `READY_FOR_RE_GATE`：

- PR #15 current head / base PR #12 relationship；
- exact CODE SHA；
- exact CODE CI run ID + Ubuntu SUCCESS + Windows SUCCESS；
- clean Round 2 REAL acceptance ID；
- Blender version/device + `usedMock=false`；
- batch identity version；
- tamper matrix摘要；
- restart / retained / historical download evidence；
- exact DOCS SHA；
- exact DOCS CI run ID + Ubuntu SUCCESS + Windows SUCCESS；
- `inputTruth=SYNTHETIC_STATIC_FIXTURE`；
- `physicalProductGeometryTruth=false`；
- `physicalPrintValidated=false`；
- `globalProductionReady=false`；
- PR #16 `FROZEN_DRAFT=true`；
- Issue #6 `BLOCKED_PR14_NOT_ON_MAIN`；
- `MERGE_AUTHORIZED=false`。

完成後 STOP for Supervisor Re-Gate。不要開新 scope、不要自行 merge。
