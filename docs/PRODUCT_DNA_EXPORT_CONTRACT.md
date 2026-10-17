# Product DNA 匯出契約（Issue #18）

非正式環境的唯讀契約。沿用 Issue #4 與已合併 PR #7 的三層櫃 Golden Product：`EngineeringHash`、`ArtworkHash`、`Final UV`、BOM candidate，以及既有真實 Blender 預覽邊界。本變更不重寫 Fox3D 引擎，不讀寫 ERP、AI PRINT OS 或 SpecPilot 資料庫，也不部署。

`globalProductionReady=false`。`engineeringReady=false`。`manufacturingReady=false`。`physicalPrintValidated=false`。`liveMachineControl=false`。

## 母版與 SKU

| 欄位 | 值 | 說明 |
|---|---|---|
| familyId | `fox3d.family.three_tier_door_cabinet` | 本地商品族。ERP family id 仍是 UNBOUND |
| moldId | `fox3d.mold.three_tier_424x295x900.v1` | 本地刀模／工程母版代號，不是已核准製版 |
| engineeringTemplateId | `THREE_TIER_DOOR_CABINET_424x295x900_V1` | 既有配方 ID |
| 預設匯出 | KU002101、KT015101、CN003701 | 1 個模具 × 3 個 Artwork SKU |
| 圖稿 | `FIXTURE_MASTER_V1` 或 `FIXTURE_SINGLE_V1` | 非 IP 校驗圖。歷史原稿維持 BLOCKED |

同一工程母版可以掛多個 Artwork。換圖會改變 `ArtworkHash`、`FinalUvHash`、`PackageHash`，不會改變 `EngineeringHash`。尺寸、板厚、結構或非預覽工法若導致工程雜湊改變，必須使用新的工程版本，不能沿用目前模具 ID。安全區與出血屬於印刷面政策，不改工程雜湊。

## 對外 API

其他服務只透過 HTTP 讀取，不共用資料庫。

| 方法 | 路徑 | 行為 |
|---|---|---|
| GET | `/api/product-dna/v1/catalog` | 公開母版代號、已知缺口、readiness=false |
| GET | `/api/product-dna/v1/families/{familyId}/manifest` | 需 `X-Tenant-Id`。三個 SKU 的 typed manifest |
| GET | `/api/product-dna/v1/families/{familyId}/skus/{sku}/twin` | 單一數位雙生 |
| POST | `/api/product-dna/v1/reconcile` | 比對宣告式 ERP／AI PRINT OS／SpecPilot 快照。不落盤、不回寫 |
| GET | `/api/product-dna/v1/media-refs?consumer=` | FoxRecorder、ImageAI、FoxStudio 唯讀媒體引用 |
| POST | `/api/product-dna/v1/exports` | 在本地封存預覽契約。可先 `seal=false` |
| POST | `/api/product-dna/v1/exports/{id}/cancel` | 尚未封存才能取消 |
| POST | `/api/product-dna/v1/exports/{id}/retry` | 已取消則建立新封存；已封存則回同一筆 |
| GET | `/api/product-dna/v1/exports/{id}` | 重算 SHA、語意與校驗檔。跨租戶為 404 |

型別來源是 `src/fox3d/product_dna.py` 的 Pydantic model。JSON Schema 在 `data/product_dna/export.schema.json`。

每個 twin 帶 GLB／三個角度 PNG／校驗圖與裁圖的媒體列、角度 metadata、source hash，以及 `PREVIEW_FIXTURE` truth badge。GLB 與渲染 PNG 在沒有真實 Blender 世代時是 `ABSENT`，不會補假檔。

## 證據分離

| 標籤 | 本契約中的意思 |
|---|---|
| REAL_LOGIC | 毫米幾何、UV、工程／Artwork／BOM candidate／Final UV 雜湊由既有 Golden 函式算出 |
| FIXTURE | 校驗圖像素。不是歷史授權圖稿 |
| MOCK_REGRESSION | pytest 與 GitHub Actions（`FOX3D_MOCK_BLENDER=1`）。不是渲染證據 |
| ABSENT | 這份匯出沒有 GLB／渲染 PNG |
| REAL_BLENDER | 只有 `evidenceOrigin=LIVE_BLENDER_PROCESS`、`usedMock=false`、有 Blender 版本，且環境不是 mock 時，分類器才接受這個標籤。本 PR 沒有執行真實 Blender，也沒有把任何檔案標成 REAL_BLENDER |
| DECLARED_REF_NOT_LIVE | ERP、AI PRINT OS MasterProduct、SpecPilot Product DNA 只保留來源說明，沒有線上讀取 |
| BLOCKED | 歷史原稿、開門視角、製造放行、正式印刷 |

本地哈希全部吻合、外部 ID 仍未綁定時，核對結果是 `LOCAL_MATCH_EXTERNAL_UNBOUND`，不是跨系統已同步。

## 已知缺口

- 沒有 ERP product family 的線上 ID，也沒有回寫。
- AI PRINT OS MasterProduct 未綁定。本地 mold id 不是已核准刀模。
- SpecPilot Product DNA id 未綁定。僅保留 Issue #58／#59 的宣告連結。
- 歷史授權圖稿仍然沒有檔案，維持 BLOCKED。
- 本環境沒有 Blender，沒有新的 clean-tree REAL render。既有 Golden 預覽路徑會在真實成功時寫入 `evidenceOrigin=LIVE_BLENDER_PROCESS`；本 PR 沒有跑那條路徑。
- BOM 仍是 candidate，不是裁切單。五金與開門維持 UNKNOWN／BLOCKED。
- `globalProductionReady` 維持 false。CI 綠燈不是 Production Ready，也不是 Worker 自評 PASS。
