# Grok 下一階段開發指令：Real Blender E2E + Parametric Cabinet

> Repo: `netfox-web/blender-autonomous-3d`
>
> 先讀完整 repo 與 `src/fox3d/`，禁止另起新專案、禁止重寫既有架構。

## 最高優先目標

目前後台已存在 Blender Workers、3D Jobs / Render Queue、Digital Twins、Recipes、Parametric Products、Furniture、Packaging、Scenes、Materials、Camera Recipes、Lighting Recipes、Recipe Research、Synthetic Data、Product R&D 等功能。

本輪不要繼續堆 Mock UI。先確認哪些是真的、哪些是 Mock，然後打通：

`真 Blender Headless → 真 NVIDIA GPU → 真 Cycles/OptiX → 真 Render → Queue → Digital Twin → DAM`

完成後再往參數化木櫃、自動 BOM、成本與未來 CNC/CAM 邊界發展。

---

## STEP 0 — Audit，禁止猜測

完整掃描：

- `src/`
- `tests/`
- `docs/`
- `scripts/`
- `pyproject.toml`
- requirements
- Docker
- README
- env/config/schema/migration

搜尋：

`mock`, `fake`, `stub`, `TODO`, `FIXME`, `NotImplemented`, `mock-4.2`, `local-mock`, `local-5090`, `BLENDER`, `OPTIX`, `CUDA`, `CYCLES`, `DigitalTwin`, `Parametric`, `Cabinet`, `BOM`, `Render`, `DAM`。

建立 `docs/CURRENT_IMPLEMENTATION_AUDIT.md`，每項只能標：

- REAL
- PARTIAL
- MOCK
- STUB
- MISSING
- BLOCKED

看到 API、class、route、schema 或 UI 不代表完成，必須追到真正 execution path。

---

## Phase 41 — 真 Blender Discovery

實作 Windows / Linux Blender discovery：

- 自動尋找 Blender executable
- 執行 `blender --version`
- 回報真實 Blender version / executable path
- 找不到則 `BLOCKED_NO_BLENDER`
- 禁止 fallback 成 mock 後宣稱成功

Mock 僅可保留於 automated test / dev。

## Phase 42 — 真 GPU Discovery

實作真 NVIDIA GPU discovery，至少取得：

- GPU index
- GPU UUID
- GPU name
- VRAM total / used / free
- driver
- CUDA availability

可使用 `nvidia-smi`。不得硬編碼 RTX 5090 / RTX 5080 假裝偵測成功。

Worker Registry 記錄來源：`REAL_DISCOVERY | MOCK | MANUAL`。

## Phase 43 — Blender Cycles / OptiX Probe

真正執行：

`blender -b --python <probe.py>`

使用 `bpy` 檢查：

- Cycles availability
- CUDA devices
- OptiX devices
- selected render device

輸出結構化 JSON。沒有 OptiX 則 `BLOCKED_NO_OPTIX`，不得偷偷 CPU fallback 後標 GPU PASS。

## Phase 44 — Real Smoke Render

建立 `REAL_BLENDER_SMOKE_TEST`：

- Cube
- Plane
- Camera
- 3-point lights
- Cycles
- OptiX
- 512x512 PNG

必須真啟動 Blender process、真使用 NVIDIA GPU、真產 PNG。

記錄：jobId、workerId、GPU、GPU UUID、Blender version、Cycles、OptiX、開始/結束時間、duration、output hash、output size、logs。

PNG 必須可從後台查看。

## Phase 45 — Queue 真串 Blender Worker

沿用既有 Queue / Scheduler / Reservation / Worker，禁止第二套 Queue。

Lifecycle：

`QUEUED → RESERVED → DISPATCHED → RUNNING → RENDERING → UPLOADING → COMPLETED`

失敗為 `FAILED`。

必須支援 retry、timeout、cancel、heartbeat、worker offline、reservation release。

## Phase 46 — Admin 真實狀態

Blender Workers 顯示：

- REAL / MOCK badge
- hostname
- OS
- GPU
- VRAM
- Blender version
- Cycles
- CUDA
- OptiX
- status
- current job
- last heartbeat

