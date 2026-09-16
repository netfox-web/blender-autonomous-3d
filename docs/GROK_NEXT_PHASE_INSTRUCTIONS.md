# Development Agent 指令：PR #15 Static Variant Batch Round 2 — Durable Batch State / Lineage Hardening

> Supervisor checkpoint: 2026-09-16
> Current main before this instruction: `dfccd2cd750320e1ab53850bdf3093096aab3044`
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR #15 base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Reviewed CODE: `2a43d9b51001176164bd534f51b63debf3f391cd`
> Reviewed DOCS/head: `f88d5c896be424da54ab379cdd97a9dc35d08f90`
> Clean REAL acceptance: `34fbd5bf-a46d-4914-8d08-cf86e36b83bb`
> Decision: **ACCEPT WITH SCOPE / NO MERGE AUTHORIZATION**
> Global Production Ready: **false**

## 0. Supervisor decision

PR #15 的 static product variant batch slice 可接受，但只接受在以下精確範圍內：

- exact CODE `2a43d9b51001176164bd534f51b63debf3f391cd` 的 GitHub Actions `35044283265`：Ubuntu + Windows SUCCESS；CI 使用 `FOX3D_MOCK_BLENDER=1`，只算 MOCK/unit/regression evidence。
- exact DOCS `f88d5c896be424da54ab379cdd97a9dc35d08f90` 的 GitHub Actions `35045863163`：Ubuntu + Windows SUCCESS；同樣只算 MOCK/unit/regression evidence。
- clean exact-CODE acceptance `34fbd5bf-a46d-4914-8d08-cf86e36b83bb`：6 個 Blender 5.2.1 LTS + OptiX 輸出，`workingTreeClean=true`、`usedMock=false`、`realOptix=true`；所有 `.blend` reopen、artifact SHA/bytes、歷史下載、restart、geometry invalidation/restoration、artwork revocation、cross-tenant path isolation checks 有證據。
- 批次沿用既有 `RecipePreviewService` serial queue 與既有 composition/render path，沒有建立第二套 Scheduler / Queue / DAM / geometry / artwork engine。
- input truth 明確為 `SYNTHETIC_STATIC_FIXTURE`；`productionReady=false`、`physicalPrintValidated=false`，沒有把 fixture 或 Mock 升格成實體 CAD / 印刷 / Production Ready。

### Truth boundary

**REAL_RENDER**
- 本輪 clean acceptance 的 6 個 Blender 5.2.1 LTS + OptiX synthetic static renders。
- `.blend` reopen、實際 artifact bytes/SHA、real worker execution。

**REAL_LOGIC**
- batch preflight、最多 24 variants、serial queue ownership、per-row generation identity、restart/non-latest history、current geometry/artwork revalidation、historical download artifact validation、publication manifest seal。

**MOCK**
- GitHub Actions pytest Blender path與 cancellation/interruption/tamper regression fixtures；它們不是 REAL render evidence。

**PARTIAL**
- persisted batch progress/status record 目前仍是 local mutable state；`model_batches.current()` 雖註明 persisted state untrusted，但尚未完整驗證 `batchId` / master / tenant / immutable request lineage / rows identity，因此 UI/status truth 還需要 durable lineage hardening。
- cross-tenant測試證明目前 workspace/path isolation behavior，但不等於完整 production authentication/authorization security certification。
- 三個 scene preset 只是簡單展示背景，不是 furnished-room scene library。
- 目前 21 masters 中仍只有 4 available previews / 17 drafts；本輪沒有補齊缺少的真實尺寸、板厚、門片缺口、正式刀模或曲面產品 authority。

**BLOCKED**
- physical CAD / measured product geometry truth。
- physical print / RIP / calibrated UV / production color proof。
- live H3/LTX/Vision/provider。
- LIVE_CNC/LIVE_LASER/PLC/machine control。
- `globalProductionReady` / `fullAutonomousFactoryReady`。

本 acceptance **不授權 merge PR #15**。PR #15 仍 stacked on PR #12；PR #12 本身也未 merge。不要自行改 base、squash 到 main、cherry-pick 到 main 或開新的 stacked PR。

