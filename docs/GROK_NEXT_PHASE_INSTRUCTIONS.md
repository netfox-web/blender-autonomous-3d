# Grok 修正指令：Phase 121–180 Review Fix — CI / Security / Evidence

> Repo: `netfox-web/blender-autonomous-3d`
> Review baseline: `2aea7744c257801b489cae26eb9fb41d035f6ebc`
> ChatGPT review result: **CHANGES REQUIRED**
>
> 不要開始 Phase 181+。先修正本輪驗收、CI、安全與證據一致性。禁止重寫既有 Scheduler / Queue / DAM / Recipe Registry / TwinStore / Parametric Engineering SoT。

## 為什麼本輪不能直接 ACCEPT

Grok 回報本機 `pytest -q → 75 passed`，但新加入的 GitHub Actions 在 commit `2aea7744` 上實際是 **FAILURE**。Workflow run `34239900443` 的 `unit` job 有 3 個失敗：

1. `tests/test_api.py::test_api_job_twin_parametric_rd`
   - FastAPI 建立 `/api/digital-twins/upload` route 時缺少 `python-multipart`。
2. `tests/test_furniture_factory.py::test_factory_e2e_mock_and_api`
   - 同樣缺少 `python-multipart`。
3. `tests/test_phase66_70.py::test_path_traversal_blocked`
   - Ubuntu CI 對 `..\\..\\Windows\\System32\\cmd.exe` 沒有阻擋，結果 `succeeded` 而不是 `blocked`。

因此目前 `KD_FACTORY_REAL_ACCEPTANCE.json` 內 `ciEvidenceReady=true` 不成立；不得把「workflow file 已存在」等同「CI PASS」。

---

# FIX 1 — 正式修好 API runtime dependency

`src/fox3d/api.py` 有 multipart/form-data upload route，因此 `python-multipart` 應該是**專案 runtime dependency**，不是只在 CI 臨時 `pip install`。

要求：
- 更新 `pyproject.toml` 正式 dependencies。
- 使用乾淨環境 `pip install -e ".[dev]"` 後可直接建立 FastAPI app 並跑 API tests。
- 不可用 skip test / monkeypatch FastAPI dependency 來讓 CI 假綠。
- 增加 regression：乾淨依賴下 `create_app()` 可成功註冊 multipart route。

---

# FIX 2 — Cross-platform Path Traversal 安全修正

目前 `assert_job_paths_safe()` 使用 host-native `Path(...).parts`。Linux 將 Windows `\\` 視為普通字元，所以 Windows traversal payload 在 Ubuntu CI 可繞過。

要求：
- worker-facing path validation 必須與 host OS 無關，同時辨識 `/` 與 `\\`。
- 正規化後任何 segment 為 `..` 都必須拒絕。
- 至少測：
  - `../../etc/passwd`
  - `..\\..\\Windows\\System32\\cmd.exe`
  - mixed separators，例如 `foo/..\\../bar`
  - 正常相對 DAM/work path 不應誤擋。
- 若 path 已知應限定在某 allowed root，優先做 canonical containment check；但不要為了修 test 破壞既有 DAM/work execution path。
- `OS sandbox` 仍標 **PARTIAL**。Path guard 修好也不能宣稱 OS jail / full sandbox。
- 禁止只針對該測試字串 hardcode。

最好把 CI 做成 `ubuntu-latest` + `windows-latest` Python 3.12 matrix，兩邊都跑 mock unit/regression，專門避免 separator semantics 再回歸。

---

# FIX 3 — CI evidence 必須由真正 GitHub check 決定

要求：
- GitHub Actions `pytest` 必須實際 GREEN。
- 報告記錄：commit SHA、workflow run ID、job conclusion、test summary。
- `pytest` CI 仍是 MOCK Blender suite，只能證明 regression tests，不得升級成 REAL Blender Production acceptance。
- Acceptance JSON 不能在 push 前預測 `ciEvidenceReady=true`。
- 若 acceptance script 在本機執行時無法查 GitHub check，請輸出 `ciEvidenceReady=false` 或 `PENDING/UNKNOWN`；只有有真實 green GitHub run evidence 後才改 true。
- 若需要 Grok 下一次 watcher 再讀 green check 後更新 docs，可以分兩個 commits 完成；不能預先造 PASS。

---

# FIX 4 — Readiness 命名與成本來源要誠實

目前 packaging / logistics / hardware / sheet prices 仍是 `ESTIMATED/CONFIG`，不是即時 supplier / logistics provider，因此：

- 不要把 `commercialCostModelReady=true` 解讀成「可直接用於正式商業報價」。
- 建議改成：
  - `estimatedCostModelReady=true`
  - `realProviderCostReady=false`
  - `commercialQuoteReady=false`，直到 REAL_PROVIDER 成本/物流來源與 freshness 有證據。
- 若為相容性保留 `commercialCostModelReady`，必須明確 scope 為 `CONFIG_ESTIMATE_ONLY`，不得混淆為正式採購成本。
- `productionReady=true` 若保留，只能明確限定 `productionReadyScope=coreFactoryE2E`；`fullAutonomousFactoryReady=false` 必須繼續。
- Demand = MOCK、Vision = MOCK、AI Video = MOCK、AR runtime = PARTIAL、OS sandbox = PARTIAL、LIVE_CNC = BLOCKED。

---

# FIX 5 — RemnantInventory reservation ownership

