# Grok 下一輪開發指令：Phase 841–900 — Product Truth Render Pack + Generative Render Gateway V1

> Repo: `netfox-web/blender-autonomous-3d`  
> Re-Gate baseline CODE: `3268f654b3b1209dc5c5ffc6c4c149b63ce38654`  
> Evidence/docs head: `f1d57eaecd53075b3f34e03ae2d7e487d8df2875`  
> Round 12 result: **ACCEPT WITH SCOPE — Phase 781–840 Artwork Placement / Surface Decoration Engine V1 re-gate passed.**  
> Next: **GO Phase 841–900.**

## 0. 先讀：本輪核心原則

不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、ManufacturingRelease、WorkOrder、MaterialLot、Backup/Restore，也不要建立第二套商品尺寸、Artwork placement 或 UV source of truth。

本輪要把已通過的 Artwork Placement V1 接到真正可驗證的 Blender Product Truth Render，再建立可替換的 Generative Render Gateway。固定原則：

> **模型可替換，Product Truth 不可替換。**

Fox3D / CabinetSpec / ArtworkPlacement / Blender 仍是商品真相；H3 MAX、LTX 2.5 或未來模型只能是可替換的 Generative Renderer Provider，不能反過來成為尺寸、結構、Artwork、Logo、顏色、相機或製造資料的 authority。

若沒有真實 H3 MAX / LTX 2.5 provider/runtime，本輪不得假裝串接成功。Provider contract 可以完成為 REAL_LOGIC，fixture 可以是 FIXTURE/MOCK，live provider 必須維持 BLOCKED/MOCK。

---

# Re-Gate 結論：Round 12 已通過

以下已確認足以解除 Phase 841+ HOLD：

1. CODE `3268f65` 已補 required + strict finite canonical geometry：`cabinet4.widthMm`、crop `xMm/yMm/widthMm/heightMm`、`canonicalSurfaces.*.widthMm/heightMm` 均拒絕 missing / bool / numeric string / NaN / ±Inf。
2. `finiteCanonicalGeometryTamperBlocked=true` 為獨立 probe；Round 8–11 原有 orientation/type/oracle/geometry/near-tolerance tamper flags 全維持 true。
3. `pytest -q` 回報 **607 passed**。
4. exact CODE GitHub Actions `34590848023`：Ubuntu + Windows SUCCESS。
5. canonical generation `0d3f01cb-336b-4d28-8659-783a5f59f419` 綁 exact CODE、`workingTreeClean=true`、`ok=true`。
6. docs/head `f1d57ea` Actions `34592535882`：Ubuntu + Windows SUCCESS。
7. Truth labels 沒有越界：Artwork validator = REAL_LOGIC/FIXTURE；Blender artwork preview = MOCK/false；physical print = false/BLOCKED；Demand/Vision/AI Video = MOCK；LIVE_CNC/LIVE_LASER/liveFactory = BLOCKED；global/full/live readiness = false。
8. `docs/CABINET_REAL_ACCEPTANCE.md` cabinet engineering truth 未改，保持原狀合理。

### 非阻塞 hardening carry-forward

目前 `_canonical_source_bound()` / `_source_crop_matches()` 還有部分 `int()` / `str()` coercion。它們目前不會讓錯誤 source bytes 變成 REAL，因為 canonical source SHA / expected 仍由 live deterministic source 重算；因此不再擋住 841+。但本輪若觸碰該 validator，順手收斂 exact serialized type，並加 regression，不能倒退。

---

# Phase 841–848 — REAL Blender Artwork Preview Gate

目前最大缺口不是 Artwork math，而是 `realArtworkPreviewReady=false`。本段先把 Product Truth 的 artwork 真正送進 REAL Blender 5.2.1 / OptiX 路徑，不能用 pytest mock 代替。

## 必做

1. 沿用既有 accepted `ArtworkPlacement` / `finalUvHash` / `placementHash` / `engineeringHash` / `surfaceHash` / `artworkHash`。
2. REAL Blender job 必須：
   - `usedMock=false`
   - `realBlender=true`
   - `realOptix=true`（若本機仍具備）
   - artwork bytes SHA 與 DAM 記錄一致
   - exact object/component identity
   - exact FRONT printable face，不得把貼圖 authority 套到整個 cube 的非 printable faces
   - final UV / rotation / mirror / crop 只能從 canonical placement identity 取得
3. 生成一張 canonical artwork preview（至少 4-door master 中一門 + 一張完整 4-door assembled view）。
4. 每個輸出記錄：artifact SHA256、size、pixel dimensions、Blender version、GPU/worker identity、jobId、CODE_EVIDENCE_SHA、engineeringHash、artworkHash、placementHash、finalUvHash、cameraRecipeHash。
5. 增加 REAL preview validator：output artifact 必須存在、hash/size 真實可讀、job/output identity 與 request exact match。
6. 不得因為 REAL Blender render 成功就設定 physical print ready。

## Gate

只有實際 REAL Blender evidence bundle 成功，才能把：

- `realArtworkPreviewReady=true`

