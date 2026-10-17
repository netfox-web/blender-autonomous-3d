# 地端 AI 實景：組合櫃 3D 場景電商工坊

`/admin/recipes/scenes` 的第三步「批次出電商圖」現在有三個引擎，可在畫面上切換：

| 引擎 | 做什麼 | 需要什麼 |
|---|---|---|
| **地端 AI 實景生成**（預設） | Blender 光追圖交給公司 GPU 艦隊（`image_flux3` = FLUX 3 Image Klein）重拍成真實照片，櫃體像素 100% 鎖定不重畫，每組可出 1–4 張變化 | 艦隊服務金鑰、工作台綁 0.0.0.0 |
| 內建攝影棚合成 | 本機 Pillow 景深／窗光／調色，秒出，仍是 3D 質感 | 無 |
| 只出 3D 光追圖 | 只跑 Blender Cycles | 無 |

AI 排景（步驟 2「AI 室內設計師」）預設也改走地端：公司 AI 閘道 `http://192.168.66.101:11434/v1` 的 `qwen3.8:27b`；沒有 Anthropic 金鑰時自動選地端。
實測 27B 一次排景約 146 秒、挑家具合理；`qwen3:8b` 約 24 秒但會重複放沙發、略過家具，要快可在設定改模型。

## 管線（每一組矩陣項目）

1. Blender Cycles 1024² 渲染 `beauty.png`（整個房間）與 `product_cutout.png`（櫃體＋地面影子，RGBA，shadow catcher）。
2. 工作台把 `beauty.png` 以區網網址公開（`{publicBaseUrl}/api/ecommerce-scenes/batches/{batch}/items/{item}/download/png?workspace=…&inline=true`）。
3. 對艦隊中控 `POST /api/fleet/tasks` 送 N 個 `image_flux3` 任務（`imageUrls=[參考圖]`、`upsample=true`、`seed=種子+k`），輪詢到完成後經中控 artifact 代理下載 PNG。
4. 把鎖定的櫃體 cutout 貼回每張生成圖（邊緣 0.8px 羽化，櫃體內部像素不動）→ `ai_local_01.png`…；原始生成圖另存 `ai_local_01_raw.png`；`ai_local.json` 記錄提示詞、種子、任務編號、節點、耗時。
5. 內建合成 `ai_composite.png` 仍會做，當艦隊排隊或失敗時的備援。

### 不會互相卡住

Blender 逐組算完就把該組交給 AI 執行緒池（同時 3 組），馬上算下一組；AI 在艦隊排隊時不會擋住後面的光追。批次要等所有 AI 回來才算完成。工作台重啟時正在跑的批次沒人接手，5 分鐘沒更新會被標成「已中斷」，重送即可。

### 批次清單與重送

「批次成果」有下拉清單（最近 15 批），重新整理或換電腦開都找得回來，會記住上次看的那批；`batch.json` 的 `request` 存了整批原始設定（櫃體、場景、配色、視角、AI 選項），「重新送出這批」一鍵重跑（例如工作台重啟中斷之後）。

### 畫面

2D 平面圖與 3D 預覽依實際顯示尺寸 × 螢幕倍率繪製（先前是 520×400 被拉寬，模糊又變形）；標籤改成不旋轉的深色底白字。3D 預覽相機原本算到背牆後面（整個左右相反），已改成從房間前方看，與 Blender 鏡頭一致。場景庫改成縮圖卡片（同一套即時預覽引擎、廣角、不含浮水印），滑過看大圖、點一下選用。

### 釘住櫃體位置與重影守門

FLUX 有時會把櫃子畫得略大或往右偏，貼回鎖定的去背圖後，AI 自己畫的櫃子會從旁邊露出來（重影）。兩道防線：

1. **框選釘位**（`aiPinProduct`，預設開）：把去背圖的外框換算成 FLUX 3 的 0–1000 layout box 一起送出，模型就把櫃子畫在框內。實測臥室場景 2/2 乾淨。
2. **位置偵測**（`drift_score`）：拿參考圖裡的櫃子邊緣當模板，在 AI 圖上找實際位置與縮放；偏移 ≥2% 或框外面積 ≥4% 判定重影，自動換種子重生成一次並留較好的；仍偏就在 UI 標「⚠」，建議按「再生成」。原始 AI 圖存 `ai_local_0k_raw.png`，分數在 `ai_local.json`。

提示詞由程式依場景組出（房型、牆／地板顏色、家具清單、燈光、鏡頭、櫃體描述、風格預設、使用者微調文字），畫面上「預覽送出的提示詞」可看到並手改；「請地端 LLM 擴寫」會呼叫閘道模型改寫成更完整的英文攝影 brief。變化幅度「忠實」只換材質光線，「大膽」允許重新設計牆面地板窗戶與家具風格，但櫃子位置尺寸不動。