---

## 1. Issue #6 / PR #14 / PR #13 gate 必須原封不動保留

這一輪 static-batch lane 與 Issue #6 Round 3B 是不同 lane。

目前仍成立：

- PR #14 articulation authority：**ACCEPT WITH SCOPE / NO MERGE AUTHORIZATION**。
- accepted authority source 尚未存在 current `main`。
- PR #13 DOOR_OPEN Round 3B 仍為 `BLOCKED_PR14_NOT_ON_MAIN`。
- 不得 copy/cherry-pick PR #14 到 PR #13。
- 不得使用 legacy/default 75°、worker observation、mesh/Vision inference 當 articulation engineering authority。
- 不得產生 DOOR_OPEN REAL evidence，直到 accepted authority 經授權真正進 main。

PR #15 Round 2 禁止修改 PR #13 / PR #14，禁止藉 static product work 繞過此 gate。

---

## 2. Round 2 只在既有 PR #15 做 durable batch-state / lineage hardening

不要開 PR #16。只在 `codex/product-variant-batches` 上做最小 additive hardening。

不要重寫：

- `RecipePreviewService`
- Scheduler / Queue / DAM
- Product master / category tree
- composition/render engine
- Artwork Placement
- Product Truth / Render Pack
- existing PR #15 UI flow

### 2A. Durable batch identity contract

目前 mutable batch record 至少含 `batchId`, `masterInputHash`, `sourceRevision`, `selectionHash`, rows；但 read path 必須把這些當 untrusted persisted data。

建立/強化一個明確、versioned 的 batch identity contract。至少綁定：

- tenant identity
- master/model ID
- `batchId` == outer service `taskId`
- batch schema/version
- `masterInputHash`
- master revision at submit
- immutable selection/request hash
- exact row count
- 每 row 的 immutable `generationId`
- 每 row 的 SKU / scene / selection identity
- row ordering/index

不要用「單一 stored hash 自己證明自己」當 authority。Verifier 必須能從 submit-time immutable request snapshot / existing canonical selection data 獨立重算應有 identity，並與 mutable progress state 比對。

如果現有 architecture 已有可重用的 canonical request/state persistence helper，直接 reuse；不要造第二套 state engine。

### 2B. `model_batches.current()` fail closed

`current()` 必須在把 persisted batch state交給 API/UI 前做 exact validation。

至少以下情況要 fail closed，不能顯示成成功批次：

- `batchId != taskId`
- wrong master / wrong tenant binding
- missing/unknown version
- row count mismatch
- duplicate `generationId`
- malformed/invalid generation UUID
- row SKU / scene / immutable selection identity mismatch
- selection/request hash mismatch
- reordered/inserted/deleted rows
- mutable state偽造 `succeeded`，但該 row 沒有可驗證的 exact generation publication
- persisted state truncation / invalid JSON / missing required identity fields

Fail closed 可以回傳明確 `corrupt/interrupted/failed` 狀態或讓 API 回可操作錯誤，但不可把 tampered state 當 completed truth。

### 2C. Completed-row truth must come from published generation evidence

對 `succeeded` row，不得只相信 batch state 字串。

必須使用既有 `compositions.generation(...)` / publication validation path（或等價既有 canonical verifier）核對：

- exact generationId
- exact masterId / current master input identity
- artifact manifest integrity
- `published.json` publication seal（對 historyVersion 1）
- current artwork classification/permission

如果 row state 說 succeeded，但 publication missing / unpublished / corrupted / wrong master / revoked/stale，batch status 必須 fail closed或至少該 row不可宣稱 succeeded/available。

不要重複實作 artifact verifier；reuse existing `compositions.generation(...)` / `print_preview.validate(...)`。

### 2D. Restart / cancellation semantics

維持現有規則：

- completed rows 保留；
- queued/running rows在服務中斷後不能自動 replay；
- cancellation不得讓尚未完成 row變成 success；
- interrupted/cancelled batch不得因 stray manifest / tampered state復活成 completed；
- restart後 UI 要可清楚區分 succeeded / failed / interrupted / cancelled。

