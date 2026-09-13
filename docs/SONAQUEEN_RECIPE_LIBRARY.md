# Sonaqueen 商品 Recipe 參考庫

這是使用者於 2026-09-13 指示建立的第一批商品參考庫。沿用現有 `RecipeRegistry`，提供三種母配方描述、三款 SKU 的供應商資料與離線來源驗證。這項工作不宣告 Phase 961+ 開始，也不解除目前 Phase 901–960 Re-Gate 的 HOLD。

## 已入庫商品

尺寸欄為 **寬 × 深 × 高（mm）**，由供應商尺寸圖的文字標籤 cm × 10 換算，保留供應商「約值」性質。沒有使用像素比例推算尺寸。

| SKU | 商品 | 外尺寸 | 結構 |
|---|---|---|---|
| MY-012 | 日系禪風十二格書櫃 | 602 × 300 × 1802 | 六行交錯隔板、十二格、無門 |
| LI-D40 | 瓦格四門收納櫃 | 415 × 300 × 1196 | 四行上下排列門片、無把手 |
| LI-PU63D-免組裝 | 夏爾六格滑門收納櫃 | 785 × 300 × 785 | 三行、六格、三片滑門 |

母配方描述：`STAGGERED_OPEN_CUBBY`、`STACKED_HINGED_CABINET`、`ROW_SLIDING_CABINET`。它們描述共用結構要求；目前尚不是可執行的 Blender 建模器。

## 使用方式

在儲存庫根目錄執行：

```powershell
python scripts/inspect_recipe_library.py
python scripts/inspect_recipe_library.py --sku LI-D40
python scripts/inspect_recipe_library.py --tenant sonaqueen-home --export .fox3d-work/sonaqueen-recipes.json
```

匯出檔為 UTF-8 JSON，可交由現有 `RecipeRegistry` 的呼叫端使用。程式呼叫方式：

```python
from pathlib import Path
from fox3d.catalog_recipes import import_library
from fox3d.infra import RecipeRegistry

registry = RecipeRegistry()
recipes = import_library(
    Path("data/recipe_library/sonaqueen/catalog.json"),
    registry,
    tenant_id="sonaqueen-home",
)
```

`RecipeRegistry` 本身為記憶體 registry；JSON 匯出提供檔案形式的可重用參考資料，未新增另一套正式配方資料庫。完全相同的匯入不新增版本；資料改變產生新的參考版本。既有核准或正式版本不會被覆寫。

## 來源與驗證

`data/recipe_library/sonaqueen/catalog.json` 包含每個 SKU 的商品頁、圖檔、擷取時間、SHA-256、欄位證據來源、判讀方式與原始觀察。三份商品頁 HTML 與七張商品／尺寸圖位於同目錄下的 `sources/`。

每次載入檢查 schema、SKU 唯一性、來源引用、檔案路徑、實際位元組雜湊、頁面 SKU／名稱、圖檔是否被該頁引用，以及各種母配方的門片／格位數量約束。來源 integrity 驗證不等於供應商規格已經實物量測或工程核定。

新增商品時，依 `SeedLibrary`／`ProductSeed` 格式加入來源與 facts。未確認數值保持缺漏，不填通用尺寸。當官網更新，需保存新來源並重新核對圖上的標籤後修訂資料；本版不會自動把網站變動當成已核定的 Engineering。

線上驗收須在乾淨工作目錄及指定 CODE commit 上執行：

```powershell
python scripts/run_recipe_library_e2e.py --expected-commit <CODE_SHA>
```

腳本重新取得十份來源。七張圖片必須與快照逐位元組一致；動態商品頁只核對 SKU／名稱，不聲稱整頁完全一致。再測試參考 Recipe 匯入，將驗收記錄寫入 `.fox3d-data/recipe-library-acceptance/<generation>/report.json`。任何來源或 commit 檢查失敗即拒絕產生成功驗收。

## 尚待完成的建模資料

- MY-012：各板件厚度、背板厚度、接合方式與每行隔板精確座標。部分內徑已錄入，但不將外內徑差當成核定板厚。
- LI-D40：板厚、背板／門板厚度、門縫及鉸鏈規格；需支援逐行門片和個別鉸鏈轉軸。
- LI-PU63D：側板／背板／門板厚度、門縫、滑軌截面與行程。官網的 25 mm 僅記為「固定板」厚度，不推廣為所有板件厚度。

目前全部以 `PRODUCT_REFERENCE` / `EXPERIMENTAL` 入庫，能力標記只有 `CATALOG_REFERENCE`。`engineeringReady`、`renderReady`、`productionReady` 均為 false。尚未產生這三款的精確 3D 模型或商品渲染，不會把現有通用櫃體套用後標示為已還原商品。

下一步應由供應商圖面補齊資料，將每種結構接入現有 Engineering 權威，完成對應幾何與機構驗證，再執行三款商品各自的 REAL Blender 渲染／核對。既有 Product Truth 與商用出圖的 Re-Gate 修正仍依原流程處理。