## 設定

設定存在資料根目錄的 `ai_settings.json`（UI「GPU 艦隊連線設定」可改），金鑰不會回傳給瀏覽器：

| 鍵 | 預設 | 說明 |
|---|---|---|
| `imageEngine` | `fleet_flux3` | `fleet_flux3` / `builtin` / `off` |
| `fleetApiUrl` | `FLEET_API_URL` 或 `http://192.168.66.101:3004` | 艦隊中控 |
| `fleetToken` | — | 服務金鑰；也可用環境變數 `FLEET_SERVICE_TOKEN`、`FLEET_SERVICE_TOKEN_FILE`，或檔案 `~/.netfox-secrets/fox3d.fleet-token` |
| `publicBaseUrl` | 自動偵測（連到中控的那張網卡 IP + 目前埠） | 節點抓參考圖用；也可用 `FOX3D_PUBLIC_BASE_URL` |
| `aiVariants` | 2 | 每組變化張數 1–4 |
| `aiVariation` | `faithful` | `faithful` / `creative` |
| `aiUpsample` | true | FLUX 3 提示詞擴寫（多 19GB 顯存，只有 24GB 以上卡能跑；關掉可讓 5080 接單） |
| `aiPinProduct` | true | 送 FLUX 3 layout box 把櫃子釘在去背圖的位置（避免重影） |
| `localBaseUrl` / `localModel` | 閘道 / `qwen3.8:27b` | 排景與提示詞擴寫用的 OpenAI 相容端點（`FOX3D_LOCAL_LLM_URL` / `FOX3D_LOCAL_LLM_MODEL`） |

### 工作台一定要綁 0.0.0.0

GPU 節點要連回工作台抓參考圖。`scripts/open_recipe_studio.py`（桌面捷徑）與 `start-admin.bat` 已改成 0.0.0.0；手動啟動請加 `--host 0.0.0.0`（或設 `FOX3D_HOST`）。綁 127.0.0.1 時，畫面上的引擎狀態會直接警告。本機 Windows 防火牆已有 python.exe 的允許規則。

### 艦隊金鑰

金鑰在 netfox-home `/data/apps/ai-fleet-console/.env` 的 `FLEET_SERVICE_TOKENS`，格式 `token:tenantId`，新增後要 `docker compose up -d --no-build console`。建議替這個工作台建專屬 token（租戶「網狐數位」），值不進 Git。

## API

- `GET /api/ecommerce-scenes/ai-engine-status`：艦隊可達、金鑰、`image_flux3` 能力（可用節點、排隊數、預估秒數）、`publicBaseUrl`、綁定警告。
- `POST /api/ecommerce-scenes/ai-prompt`：`{scene, cabinet, themeId, aiStyleId, aiPrompt, view, aiVariation, polish}` → 組好的提示詞（`polish=true` 走地端 LLM）。
- `POST /api/ecommerce-scenes/batches` 新增欄位：`aiEngine`、`aiVariants`、`aiVariation`、`aiUpsample`、`aiSeed`（0＝隨機）、`aiFinalPrompt`（整批共用的手改提示詞）。
- 批次項目新增 `stage`（queued/blender/ai/done）、`aiState`（pending/running/succeeded/partial/failed/builtin/skipped）、`aiVariants[]`（每張的 state/seed/taskId/node/progressNote/elapsedSec/caption）、`aiPrompt`、`aiError`。
- 下載：`…/download/ai_local_png?variant=1..4`（已貼回櫃體）與 `ai_local_raw_png`；zip 內為 `*_C_AI_Local_v{k}.png`。

## 實測（2026-10-17，辦公室工作站 T1000 + 5090-3）

- Blender 1024² 24 samples OptiX 約 8–12 秒；FLUX 3 擴寫＋出圖每張約 20–40 秒（排隊另計）。
- FLUX 3 幾乎完整保留構圖，cutout 貼回去對得準；牆面出現真實石膏質感、沙發布紋、地毯織紋、窗景綠意；同提示不同 seed 的差異偏小，想要大變化用「大膽」或改風格／微調文字。
- 艦隊顯存被別的 ComfyUI 快取佔住時任務會排隊（progressNote 會顯示「等待 GPU 資源…」），UI 會一直顯示該狀態；中控只會釋放 :8188 的快取。

程式：`src/fox3d/fleet_image_client.py`（中控用戶端）、`src/fox3d/local_scene_ai.py`（提示詞／合成／變化流程／狀態）、`src/fox3d/ecommerce_scene_studio.py`（矩陣 worker）、`src/fox3d/ecommerce_scene_api.py`（路由）、`src/fox3d/static/scene-studio.*`（前端）；測試 `tests/test_local_scene_ai.py`。生成圖是行銷素材，不是 Product Truth。