`mock-4.2` 不得顯示得像正式 Worker。

## Phase 47 — Digital Twin 真 E2E

建立 `PRODUCT_DIGITAL_TWIN_E2E`，先支援 GLB / GLTF：

`Upload → Asset/DAM → Digital Twin → validation → Blender import → normalize → dimensions → bounding box → preview render → DAM`

Digital Twin 頁面至少顯示 preview、asset、dimensions、format、version、createdAt。不得只建立 database row。

## Phase 48 — WHITE_STUDIO 真商品攝影

沿用既有 `WHITE_STUDIO` Recipe：

`Digital Twin → Blender Scene → Ground Plane → Auto Camera Framing → Lighting → Shadow → Cycles → OptiX → Render → DAM`

不得人工打開 Blender。

## Phase 49 — PRODUCT_360

`Digital Twin → Turntable → 36 frames → GPU Render`

輸出 frames manifest、MP4、Web 360 manifest，全部回 DAM。

記錄 lineage：DigitalTwinVersion、RecipeVersion、BlenderVersion、GPU、JobId。

## Phase 50 — REAL E2E Acceptance

建立 `docs/REAL_E2E_ACCEPTANCE.md`，逐項標：

- REAL PASS
- MOCK PASS
- BLOCKED
- FAIL

Production Ready 至少要求：

- `realBlender=true`
- `realGPU=true`
- `realCycles=true`
- `realOptix=true`
- `realRenderOutput=true`
- `queueIntegrated=true`
- `damIntegrated=true`

任一 false，不得宣稱 Production Ready。

---

# Parametric Furniture

## Phase 51 — Engineering Core

建立 `EngineeringProductDefinition` 作為唯一 Source of Truth，至少包含：

- productType
- width / height / depth
- material
- components
- constraints
- connections
- hardware

Blender 只是 consumer。同一 Engineering JSON 同時供 Blender、BOM、Cost、未來 CAD/CAM。

## Phase 52 — STORAGE_CABINET V1

第一個真參數化產品：`STORAGE_CABINET`。

測試輸入：

- width=800
- height=1800
- depth=400
- boardThickness=18
- shelfCount=4
- doorCount=2

自動建立 left/right panel、top、bottom、back、shelves、doors。禁止固定 mesh hardcode；參數改變必須重新生成 geometry。

## Phase 53 — BOM

由同一 Engineering Definition 自動產 BOM：

- partId
- partType
- length
- width
- thickness
- material
- quantity
- edgeBanding

驗證 3D geometry dimensions == BOM dimensions。禁止 Blender 與 BOM 各有一套尺寸。

## Phase 54 — Resize Regression

測試 width `800 → 1200`，確認 cabinet、top/bottom、shelf、doors、BOM、material usage、preview 全部同步更新。

## Phase 55 — Engineering Rule Engine

加入 minimum/maximum dimension、board thickness、door clearance、shelf clearance、back panel、drawer clearance、component collision、door collision、hardware clearance。

LLM 不負責工程合法性；Rule Engine 才能 Validate。

## Phase 56 — Cabinet Materials

建立：`WOOD_WHITE`, `WOOD_OAK`, `WOOD_WALNUT`, `WOOD_BLACK`, `WOOD_CREAM`。

資料包含 visual material、engineering material、cost unit、thickness options、texture asset。Blender 材質與工程材料需 mapping。

## Phase 57 — Cabinet Cost

由 BOM 計算 board area、edge banding、hardware、processing、assembly、estimated material cost、estimated total cost。先做 Engine，不串付款。

## Phase 58 — Door / Drawer / Hardware

加入 hinged door、drawer、handle、hinge placeholder、drawer rail placeholder，建立 component graph，支援 collision test。

## Phase 59 — Exploded / Assembly

由 component graph 自動產 exploded view、assembly order、assembly animation，輸出 PNG / MP4 / manifest。

## Phase 60 — Cabinet Real Acceptance

建立 `docs/CABINET_REAL_ACCEPTANCE.md`，證明：

`自然參數 → Engineering Definition → geometry → BOM → material → cost → Blender preview`

全部來自同一產品版本。

## Phase 61 — Natural Language Cabinet

