# Grok 下一輪開發指令：Phase 841–900 Re-Gate Round 1 — Product Truth Evidence Authority / Artwork Mask Correction

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `3f8a1ed00c0145cc3feff5a52ccf5cb492f47b68`  
> CODE_EVIDENCE_SHA: `4a88680c4e08fc0b2a077a0309489aaa6b34deb1`  
> Canonical generation: `9a5a1df4-e74c-4951-8c37-a9f41b950bcf`  
> Re-Gate result: **CHANGES REQUIRED — do not start Phase 901+.**

## 0. 本輪範圍

這是 **correction-only Re-Gate**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、ArtworkPlacement、ManufacturingRelease、WorkOrder、MaterialLot、Backup/Restore，也不要建立第二套 renderer 或第二套 mm / UV / Product Truth source of truth。

固定原則不變：

> **模型可替換，Product Truth 不可替換。**

H3 MAX / LTX 2.5 仍只是一層 provider boundary；沒有 live runtime/evidence 就保持 BLOCKED/MOCK。不得把 pytest / CI / fixture 當 Production Ready。

## 1. 已接受，不需重做

目前可接受的部分：

- `pytest -q` 回報 **612 passed**；這仍是 MOCK/unit/integration + FIXTURE/REAL_LOGIC 測試，不是 Production Ready。
- exact CODE Actions `34604724211` 已確認 Ubuntu + Windows SUCCESS。
- docs/head Actions `34607027316` 已確認 Ubuntu + Windows SUCCESS。
- canonical evidence 綁 `4a88680`、`workingTreeClean=true`。
- REAL Blender 5.2.1 LTS + NVIDIA T1000 OptiX job 已有 `usedMock=false` evidence。
- Generative Gateway contract / routing 可維持 REAL_LOGIC；live H3 MAX / LTX 2.5 維持 BLOCKED。
- Vision Judge 維持 MOCK；`physicalPrintValidated=false`；LIVE_CNC / LIVE_LASER BLOCKED；`globalProductionReady=false`；`fullAutonomousFactoryReady=false`。
- `docs/CABINET_REAL_ACCEPTANCE.md` 的 engineering truth 不需為本輪湊文件而改。

## 2. Blocker A — ArtworkMask 目前不是獨立 printable-surface authority

目前 canonical REAL evidence 中：

- `product_mask` SHA256 = `2fe4119ae51d552828971a51641e6ee2b92dfe544a232acbc54761f26b3de83e`
- `artwork_mask` SHA256 = `2fe4119ae51d552828971a51641e6ee2b92dfe544a232acbc54761f26b3de83e`
- size / occupancy 也相同。

而 REAL worker path 目前在缺 `artwork_mask.png` 時直接把 `product_mask.png` 當 artwork mask。這只能標 **PARTIAL**，不能讓 `productTruthRenderPackReady=true`。

### 必修

1. REAL Blender path 必須產生真正的 **Artwork / Printable Surface Mask**，來源必須是 canonical `ArtworkPlacement + PrintableSurface + componentId/objectName + face=FRONT`。
2. REAL path 禁止：
   - `artwork_mask = product_mask`
   - 因缺 mask 而 silent alias / silent fallback 後仍標 REAL。
3. 對本輪 4-door / single-door placement canonical case，ArtworkMask 必須語意上只代表被指定的 printable FRONT surface / artwork region，不可代表整個 cabinet/product occupancy。
4. validator 至少驗：
   - mask artifact 真實存在、SHA/size/dimensions 可讀；
   - 非全黑 / 非不合理全白；
   - ArtworkMask 與 ProductMask 的關係符合「printable surface 是 product 的子集合/可驗證區域」；
   - 此 canonical case 若 `artwork_mask` 與 `product_mask` byte-identical，直接 FAIL；
   - mask identity 必須綁 `componentId/objectName/face/surfaceHash/placementHash/finalUvHash`。
5. 若 REAL Blender 當前無法產生獨立 ArtworkMask，合理結果是：
   - `realArtworkPreviewReady` 可依真正 preview evidence 評估；
   - `productTruthAovPackReady=false`；
   - `productTruthRenderPackReady=false`；
   - status = PARTIAL/BLOCKED；
   而不是生成假 mask 補綠。

## 3. Blocker B — REAL Blender output identity 現在由 pack builder「事後貼標籤」，未被 worker evidence 獨立驗證

目前 `build_pack()` 會把 canonical placement/hash 寫進 AOV manifest，但 validator 沒有證明 REAL Blender worker 實際吃到的就是同一份 artwork / placement / object / face。這不符合前一輪 Required Negative #12：**REAL Blender output with wrong object/artwork identity → FAIL**。

### 必修

REAL Blender job/result evidence 必須回傳並由 validator exact compare：

- `engineeringHash`
- `artworkId`
- `artworkHash`
- `artworkSha256`（需與 DAM 真實 bytes SHA 一致）
- `placementId`
- `placementHash`
- `finalUvHash`
- `surfaceHash`
- `componentId`
- `objectName`
- `face`，本 canonical case 必須 `FRONT`
- `cameraRecipeHash`
- `sceneRecipeHash`
- `blenderJobId`
- Blender version / worker / GPU
- `usedMock` exact bool
- `realBlender` exact bool
- `realOptix` exact bool

不得只因 `done.realBlender=true` 就把 pack 內 canonical hashes 視為 output evidence。

### REAL readiness 必須 fail-closed

要設 `realArtworkPreviewReady=true` / `productTruthRenderPackReady=true` 時至少要求：

- `usedMock is False`
- `realBlender is True`
- `realOptix is True`（本輪既有 OptiX acceptance scope）
- job/version/worker/GPU 非空
- worker/result identity 與 authoritative request/placement exact match
- output artifact SHA/size/dimensions 真實可驗

