# Recipe 3D 工作台：操作與程式盤點

此版本完成「現有商品資料 → 確認預覽設定 → 真實 Blender 模型與圖片 → 下載」的本機操作流程。入口為 http://127.0.0.1:8790/admin/recipes，尚未部署至供應商官網。

## 不需要寫程式的操作

1. 雙擊桌面「收納王妃 Recipe 3D 工作台」。啟動器會在背景開啟服務，再開啟瀏覽器；服務已執行時會直接進入畫面。
2. 在左側選擇商品，預設顯示「3D 預覽與下載」。先閱讀預覽設定中的暫用板厚、背板、門縫與結構簡化。
3. 若要修改尺寸，切換「規格與缺漏」，修改並按表單底部「儲存草稿」。所有尺寸使用 mm。
4. 回到 3D 頁，按「使用以上設定生成預覽」。生成在背景執行，可切換商品或重新開啟網頁查看狀態；電腦與工作台服務需保持執行。
5. 在「互動結構預覽」拖曳旋轉、滾輪縮放；也可聚焦圖面後用方向鍵與加減鍵操作。勾選「隱藏門片查看內部」僅影響畫面，不會修改下載模型。
6. 完成後下載 PNG 圖片、GLB 模型或 Blender 專案。Blender 專案可用 Blender 開啟編輯；GLB 可供支援 glTF 的工具載入。

新增商品時先選三種支援結構之一，填外尺寸、上下行數、格位數與門片數。這不是上傳任意照片便自動重建形體的工具。圖片與網址用作參考，幾何由已儲存參數及畫面列出的假設建立。

## 三種支援結構

| 商品 | 模型配置 | 預覽板件 |
|---|---|---|
| MY-012 十二格書櫃 | 六行、每行兩格、交錯隔板、無門 | 15 件 |
| LI-D40 四門收納櫃 | 四行、每行一格及一片上下排列門片 | 12 件 |
| LI-PU63D-免組裝 六格滑門櫃 | 三行、每行兩格及一片左側滑門 | 13 件 |

上表為目前種子商品及預設預覽假設的結果。固定板 25 mm 僅套用於滑門櫃的頂、底與橫板，側板不擅自套用 25 mm。各行隔板座標可在規格欄填逗號分隔的 mm 值，由下往上，量自左側內壁至隔板中心。各行高度目前等分；圖示局部內徑保留參考，未視為已核定幾何。

模型包含實體尺寸的板件，但未模擬鉸鏈轉軸、滑軌截面、開門行程、接合、承重或實際表面紋理。材質為示意木色。預覽板件表不是裁切單，`engineeringReady` / `productionReady` 維持 false；供應商參考記錄的 `renderReady` 也不因產生預覽而升級。

## 常見狀態

| 畫面狀態 | 操作方式 |
|---|---|
| 提示缺少外尺寸或數量 | 到規格頁填妥並儲存，再回到 3D 頁 |
| 找不到 Blender | 安裝 Blender，重新啟動工作台；不會用假模型代替成功 |
| 生成中 | 可取消；若取消太晚且檔案已完成驗證，仍可能保留成功成果 |
| 規格已變更／上一版 | 渲染圖與下載檔保留上一版；互動結構顯示目前設定。重新生成以更新下載 |
| 工作台曾中斷 | 重新生成即可；之前已成功的版本保留 |
| 檔案驗證失敗 | 成果按鈕不會提供損壞檔案，請重新生成 |
| 多視窗版本衝突 | 先另存未儲存的修改文字，再重新載入最新商品 |

## 現有程式與此次完成範圍

| 區塊 | 已存在的程式 | 此次可用性結論 |
|---|---|---|
| 商品參考資料 | `catalog_recipes.py`、三款商品與來源快照 | 保留來源完整性檢查與原始規格 |
| 草稿管理 | `recipe_workbench.py`、SQLite、圖片儲存 | 原有中文 UI 可新增、編輯、驗證、上傳圖片、匯入匯出 |
| 商品轉 3D | `recipe_3d.py` | 修正欄位與各行門片，加入生成前確認、幾何驗證、版本化檔案 |
| 背景操作 | `recipe_preview_service.py`、`recipe_admin_api.py` | 加入排隊、取消、失敗與重啟恢復；沿用 Platform 執行與 DAM 儲存 |
| 操作畫面 | `static/recipe-library.*`、`recipe-viewer.js` | 加入旋轉結構預覽、真實成圖、下載與上一版提示 |
| Blender 執行 | `scripts/blender_job.py` | Recipe 專用分支匯出板件 GLB、blend、PNG 與實際幾何紀錄 |
| 啟動與驗收 | `open_recipe_studio.py`、`run_recipe_studio_e2e.py` | 桌面入口與綁定 clean CODE 的真實 HTTP / Blender 驗收 |
| 既有平台管理 | `/admin`、Queue、Worker、DAM、Digital Twins 等 | 保留原有功能；本次未宣稱所有製造或其他產品路徑已完成商用驗收 |
| GPT / Supervisor | GitHub 指令文件、Issue #1、既有 Supervisor 服務 | 10 分鐘 heartbeat 與即時 Issue 回報已使用；公開 webhook / live provider 前置條件未完成，維持既有 HOLD |

本次為使用者另行授權的 Recipe 可用化工作，不是 Supervisor 新 Phase 放行，也未修改 Scheduler、Queue、DAM 或 Engineering 權威模型。

## 保存與維護

- 預設資料根目錄：`E:\projects\sonaqueen-recipe-library\.fox3d-data`。
- `recipe-workbench/` 保存草稿、歷次版本與上傳圖片；`recipe-previews/` 保存各商品不可變的生成版本及檔案雜湊。
- JSON 匯出是草稿資料交換，不含 3D 檔、圖片位元組或完整歷次版本。重要 3D 成果請直接下載；完整搬移需先停止服務，再備份整個資料根目錄。
- 本機服務固定使用 `sonaqueen-home` 工作區；工作區欄位不是登入或權限驗證，不應直接公開網路服務。
- 桌面捷徑的程式目標為 `scripts/open_recipe_studio.py`。啟動紀錄在 `.fox3d-work/recipe-studio/server.log`；初始化失敗時啟動器會顯示可交給維護人員的紀錄位置。
- 開發者可執行 `python scripts/run_recipe_admin.py`；另外測試請指定不同資料根目錄及連接埠，例如 8792，避免占用 Supervisor 的 8791。

## 監工回報

已設定每 10 分鐘檢查 GitHub main 指令文件及 Issue #1 的 heartbeat。沒有新指令或可行動變化時保持安靜；成果完成後立即送出 Issue 回報，不等待下一輪。

真正 GitHub webhook → GPT provider → 自動發布下一輪指令的既有 Supervisor 程式仍缺公開 HTTPS webhook、HMAC 驗證金鑰、provider/model 與 live credentials、管理驗證設定。此版本未建立或讀取密鑰，也不以輪詢或 Issue 留言冒充 live provider 已啟用。
