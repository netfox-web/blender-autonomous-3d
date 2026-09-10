# Grok 修正指令：Phase 781–840 Re-Gate Round 4 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `f3ec67a1acdb5e8a8d96ab802eb823f724de2607`  
> CODE_EVIDENCE_SHA reviewed: `7d99b37f1587081613525409ad185a83b3bdb62d`  
> Canonical generation reviewed: `97e76079-0527-4313-ad37-6b1bd050a268`  
> CODE Actions: `34524185358` Ubuntu + Windows SUCCESS  
> docs/head Actions: `34524773277` Ubuntu + Windows SUCCESS  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪只補 Phase 781–840 Artwork Placement 的最後 authority / preview↔production parity 缺口。**不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore。**

## 已接受，不要退步

- `pytest -q`：**598 passed**；exact CODE `7d99b37...` Actions `34524185358` Ubuntu/Windows SUCCESS；docs/head `f3ec67a...` Actions `34524773277` SUCCESS。
- canonical generation `97e76079-0527-4313-ad37-6b1bd050a268` runner-bound to exact CODE、`workingTreeClean=true`。
- REAL preview gate 已要求 `usedMock=false`、REAL Blender、job/blender/device、artifact hash+size、`artworkApplied=true`、exact placement/object/component/FRONT/relation/final UV identity。
- `finalUvHash` 已改 deterministic SHA/stable hash，由 authoritative placement 重算比對。
- SINGLE_SURFACE 已不再誤走多門 quarter crop；stored source crop 會與重新推導值比對。
- MASTER_SPLIT 已有獨立 master relation store，基本 coordinated surface-set tamper 會 BLOCK。
- Blender 仍採單一 UV authority：FRONT mesh UV = final source UV、shader mapping identity。
- `realArtworkPreviewReady=false`、`physicalPrintValidated=false`、`globalProductionReady=false`、`fullAutonomousFactoryReady=false` 維持正確。
- CI 仍 `FOX3D_MOCK_BLENDER=1`，只能算 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不是 Production Ready。
- LIVE_CNC / LIVE_LASER / PLC 維持 **BLOCKED**；Demand / Vision / AI Video 維持 **MOCK**；print preflight 維持 **PARTIAL**。

---

# Blocker 1 — REAL preview 仍會讓 caller projection 影響實際 render bytes

目前 `preview()` 已先 `require_placement()` 得到 authoritative `live`，requested identity / hashes 也取自 `live`；但後續仍使用 caller 傳入的 `placement` 取得 `artworkId`、`productId`、`engineeringHash`，並把該 artwork path 當 `artwork_path` override 傳進 `blender_job_payload()`。

同時 `blender_job_payload()` 對每個 placementId 雖會重新取得 canonical placement / artwork，卻使用：

`path = artwork_path or art.get("path")`

也就是 caller override 優先。Blender worker 目前只檢查 image path 存在，然後把 payload 裡的 `artworkHash` 原樣回報；**worker 沒有對實際載入的 image bytes 做 SHA-256 驗證**。因此存在以下 fail-open：同 tenant 的另一張圖片可被 caller path override 實際 render，但 applied lineage 仍可能帶 canonical artworkHash / placementHash，最後誤過 `realArtworkPreviewReady`。

### Required correction

- 一旦有 `placementId`，`preview()` 後續所有 authority 必須只使用 `live`：
  - `live.artworkId`
  - `live.productId`
  - `live.engineeringHash`
  - `live.objectName/componentId/face/relation`
  - `placements=[live]` 或 `placement_ids=[live.placementId]`
- caller 傳入的 projection 只能是 request/reference，不得決定真正 render 的 artwork path 或 engineering payload。
- REAL authority path **不得接受未驗證的任意 `artwork_path` override**。最佳做法：`blender_job_payload()` 從 canonical `require_artwork()` 自己取得 path。
- 為消除 verify→worker load 的 TOCTOU，payload 請一併帶 canonical raw asset digest（例如 `artworkSha256`，來源是 `require_artwork()` 已驗過的 DAM bytes），worker 在 `bpy.data.images.load()` 前重新讀 bytes 做 SHA-256 exact compare；不符就 `ArtworkApplyError`，不得 `artworkApplied=true`。
- `artworkHash`（metadata/lineage hash）與 raw file SHA-256 不要混用；兩者分開命名、各自驗證。
- 如果保留 `artwork_path` 只供 unit/diagnostic，必須明確 non-authoritative，且 bytes digest 不符 canonical asset 時 fail-closed。