任何 wrong/missing object、component、face、artwork SHA/hash、placementHash、finalUvHash、surfaceHash → FAIL。

## 4. Blocker C — 前一輪要求的兩種 canonical preview evidence 尚未完整獨立證明

Phase 841–848 原指令要求至少：

1. **4-door master 中一門的 canonical artwork preview**；
2. **完整 4-door assembled view**。

目前 canonical scenario 只有單一 Product Truth render pack / HERO_FRONT evidence，沒有清楚的兩個獨立 view artifact acceptance。

### 必修

同一個 product truth 下，產生並發布至少兩個可驗證 view：

- `DOOR_DETAIL`：指定 door/component 的 FRONT artwork detail；
- `ASSEMBLED_FRONT`：完整四門櫃 assembled view。

每個 view 必須有自己的：

- artifact/DAM ref
- SHA256 / size / dimensions
- cameraRecipeHash
- Blender job/output identity

但共享同一 authoritative：engineering/artwork/placement lineage。可以在既有 ProductTruthRenderPack manifest 中最小幅擴充 views，不要另建 renderer。

少任一 view → Phase 841–900 acceptance FAIL / PARTIAL，不得進 901+。

## 5. Acceptance runner / readiness 不得 fail-open

修正 runner / validator：

1. `ok=true` 前，必須重新驗證：
   - REAL job identity authority；
   - 真 ArtworkMask authority；
   - 兩種 required canonical preview views；
   - AOV hash/size/dims/lineage；
   - mock/live truth boundary。
2. builder 不可把未驗證 worker output 事後補 canonical lineage 後直接視為 REAL proof。
3. fixture AOV fallback 可以保留作 MOCK/FIXTURE 測試，但必須讓 REAL readiness false。
4. `usedMock` / `realBlender` / `realOptix` 對 REAL evidence 使用 strict boolean schema；不要用 truthy coercion。
5. CameraRecipe / SceneRecipe 若本輪碰 validator，順便收斂 required/strict finite fields；不要用 missing 值透過 `or default` 在驗收時偷偷變成 canonical default。

## 6. Required negative regression matrix

至少新增直接走正式 validator / acceptance path 的 tests：

1. REAL canonical 4-door case：`product_mask` 複製成 `artwork_mask` → FAIL。
2. ArtworkMask 指到 wrong component / wrong object / non-FRONT face → FAIL。
3. wrong artwork bytes SHA / DAM artifact → FAIL。
4. worker evidence wrong `artworkHash` / `placementHash` / `finalUvHash` / `surfaceHash` → FAIL。
5. worker evidence missing/wrong `componentId` / `objectName` → FAIL。
6. `realBlender=true` 但 `realOptix=false` → REAL readiness false。
7. `usedMock` / `realBlender` / `realOptix` 為 string/int/null 等非 exact bool → REAL readiness false / FAIL。
8. 缺 `DOOR_DETAIL` 或缺 `ASSEMBLED_FRONT` → Phase acceptance FAIL。
9. AOV manifest 被事後 coordinated tamper，但 worker evidence 不一致 → FAIL。
10. fixture fallback 仍不可把 `realArtworkPreviewReady` / `productTruthRenderPackReady` 設 true。
11. 既有 Phase 841–900 negatives 全保留。
12. Round 8–12 Artwork Placement tamper matrix 全保留，不能 regression。

## 7. Evidence / Definition of Done

完成後停止，等 ChatGPT Re-Gate；不要開始 Phase 901+。

必須提供：

1. 新的 exact `CODE_EVIDENCE_SHA`。
2. 完整 `pytest -q` exact passed count。
3. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS。
4. clean tree REAL canonical runner，禁止正式 evidence 用 `--allow-dirty`。
5. REAL Blender 5.2.1 + T1000 OptiX job evidence：`usedMock=false`、identity exact bound。
6. `DOOR_DETAIL` + `ASSEMBLED_FRONT` 兩個 REAL artifact evidence（SHA/size/dimensions/DAM/camera/job）。
7. ProductMask 與真正 ArtworkMask 的 distinct/semantic proof；canonical case 不得再同 SHA。
8. 新 generation + runner-bound `evidenceCodeCommit` + `workingTreeClean=true`。
9. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md/.json`
   - `docs/GENERATIVE_RENDER_GATEWAY_ACCEPTANCE.md/.json`（若 gateway evidence 有變）
   - `docs/CABINET_REAL_ACCEPTANCE.md` 僅在 cabinet engineering truth 真有變時才改。
10. docs/evidence commit push 後，docs/head Actions Ubuntu + Windows SUCCESS。
11. Issue #1 留簡短完成交接：CODE SHA、pytest、CODE Actions、generation、兩 view evidence、ProductMask/ArtworkMask 狀態、provider truth labels、docs SHA/docs Actions。

## 8. Truth boundary 必須維持

- Generative Gateway contract / routing：REAL_LOGIC。
- live H3 MAX：BLOCKED，除非真 provider/runtime + request/response evidence。
- live LTX 2.5：BLOCKED，除非真 provider/runtime + request/response evidence。
- quality benchmark：UNVERIFIED，除非真 benchmark。
- Vision Judge：MOCK/BLOCKED（沒有 live model 就不能升級）。
- `APPROVED_FOR_ASSET_REVIEW` ≠ production ecommerce asset。
- `physicalPrintValidated=false`。
- LIVE_CNC / LIVE_LASER / PLC：BLOCKED。
- `liveFactoryExecutionReady=false`。
- `globalProductionReady=false`。
- `fullAutonomousFactoryReady=false`。

**不要為了全綠而改 truth label；這輪的目標是把 Product Truth evidence authority 做到真的 fail-closed。**