否則保持 false，Phase 841–848 可標 PARTIAL/BLOCKED，但不得偽造。

---

# Phase 849–858 — Product Truth AOV / Control Pack

從同一個 Blender scene/job 生成 provider-neutral control pack，供未來 H3 MAX / LTX 2.5 / 其他 renderer 使用。

至少包含：

- Beauty RGB
- Depth
- Normal
- Product/Object Mask
- Artwork/Printable Surface Mask
- Alpha / Product Matte
- Camera metadata
- Object/component ID manifest

如果現有 compositor 已能產 depth/normal/seg，請擴充現有路徑，不要另建一套 renderer。

每個 AOV 必須有：

- artifactId / DAM ref
- SHA256
- size
- width / height
- format
- semantic role
- same renderPackId
- same engineering/artwork/placement/camera lineage

### 必須 fail-closed

- 缺任一 required AOV → `productTruthRenderPackReady=false`
- AOV dimensions 不一致 → FAIL
- artifact hash/size mismatch → FAIL
- mask 全黑 / 全白且不符合 expected product occupancy → FAIL
- object mask 缺 cabinet/product component identity → FAIL
- AOV 來自不同 engineering/artwork/placement/camera hash → FAIL

---

# Phase 859–868 — SceneRecipe / CameraRecipe SOT

新增小型、可 hash 的 scene/camera recipe；不要把它變成第二套 Cabinet geometry。

## CameraRecipe 最少欄位

- cameraId
- target / lookAt
- location / rotation 或 deterministic pose definition
- focalLengthMm
- sensorWidthMm（若需要）
- resolution
- aspect ratio
- framing / safe margin
- recipeVersion
- cameraRecipeHash

## SceneRecipe 最少欄位

- sceneId
- background/environment preset
- lighting preset / key-fill-rim 或 studio rig identity
- floor / shadow catcher policy
- render engine / samples / color management
- recipeVersion
- sceneRecipeHash

要求：同一個 Product Truth + SceneRecipe + CameraRecipe 可 deterministic replay；修改 camera/scene recipe 必須改 hash，不能 silent drift。

---

# Phase 869–878 — `ProductTruthRenderPack` Manifest + DAM Lineage

建立單一 manifest（名稱可調整），把 Product Truth Render Pack 發布到既有 DAM，不重寫 DAM。

至少綁定：

- tenantId
- productId / candidateId / version
- engineeringHash
- CabinetSpec / Twin identity（沿用現有可用欄位）
- artworkId / artworkHash / artworkSha256
- placementId / placementHash / finalUvHash
- sceneRecipeHash
- cameraRecipeHash
- renderPackId
- Beauty / Depth / Normal / ProductMask / ArtworkMask / Alpha artifacts
- blenderJobId
- Blender version / worker / GPU evidence
- CODE_EVIDENCE_SHA
- generatedAt
- `usedMock`
- `truthLabel`

### Authority rule

Generative renderer 只能引用 `renderPackId`，不能自行重建或覆寫 Cabinet/Artwork geometry。任何 provider job 的 input lineage 必須可回溯此 manifest。

---

# Phase 879–888 — Generative Render Gateway V1（Provider-neutral）

建立很薄的 provider adapter boundary；不要把 H3 MAX 或 LTX 2.5 寫死進 Fox3D core。

建議 contract：

```text
GenerativeRenderRequest
  renderPackId
  mode: IMAGE | VIDEO
  prompt / negativePrompt
  duration/fps (VIDEO)
  productLocked=true
  requiredControls[]
  providerPreference[]
  seed/policy

GenerativeRenderResult
  provider
  providerModel
  providerRequestId
  outputArtifacts[]
  inputRenderPackId
  inputLineageHash
  usedMock
  status
  latency/cost (若真實可得)
```

Adapter 至少預留：

- `H3_MAX`
- `LTX_2_5`
- `FUTURE_PROVIDER`

但只有存在真實 provider/runtime + 真實 request/response evidence 時才可標 REAL_PROVIDER。否則：

- interface / routing logic = REAL_LOGIC
- deterministic fixture adapter = FIXTURE/MOCK
- live provider availability = BLOCKED/MISSING

不得把 fake HTTP response、hardcoded output URL、fixture video/image 當 provider ready。

---

# Phase 889–894 — Provider Scheduler / Capability Routing

在既有 Scheduler/Queue 上加 routing metadata，不重寫 Scheduler。

至少可依下列決策：

- IMAGE vs VIDEO
- required controls（depth/normal/mask/image conditioning）
- resolution / duration / fps
- provider capability
- local/remote availability
- estimated latency/cost（若只是 config 要明確標 CONFIG_ESTIMATE）
- productLocked requirement

Scheduler output 必須可說明「為何選 H3 MAX / LTX 2.5 / fallback」，但不要宣稱目前哪個 provider 品質一定較好；沒有真實 benchmark 就保持 UNVERIFIED。

---

# Phase 895–898 — Product Consistency QA Gate

Generative output 永遠不是 Product Truth。新增 QA contract，至少區分：