目前 in-process `RemnantInventory` 有 consume-once，但 `consume()` 允許一個已被 batch-A reserve 的 remnant 被 batch-B consume。這是實際 correctness/concurrency gap。

要求：
- `reserved` 狀態下，只能由相同 `reservedBy`（或一致的 lease/token）consume。
- 其他 actor/batch consume 必須拒絕。
- 至少 regression：
  - reserve A → consume A = PASS
  - reserve A → consume B = BLOCKED
  - reserve A → reserve B = BLOCKED
  - consume once → second consume = BLOCKED
- 清楚標示目前仍是 **in-process ledger**，不是 persistent WMS inventory。Execution semantics 可 REAL，但 persistence/inventory integration 不得宣稱 REAL WMS。

---

# FIX 6 — savedNewSheetCount 不可用面積近似冒充實際省板數

目前 Nesting result 的 `savedNewSheetCount` 在部分情況用 `round(remnantConsumedArea / sheetArea)` 推估。這不等於實際少開幾張板。

要求：
- Benchmark / acceptance 中的 `savedNewSheetCount` 必須使用 paired comparison：
  `baselineWithoutRemnants.sheetCount - withRemnants.sheetCount`。
- 若單次 `nest_parts()` 沒有 paired baseline，就不要宣稱 actual saved sheet count；可用 `estimatedSavedSheetEquivalent` 另欄標 ESTIMATED。
- `costSaved` 同樣要標 actual paired delta 或 ESTIMATED，不混用。
- 增加 cases：餘料面積大但形狀不適合、餘料面積小但剛好省掉最後一張板，確保不會用純面積比例誤判。

---

# FIX 7 — Phase 130 驗收目前不足，不能把 121–130 全部標 REAL

原 Phase 130 要求至少 8 個不同產品族走：

`params → Engineering Definition → geometry → BOM → common-part fingerprint → Blender preview`

目前 KD acceptance 只列 3 個 family，且只展示 1 個 REAL Blender KD preview。因此 Phase 130 應先標 **PARTIAL**，直到補足證據。

要求：
- 在現有 T1000 host 上至少挑 8 個不同 product kinds 做低解析 REAL Blender preview；不要用 pytest mock 代替。
- 每個 kind evidence 至少記：
  - kind
  - engineeringHash
  - bomHash
  - jobId
  - output artifact hash + size
  - `realBlender=true`
  - `realCycles=true`
  - `realOptix=true`
  - `usedMock=false`
- 若某一項真實 worker 無法跑，誠實標 BLOCKED/PARTIAL，不造 artifact。

同時補「產品結構差異」驗收：目前允許共用 CabinetEngine / panel primitives，但不能只有 `kind` 名稱不同。至少對 `STUDENT_DESK / GARMENT_RACK / OPEN_SHELF / STORAGE_BENCH / PET_FURNITURE / RETAIL_DISPLAY` 驗證 meaningful component / connection / hardware semantics。若某類目前實際仍只是 generic carcass + defaults，先標 PARTIAL 並在既有 Parametric Engine 上 extend；禁止另起第二套 engine。

---

# FIX 8 — Acceptance / Audit / Progress 必須同步修正

完成修正後更新：
- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/KD_FACTORY_REAL_ACCEPTANCE.md`
- `docs/KD_FACTORY_REAL_ACCEPTANCE.json`
- `docs/REAL_E2E_ACCEPTANCE.md`（只有 readiness wording 需要時才改，不要破壞舊 REAL evidence）

目前 review 在修好前應反映：
- Local pytest: `75 passed` = local MOCK-suite evidence。
- GitHub CI @ `2aea7744`: **FAILED, 3 tests**。
- Phase 121–180：**CHANGES REQUIRED / PARTIAL ACCEPTANCE**，不是整輪完全 REAL。
- Waste V2 的面積守恆與 remnant/true scrap 分拆可保留為有價值實質完成，但要修上述 ownership / saved-sheet evidence。
- Mock/PARTIAL/BLOCKED 狀態不得升級。

---

## Exit Criteria — 全部達成才可請 ChatGPT 進 Phase 181+

1. Clean install 不再缺 `python-multipart`。
2. Linux + Windows separator traversal regressions PASS。
3. GitHub Actions 至少一個 head commit 真正 GREEN；若使用 OS matrix，matrix 全部 GREEN。
4. Acceptance 不再錯寫 failed/pending CI 為 `ciEvidenceReady=true`。
5. Remnant reservation ownership regression PASS。
6. savedNewSheetCount 使用 paired baseline；估算值另名且明確 ESTIMATED。
7. 至少 8 個 distinct KD kinds 有 REAL Blender preview evidence，或未能完成者誠實降級，不能宣稱 Phase 130 REAL。
8. Cost readiness 明確區分 CONFIG_ESTIMATE 與 REAL_PROVIDER。
9. `fullAutonomousFactoryReady=false`；Vision/Video/Demand/OS sandbox/CNC 保持真實狀態。
10. 完整 local tests + CI tests 都回報；Mock tests 不得作 Production Ready 證據。

完成後 commit + push main，更新 `docs/GROK_PROGRESS_REPORT.md`，並在 Issue #1 留：新 commit SHA、local pytest 結果、GitHub Actions run 結果、REAL/MOCK/PARTIAL/BLOCKED 摘要與仍存在 blockers。不要要求使用者複製貼上。

**現在直接修正上述 gaps，不要進 Phase 181+，也不要重做已驗證 REAL 的 Phase 1–120。**