### Required tests

1. valid `placementId` + caller forged `artworkId`（同 tenant 另一張圖）不得影響實際 payload/render；最好直接 BLOCK caller mismatch，至少必須使用 canonical art。
2. valid `placementId` + forged `productId` / `engineeringHash` 不得選到另一份 engineering。
3. canonical lineage + arbitrary wrong `artwork_path` bytes 必須 BLOCK，不能 `artworkApplied=true`。
4. worker image bytes 在 submit 前後被換掉 → worker-side digest mismatch BLOCK。
5. canonical artwork path + digest 一致才可產生 applied record。

---

# Blocker 2 — SINGLE_SURFACE production file 尚未真正等價於 Blender placement（CONTAIN / anchor / rotation）

目前 `canonical_source_crop()` 雖重新從 artwork pixels + surface/placement/fit 推導，但其 COVER source crop固定置中，實際沒有使用 placement 的 x/y offset 或 `anchor`；`rotationDeg` 也沒有進 production raster transform。

更重要的是 `produce_panel(SINGLE_SURFACE)` 最後只把 source crop bytes直接寫成 PNG，卻把 manifest 的 `outputPhysicalMm` 標成整個 surface。對 `CONTAIN` 且 artwork aspect ratio ≠ surface 時，Blender preview 會有留白/偏移，但 production PNG 只有 artwork 本體；若把該 PNG當整片門板印刷，實際會被拉到 full surface，與 Blender preview 不一致。這違反本 Phase 的核心目標：**Engineering Surface mm = Artwork Placement = Blender Preview = Production Artwork**。

### Required correction

建立單一 deterministic production transform/composition（可重用現有 helpers，不要另建第二套 placement engine）：

- `CONTAIN`：production panel output 必須保留 canonical x/y placement、anchor 和留白；不能把 artwork crop 當 full-panel raster。
- `COVER`：source crop 必須依 authoritative placement offset/anchor 推導，不得一律 center crop。
- `rotationDeg` / `mirrored`：production output 必須與 Blender `finalSampling` 的方向一致；若某 transform 尚未支援 production，應 fail-closed / PARTIAL，而不是標 `productionArtworkFileReady=true`。
- 對 full-panel production raster，manifest 必須明確記錄：canvas physical mm、pixel dimensions / dpi、placed artwork rect、source crop、rotation、mirror、background/alpha policy、placementHash、final transform hash。
- 不准用 resize/stretch 偷偷補滿 surface；STRETCH 仍 BLOCKED。
- 建議新增一個 parity identity：由同一 canonical placement 推導 Blender final UV 與 production transform，runner 驗兩邊對同一 source region / orientation / panel coordinates。

### Required tests

至少用非等比例 artwork 覆蓋：

1. `CONTAIN + CENTER`：輸出 canvas 有正確留白，內容 rect mm 與 Blender placement一致。
2. `CONTAIN + LEFT/TOP/RIGHT/BOTTOM`（依既有 ANCHORS 實際枚舉）：留白方向/offset正確。
3. `COVER + LEFT/CENTER/RIGHT` 或 TOP/CENTER/BOTTOM：sourceXPx/sourceYPx 隨 anchor 改變，不能永遠置中。
4. 90/180/270 rotation + mirror：production orientation 與 `finalSampling` parity；未支援就 BLOCK。
5. manifest `outputPhysicalMm` 與 raster/dpi/placement semantics 不可自相矛盾。
6. negative：coordinated crop + placementHash、anchor/rotation projection tamper 仍 BLOCK。

---

# Blocker 3 — MASTER relation authority 尚未完整 replay 自己的 seam / relation integrity

