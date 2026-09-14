# Recipe 3D 工作台驗收

使用者要求完成現有商品 Recipe → 3D 的中文操作流程，並沿用每 10 分鐘指令巡檢及 Issue #1 即時回報。此紀錄只驗收本機商品預覽，不宣告工程核定、製造放行或 Supervisor LIVE E2E 通過。

## CODE 與 CI

- 最終 CODE：`d2db1155ef1690633230028a982dcfaa1391fc01`（包含 UI 主實作 `ed231043677e176bd79a6ad5e96ce9b105bd4fc8`）。
- CODE CI：[34796953280](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34796953280)，兩個 OS 均 SUCCESS，各 787 項測試通過，已核對測試紀錄的 787 個成功測試標記。
- Ubuntu job：103831790002；Windows job：103831790137。
- 舊 CODE 的 CI 34796329488 已取消並由上述修正版取代，不計入通過證據。
- 本機完整回歸在後補兩項案例前為 785 passed；後續 43 項 Recipe / UI / API 針對性測試通過，最終 CI 完整收集及執行 787 項。

## clean CODE 真實驗收

- Generation：`e2089521-ff0e-465e-84de-4c335caed14c`。
- `evidenceCodeCommit=d2db1155ef1690633230028a982dcfaa1391fc01`、`workingTreeClean=true`、`developmentOnly=false`。
- 執行：`python scripts/run_recipe_studio_e2e.py`；CODE 雙 OS CI 通過後才啟動，HTTP 服務使用獨立驗收資料根目錄。
- 結果：PASS；真實 Blender 5.2.1 LTS / Cycles / OptiX，`usedMock=false`。
- 三款均核對實際 Blender 板件尺寸與位置、800 × 800 PNG、GLB 板件數及檔案結構、blend 檔案可重新開啟、HTTP 下載，以及重啟後 generation 不變且檔案仍通過雜湊驗證。

| SKU | 板件數 | 實際產出 |
|---|---:|---|
| LI-D40 | 12 | PNG、GLB、blend、實際幾何紀錄 |
| LI-PU63D-免組裝 | 13 | PNG、GLB、blend、實際幾何紀錄 |
| MY-012 | 15 | PNG、GLB、blend、實際幾何紀錄 |

檔案 SHA-256、大小及各商品 generation 見 [機器可讀紀錄](SONAQUEEN_RECIPE_STUDIO_ACCEPTANCE.json)。完整本機產物位於 `.fox3d-work/recipe-studio-e2e/e2089521-ff0e-465e-84de-4c335caed14c/`。先前 `e735a94b-5c38-4ee4-a448-c5f4f30735ed` 為 dirty tree 開發檢查，未取代本次正式證據。

## 瀏覽器操作核對

已使用 Codex 瀏覽器實際操作生成三款商品、在背景生成時切換商品、拖曳旋轉、隱藏門片查看內部，以及重新載入後查看下載入口。另在 8792 獨立測試資料區將 LI-D40 寬度改為 500 / 501 mm，驗證草稿儲存、上一版提示與取消生成後保留先前成果；8792 已停止。

UI 核對發生於 `ed23104` 的畫面版本，記錄保留該 SHA；最終 `d2db115` 僅補強損壞檔案的失敗狀態並通過針對性測試。使用者 8790 服務已重啟載入最終 CODE，三款使用者草稿仍為原始版本 0。

## 使用入口與範圍

- [本機工作台](http://127.0.0.1:8790/admin/recipes)；桌面「收納王妃 Recipe 3D 工作台」捷徑。
- [操作手冊與程式盤點](SONAQUEEN_RECIPE_STUDIO.md)。
- 模型含預覽假設、示意材質與簡化五金，板件表非裁切單；`engineeringReady=false`、`productionReady=false`。
- 每 10 分鐘 heartbeat 已設定，進度已即時回報 [Issue #1](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5657822100)。無新指令時保持安靜。
- 本工作來自使用者直接授權，不偽造 Supervisor 的 instruction/code/docs/evidence lineage。既有 Supervisor LIVE webhook/provider 前置條件與 Phase 961+ HOLD 維持原狀。

本文件與 JSON 為 Phase 2 DOCS 提交內容。DOCS 自身 SHA 及其 CI run ID 於完成後回報 Issue #1，避免在尚未成功時寫入未來的 CI 結果或以自我引用造成反覆文件提交。
