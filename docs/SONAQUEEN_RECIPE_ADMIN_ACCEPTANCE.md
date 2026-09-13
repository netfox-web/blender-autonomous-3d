# Sonaqueen Recipe 後台驗收

日期：2026-09-13。範圍：本機商品參考與草稿管理後台。操作入口 `/admin/recipes`，啟動及備份方式見 [操作手冊](SONAQUEEN_RECIPE_ADMIN.md)。

## CODE 與 CI

- 功能 CODE：`295a51297bc9cc0ba06f6e5ffecb91dc5ad415c6`。
- 整合 CODE：`ae449b840acc9b6f236ab36cc3948bcaeac84c74`。合併 `origin/main`，保留新版管理台及商品 Recipe 入口。
- Actions：[34746683486](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34746683486) — **SUCCESS**，檢出 exact CODE SHA。
- Ubuntu job `103695777832` — **SUCCESS**。
- Windows job `103695777854` — **SUCCESS**。
- 本機整合版：**693 tests passed**，exit code 0；其中本次後台與 HTTP runner 專項 23 項。既有 Starlette/httpx 棄用提示不影響結果。

## 乾淨 CODE 驗收

上述兩個 CI job 成功後，在 clean working tree 執行：

```powershell
python scripts/run_recipe_admin_e2e.py --expected-commit ae449b840acc9b6f236ab36cc3948bcaeac84c74
```

- generation：`c8159dbf-1f86-40f5-8fd5-86370ad1efcf`。
- 模式：`LIVE_LOCAL_HTTP`，真實本機 HTTP 服務，獨立暫存 SQLite／圖片資料。
- 通過：三款商品／七張來源圖片雜湊；新增／編輯／版本衝突；缺漏檢查；圖片上傳／讀取與工作區隔離；匯出／匯入及重複保護；重啟服務後草稿與圖片仍保留。
- 原始供應商目錄未變更。機器可讀證據：[SONAQUEEN_RECIPE_ADMIN_ACCEPTANCE.json](SONAQUEEN_RECIPE_ADMIN_ACCEPTANCE.json)。

## 瀏覽器實際操作

使用獨立 `8791` 測試環境操作搜尋、商品編輯、資料依據、儲存、重新載入、缺漏驗證、新增商品、JPEG 上傳、JSON 下載與匯入。下載檔已在磁碟讀取並驗證商品內容；JSON 不含圖片位元組，匯入後的圖片須另行上傳。

首次操作發現整數欄位使用小數 min 造成 step 驗證失敗，已於功能 CODE 修正為整數 min，並重驗儲存成功。390 px 窄螢幕測試無水平溢出及破圖，之後恢復原視窗尺寸。新版 `/admin` 入口亦可正常跳轉。

CI 成功後再次在整合 CODE 的 clean tree 操作 LI-D40：儲存帶 CODE SHA 的測試備註為 revision 2，重開頁面確認相同備註持續存在，再驗證得到待補 4 項、無缺少依據及結構問題。此 18 mm 板厚為先前 UI 測試值，僅位於測試資料目錄，**並非商品工程確認值**。

使用者服務 `8790` 初始僅有原本三款商品，未加入 QA 商品或 QA 規格。實際使用者後續操作資料以本機資料庫為準。

## 能力邊界

本報告證明後台資料管理與保存可用，不是 REAL Blender、幾何還原或製造驗收。`engineeringReady`、`renderReady`、`productionReady` 持續為 false；不解除 Phase 961+ HOLD。先前官網來源 LIVE_HTTP 驗收獨立保留於 [供應商參考庫驗收](SONAQUEEN_RECIPE_LIBRARY_ACCEPTANCE.md)。

本文件屬 Phase 2 文件提交；文件 commit 的 exact-head CI 結果待完成後另於 PR #2 與 Issue #1 回報，不以 CODE CI 代替。