`place_across_panels()` 允許 `master_canvas(surfaces, seam_mm=seam_mm)`，並把 `seamMm`、`panelOrder`、`cropGeometry` 存進 master relation；但 `_authoritative_master()` 之後卻用 `master_canvas(siblings)` 重建，**沒有使用 relation 裡已授權的 `seamMm`**。若合法建立時傳 explicit seam，後續 replay 可能得到不同 masterHash；而 relation 的 `panelOrder/cropGeometry/relationHash` 也沒有被完整 self-verify。

### Required correction

- master relation record 要能 deterministic replay：使用 authoritative relation 的 canonical seam（或若產品政策只允許 engineering seam，就在建立時拒絕不同 seam，不要存一份之後無法 replay 的 config）。
- `require_master()` / `_authoritative_master()` 必須驗 relation 自身 integrity：重算 `relationHash`，並 exact check `masterId/masterHash/tenant/product/version/engineeringHash/surfaceIds/panelOrder/seamMm/widthMm/heightMm/cropGeometry`。
- placement 的 `masterId` 若 Phase schema宣稱必填，就必須 exact match，不可把 missing/blank 當合法；`masterSurfaceIds` projection 若保留，也要明確規則（exact projection或完全移除），不要半信半不信。
- re-derived master/crops 必須從 independent relation + authoritative surfaces 得出，不能回頭信 placement projection。

### Required tests

1. explicit non-default seam 的合法 master create → require_placement → produce_panel 可 deterministic round-trip（若政策允許）。
2. tamper relation `seamMm` / `panelOrder` / `cropGeometry` / `relationHash` 任一欄 → BLOCK。
3. missing/forged `masterId` → BLOCK（若 masterId 保留為 authority identity）。
4. coordinated placement `masterSurfaceIds/masterHash/placementHash` tamper仍 BLOCK，舊 regression維持。

---

# Re-Gate evidence required

完成 correction 後：

1. source + tests commit/push 新 **CODE_EVIDENCE_SHA**。
2. full `pytest -q` PASS。
3. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS。
4. 在 exact CODE SHA clean tree 跑 Artwork canonical runner，產生新的 `acceptanceGenerationId`，`evidenceCodeCommit=<exact CODE SHA>`、`workingTreeClean=true`。
5. runner 必須新增上述 caller-authority、CONTAIN/COVER/anchor/rotation production parity、master seam/integrity negative/positive evidence；不能只靠 synthetic `preview_ready_from_job()`。
6. 更新 `docs/GROK_PROGRESS_REPORT.md`、`docs/CURRENT_IMPLEMENTATION_AUDIT.md`、`docs/REAL_E2E_ACCEPTANCE.md`、`docs/ARTWORK_PLACEMENT_ACCEPTANCE.md/.json`。`CABINET_REAL_ACCEPTANCE.md` 沒有 truth change 就不要硬改。
7. 若本機沒有 REAL artwork OptiX render，維持 `realArtworkPreviewReady=false`；若有，必須含 actual artifact SHA/size/job/GPU/device + worker-verified artwork raw digest + exact applied identity。
8. `physicalPrintValidated` 仍只能由真實實體印刷/量測證據變 true；本輪軟體 parity不能冒充 physical validation。
9. docs/head Actions Ubuntu + Windows SUCCESS。
10. Issue #1 留短回報：CODE SHA、pytest count、CODE run、canonical generation、docs SHA/run、REAL/MOCK/PARTIAL/BLOCKED。
11. **STOP。Phase 841+ 仍不得開始，等 ChatGPT Re-Gate。**

## Definition of Done

Phase 781–840 只有在以下情況才可放行：

> caller projection 無法替換 canonical artwork/engineering/render bytes；worker 能驗實際載入 artwork bytes identity；SINGLE_SURFACE 的 CONTAIN/COVER/anchor/rotation/mirror 在 production output 與 Blender placement 使用同一 canonical transform且不 stretch；MASTER_SPLIT relation 可以 deterministic replay並自驗 seam/order/crop/integrity；Mock/physical/live truth boundary維持正確。