若需要持久化 transition，只做 additive state metadata；不要另造 worker queue。

---

## 3. Required negative / adversarial tests

新增 focused tests，至少涵蓋：

1. batch file `batchId` 改成別的 task ID → BLOCK。
2. tenant/master identity tamper → BLOCK。
3. masterInputHash / sourceRevision / selectionHash tamper → BLOCK。
4. row 插入、刪除、重排 → BLOCK。
5. duplicate generationId / malformed generationId → BLOCK。
6. SKU / scene 改寫但 generationId 不變 → BLOCK。
7. row 偽造 `succeeded`，但沒有 published generation → 不得成功。
8. publication seal / manifest SHA tamper → 不得成功/下載。
9. completed row 指向另一 master 的 generation → BLOCK。
10. artwork revoked / geometry stale 後，batch history/status不可仍宣稱 downloadable current result。
11. cancelled/interrupted persisted record改成 succeeded → BLOCK。
12. valid historical non-latest completed generation仍可正常讀取與下載。
13. service restart後 completed保留，未完成不 replay。
14. existing single-composition flow完全不退化。
15. existing category tree / 4 available preview / 17 draft inventory semantics不被改寫。

Mock tests 必須明確標 MOCK regression，不得用作 REAL Blender acceptance。

---

## 4. CODE → REAL → DOCS gate order

嚴格依序：

1. fetch PR #15 exact current head；確認沒有誤動 PR #13/#14。
2. implementation minimal hardening on PR #15 only。
3. focused tests + full `pytest -q`。
4. freeze new CODE SHA。
5. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS。
6. clean exact-CODE REAL acceptance：至少跑一個 2-row synthetic batch，必須 real Blender 5.2.1 LTS + OptiX / `usedMock=false`，再驗證 restart + retained history + state tamper fail-closed；若既有 runner 可安全擴充就 reuse，不要造平行 acceptance framework。
7. REAL evidence 要包含 exact CODE、`workingTreeClean=true`、artifact SHA/bytes、BLEND reopen、publication identity、batch identity、representative tamper results。
8. 再 commit DOCS/evidence。
9. exact DOCS SHA Ubuntu + Windows CI SUCCESS。
10. Issue #1 回報 `READY_FOR_RE_GATE` 並 STOP。

若任何 gate 失敗：回報精確 `CHANGES_REQUIRED` / `BLOCKED` 原因，停止，不得把 Mock/FIXTURE補成 Production Ready。

---

## 5. Documentation / truth labels

更新：

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`
- `docs/PRODUCT_VARIANT_BATCH_GUIDE.md`（只有 operator behavior 真有變才改）
- 可更新 agent progress/handoff 文件，但不要把 historical Supervisor docs 改寫成假最新 truth。

只有在 scoped readiness 真有改變時才動 `docs/REAL_E2E_ACCEPTANCE.md`。

`docs/CABINET_REAL_ACCEPTANCE.md` 不得因 static batch feature 改動，除非 cabinet engineering truth真的變更。

不要把 historical legacy 75° articulation描述成目前 Round 3B engineering authority。

---

## 6. Final handoff contract

Issue #1 最終至少回報：

- PR #15 current head / base PR #12 relationship
- new CODE SHA
- new DOCS SHA
- exact CODE CI run + Ubuntu/Windows conclusion
- exact DOCS CI run + Ubuntu/Windows conclusion
- clean REAL acceptance ID
- Blender version/device / `usedMock=false`
- batch identity contract/version
- tamper matrix結果
- retained/history/download/restart結果
- `inputTruth=SYNTHETIC_STATIC_FIXTURE`
- `physicalPrintValidated=false`
- `physicalProductGeometryTruth=false`（或等價明確聲明）
- `globalProductionReady=false`
- Issue #6 `BLOCKED_PR14_NOT_ON_MAIN` 仍維持
- `MERGE_AUTHORIZED=false`

完成後 STOP for Supervisor Re-Gate。不要開下一個 stacked PR，不要自行 merge。
