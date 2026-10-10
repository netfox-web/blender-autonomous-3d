# 三層櫃 Golden Product

這個工作台把同一套櫃體配方與 Artwork 版本分開，供四個 SKU 共用。使用者可選擇圖稿版本、生成真實 Blender 預覽、旋轉結構、取消背景工作，以及下載圖片、模型與每門裁圖。成果用途為 **商品預覽與數位圖稿定位校驗**，尚未取得工程／製造放行。

來源指令：[Issue #4](https://github.com/netfox-web/blender-autonomous-3d/issues/4)。配方 ID：`THREE_TIER_DOOR_CABINET_424x295x900_V1`。

## 不懂程式碼也能操作

1. 雙擊桌面「收納王妃 Recipe 3D 工作台」，或開啟 [本機 Recipe 庫](http://127.0.0.1:8790/admin/recipes)。
2. 點「開啟三層櫃 Golden Product」，進入 [三層櫃工作台](http://127.0.0.1:8790/admin/recipes/golden)。
3. 選擇 KU002101、KT015101、CN003701 或 PN010201。
4. 選擇 Artwork 版本。「歷史原稿」目前會顯示 BLOCKED；可選「三門連續校驗圖」或「三門獨立校驗圖」驗證流程。這些是 FIXTURE 校驗圖，並非該商品的原始外觀。
5. 閱讀尺寸、板厚與五金的狀態，勾選預覽假設確認，再按「生成真實 3D 預覽」。背景工作可取消，完成的上一版會保留。
6. 上方結構圖可拖曳旋轉、滾輪縮放、方向鍵操作，或隱藏門片。它不顯示 Artwork；貼圖以 Blender 產出的三個視角為準。
7. 下載 PNG、GLB、Blender 原檔、驗證紀錄 JSON，或各門片校驗裁圖。切換 Artwork 後若未重新生成，畫面會明示「上一版成果」。

服務關閉時請使用桌面捷徑重新啟動。網址只在執行工作台的電腦上有效。

## Truth Matrix

| 項目 | 狀態 | 依據／限制 |
|---|---|---|
| 424 × 295 × 900 mm、三層三門 | CONFIG | Issue #4 提供的尺寸，非實體量測證書 |
| 側板、橫板、門板 15 mm，背板 3 mm | ESTIMATED | 尚無已驗證圖面 |
| 門隙 2 mm、安全區 5 mm、出血 3 mm | CONFIG | 預覽／印刷面政策值 |
| 四個歷史 SKU 身分欄位 | CONFIG | Issue 指定；沒有虛構圖檔或歷史來源 |
| 歷史 Artwork | BLOCKED | repo 中未提供原始圖稿，保留待補 slot |
| 校驗圖 | FIXTURE | 程式建立的非對稱彩色定位格，各 SKU／門片可區分 |
| mm 幾何、裁圖、UV、雜湊與拒絕錯誤資料 | REAL_LOGIC | 單元／回歸及真實 worker 核對，見驗收紀錄 |
| Blender 閉門／立體／細節預覽 | REAL（scoped preview） | 以獨立正式 acceptance 的實際結果為準 |
| 五金、鉸鏈、磁吸、孔位、接合 | UNKNOWN / BLOCKED | 不新增假五金或假開門動畫 |
| FRONT_OPEN | BLOCKED | articulation authority 不足 |
| BOM、板件、印刷面、nesting input | PARTIAL / CANDIDATE | 非裁切單；未知板材、鋸縫、紋向、餘料均保持空值 |
| 工程、製造、production readiness | false | 不因 UI 生成完成、pytest 或 CI PASS 升級 |
| LIVE CNC / LASER / PLC | BLOCKED | 未涉及機台控制 |

## 工程與 Artwork 分離

- `GoldenRecipe` 用可帶 truth、evidence 與 evidenceSha256 的 Measurement schema 保存毫米數值。VERIFIED 欄位必須帶證據雜湊，但單一欄位的 VERIFIED 不會讓整體 readiness 自動升級。
- 櫃體有 10 個板件：左右側板、頂底板、兩層板、背板、三片門。門片由上到下固定為 door_1、door_2、door_3。
- `sizeMm`、`locationMm` 為幾何來源。Blender 在單位邊界除以 1000，直接設定實際尺寸；不使用舊 `_add_box` 的尺寸補償。
- 四 SKU 使用相同 EngineeringHash。SKU、Artwork 版本與像素身分放在 ArtworkHash／PackageHash，印刷安全區與出血也不改變 EngineeringHash。
- 預設門面為 390 × 276 mm；三門在主畫布上的起點為 y=0、295、590 mm，整體畫布為 390 × 866 mm。門片之間刻意跳過 19 mm 的橫板與間隙區域，並保存 seam metadata。
- MASTER_SPLIT 的 PNG 座標由左上向下，Blender UV 由左下向上；使用明確的 y 反轉。SINGLE_SURFACE 每門有獨立來源，不取其他門的畫布區段。
- 校驗圖採 1 px/mm 精確格網；這是定位測試，不是印刷解析度承諾。圖稿不拉伸，production trim 從同一來源圖像獨立裁出，比對實際像素。
- 安全區與出血以 metadata 保存；裁圖下載是 trim-only 校驗圖。未知五金 keep-out 不會假填，出血擴展與正式印刷輸出保持 BLOCKED。

## 可重用模組與資料

| 位置 | 用途 |
|---|---|
| `src/fox3d/golden_product.py` | 配方 schema、毫米幾何、四 SKU／Artwork slots、定位與拒絕錯誤資料規則 |
| `src/fox3d/golden_preview.py` | 連接既有 Platform、Blender、DAM；不可變 generation、來源／裁圖／模型驗證 |
| `src/fox3d/golden_api.py` | 現有 Recipe admin 的 Golden UI/API |
| `src/fox3d/recipe_preview_service.py` | 沿用背景排程、重啟恢復、取消與重複工作保護；加入 adapter 注入 |
| `scripts/blender_job.py` | Golden mm 建模及 mesh UV／packed texture 實際讀回；既有非 Golden 模式保留 |
| `scripts/run_golden_product_e2e.py` | clean-CODE HTTP／Blender／下載／重啟驗收 |
| `scripts/check_golden_blend.py` | 在重開的 Blender 檔中核對尺寸、門面 UV 與嵌入圖檔雜湊 |
| `data/golden_product/recipe.schema.json` | 可替換成已驗證工程输入的 schema |
| `data/golden_product/three_tier_manifest.json` | 預設配方、EngineeringHash、四個原稿待補 slot 與校驗版本 |

歷史原稿待補時需保存來源、合法使用依據與原圖雜湊。V1 UI 目前提供原稿待補欄位與兩種校驗版本，尚未提供任意圖稿上傳／工程配置編輯；不可把改寫 slot 當成原稿已驗收。

## 驗證與備份

成果在資料根目錄 `golden-previews/<tenant+sku hash>/generations/<generationId>/`。每代保存原圖、逐門 trim、三個 PNG、GLB、blend、worker observation 與 manifest。只有所有校驗通過後才更新最新版本指標；取消或失敗保留原成果。下載會重新驗證身分、來源與 SHA-256。

原稿內容及版本納入既有 render cache 的 assetHash；快取命中時保留原始 worker job ID，另記 requestedJobId，不能把快取成果冒充新 worker 執行。取消會在素材建立後、渲染返回後及更新最新成果前再次檢查。

備份時保存整個 `.fox3d-data`，不要只備份 JSON；其中包含原有 Recipe 草稿、Golden generations 與既有 DAM 資產。本機 `.fox3d-work` 為驗收及開發紀錄，正式驗收摘要另提交至 docs。

此 Issue 完成後等待 Supervisor Re-Gate；不自動進入 Issue #5/#6 的影片流程，不改寫既有 Supervisor LIVE webhook 阻擋狀態。