- STRUCTURE
- ARTWORK/LOGO
- COLOR
- SILHOUETTE / PRODUCT MASK
- CAMERA / FRAMING
- GENERATED BACKGROUND

本輪若沒有 live Vision model：

- deterministic mask/geometry/image checks = REAL_LOGIC
- Vision Judge = MOCK/BLOCKED

QA 必須有 fail-closed output：

- `APPROVED_FOR_ASSET_REVIEW`
- `REJECT_PRODUCT_DRIFT`
- `REJECT_ARTWORK_DRIFT`
- `REJECT_MISSING_EVIDENCE`

不得自動把生成結果升成 production ecommerce asset；仍需 Human/Asset review gate。

---

# Phase 899–900 — Acceptance / Evidence / Docs

新增：

- `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md`
- `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json`
- `docs/GENERATIVE_RENDER_GATEWAY_ACCEPTANCE.md`
- `docs/GENERATIVE_RENDER_GATEWAY_ACCEPTANCE.json`

並更新：

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md`
- `docs/CABINET_REAL_ACCEPTANCE.md`：**只有 REAL artwork Blender path 真正改變 cabinet preview evidence 才更新；否則不要為了湊文件而改。**

## Canonical acceptance 至少要發布

- `realArtworkPreviewReady`
- `productTruthRenderPackReady`
- `productTruthAovPackReady`
- `generativeRenderGatewayLogicReady`
- `liveH3MaxProviderReady`
- `liveLtx25ProviderReady`
- `productConsistencyQaLogicReady`
- `liveVisionJudgeReady`
- `physicalPrintValidated`
- `liveFactoryExecutionReady`
- `globalProductionReady`

### 預期 truth boundary

若本輪只完成 REAL Blender + provider contract，而沒有 live generation provider，合理結果應類似：

- realArtworkPreviewReady = true（只有 REAL Blender evidence 才能 true）
- productTruthRenderPackReady = true（若 AOV pack REAL）
- generativeRenderGatewayLogicReady = true
- liveH3MaxProviderReady = false/BLOCKED
- liveLtx25ProviderReady = false/BLOCKED
- liveVisionJudgeReady = false/MOCK
- physicalPrintValidated = false
- liveFactoryExecutionReady = false
- globalProductionReady = false

不要為了「全綠」改 truth label。

---

# Required negative / regression matrix

至少新增直接走正式 validator / acceptance path 的 negatives：

1. wrong `engineeringHash` in render pack → FAIL
2. wrong `artworkHash` / `placementHash` / `finalUvHash` → FAIL
3. mixed cameraRecipeHash among AOVs → FAIL
4. missing required AOV → FAIL
5. AOV SHA/size tamper → FAIL
6. product mask empty / impossible → FAIL
7. provider result references wrong renderPackId → FAIL
8. provider result claims `usedMock=false` without verifiable live provider evidence → FAIL
9. H3/LTX fixture output cannot set `live*ProviderReady=true`
10. generative result cannot mutate Product Truth manifest
11. mock Blender cannot set `realArtworkPreviewReady=true`
12. REAL Blender output with wrong object/artwork identity → FAIL
13. prior Round 8–12 Artwork Placement tamper matrix must remain passing; no regression.

---

# Evidence flow / Definition of Done

1. commit/push code as exact `CODE_EVIDENCE_SHA`。
2. 跑完整 `pytest -q`；回報 exact passed count。
3. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS。
4. 在 clean tree 跑新的 canonical acceptance runner；正式 evidence 禁止 `--allow-dirty`。
5. REAL Blender artwork evidence 必須是 `usedMock=false`，並有可核對 output SHA/size/job/worker/Blender/GPU/identity。
6. AOV/Product Truth Render Pack 全部 artifact lineage 可驗。
7. 如果 H3 MAX / LTX 2.5 沒有真實 provider/runtime，就保持 live provider false，不要阻塞 Product Truth Render Pack 的完成。
8. 更新 Progress/Audit/REAL_E2E/新增 acceptance docs。
9. docs/evidence commit push 後，docs/head Actions Ubuntu + Windows SUCCESS。
10. Issue #1 留完成交接：CODE SHA、pytest、CODE Actions、REAL Blender job/evidence、renderPackId、AOV status、provider truth labels、docs SHA/docs Actions。
11. **STOP，等待 ChatGPT Re-Gate；不得自行進 Phase 901+。**

# 禁止事項

- 不得重寫既有核心架構。
- 不得建立第二套 Cabinet mm / UV / Artwork authority。
- 不得把 generative output 當 Product Truth。
- 不得把 Mock/FIXTURE provider 當 live provider。
- 不得因 pytest/CI 綠燈宣稱 Production Ready。
- 不得因 REAL Blender preview 通過就宣稱 physical print validated。
- 不得自行啟用 LIVE_CNC / LIVE_LASER / PLC。
- 不得把 `globalProductionReady` / `fullAutonomousFactoryReady` 提升為 true，除非所有既有 blocker 真的被實證解除。