加入 `DesignIntent`。

範例：

「幫我做一個寬120公分、高180公分、深40公分，雙門、4層板、白色木紋收納櫃。」

流程：

`Natural Language → DesignIntent JSON → Parametric Engine → Engineering Rules → BOM → Cost → Blender`

LLM 禁止直接輸出正式製造資料。

## Phase 62 — Variant Generator

同一需求產多方案：door layout、shelf layout、color、handle、proportion。先 Preview，不要全部 Final Render。

## Phase 63 — Vision Judge

Preview 評估 composition、aesthetics、space utilization、manufacturability、cost、constraint validity，保留 Top N。工程合法性不得由 Vision Model 取代 Rule Engine。

## Phase 64 — Product R&D Agent

流程：

`Natural Language → Design Intent → Variants → Engineering Validation → BOM → Cost → Blender Preview → Vision Judge → Candidate`

正式生產前必須 `HUMAN_APPROVAL_REQUIRED`。

## Phase 65 — CNC/CAM Boundary

本輪只建立 `ManufacturingManifest` 與 Adapter interfaces：

- CADAdapter
- CAMAdapter
- CNCAdapter
- NestingAdapter

可產 BOM、DXF export interface、drilling manifest、cutting manifest，但禁止真正控制 CNC。

---

# 後續延伸

## Phase 66 — Packaging Digital Twin

沿用同一 Digital Twin 架構延伸 BOX / BOTTLE / POUCH / JAR / TUBE：

`artwork → material → 3D → render → 360 → video reference`

禁止第二套 Digital Twin。

## Phase 67 — Blender → AI Video

建立通用 Adapter：

`Blender → start/middle/end references + depth + normal + mask → AI Video Adapter`

預留 H3 / LTX / 其他模型，不硬綁單一模型。

Blender = deterministic control；AI Video = generative motion/effects。

## Phase 68 — Synthetic Data

真 Blender 產 RGB、depth、normal、mask、segmentation、bounding boxes、camera pose、object id；每批 Dataset 必須有 manifest。

## Phase 69 — Autonomous Recipe Research

GPU idle 時：

`Recipe Variant → low-res Blender Preview → Vision Judge → Score`

狀態：`EXPERIMENTAL → CANDIDATE → APPROVED → PRODUCTION`。

Agent 不得直接覆蓋 Production Recipe。

## Phase 70 — Production Hardening

檢查 tenant isolation、script sandbox、path traversal、arbitrary Python execution、resource limits、network restrictions、job cancellation、GPU cleanup、temp cleanup、asset lineage、cache integrity、worker crash recovery。

Blender Python 是可執行程式碼。未批准 AI-generated Python 必須 `SANDBOX ONLY`。

---

# 不可違反規則

1. 不重寫現有架構。
2. 不建立第二套 Scheduler / Queue / Recipe Registry / DAM。
3. 不因命名不同就重做，優先 reuse / extend / adapter。
4. Mock 保留給測試，但不得冒充 Production。
5. REAL acceptance 必須有實際 artifact 證據。
6. 缺 Blender / OptiX / GPU 時不得造假 PASS。
7. 每個 Phase 要有 regression tests。
8. 不要只做 UI。
9. 不要只建 schema 就宣稱完成。
10. 不要為 Phase 數量做空殼。
11. 既有功能若已完成，先驗證再標 REAL/PARTIAL，不重寫。
12. 正式製造/CNC 前保留 Human Approval Gate。

# 本輪交付

完成後提交：

1. `CURRENT_IMPLEMENTATION_AUDIT.md`
2. `REAL_E2E_ACCEPTANCE.md`
3. `CABINET_REAL_ACCEPTANCE.md`
4. 所有新增/修改檔案
5. migrations
6. tests
7. 真實測試結果
8. Mock / Real 對照表
9. 未完成 Blockers
10. 下一輪建議

並執行專案現有 lint / typecheck / unit / integration / E2E tests。

最後報告必須明確區分 `REAL / MOCK / PARTIAL / BLOCKED`，不得用「已完成」概括尚未真正接通的功能。

**現在直接從 main branch Audit 開始，依依賴順序實作，不要先問是否繼續。**
