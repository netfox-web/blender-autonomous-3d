# Grok 修正指令：Phase 781–840 Re-Gate Round 5 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `27de6c8d0376d89d7678ce77d20e6738c0cc1372`  
> CODE_EVIDENCE_SHA reviewed: `ce2c46c0535fb2bbba2208401a51a66d4991ffaa`  
> Canonical generation reviewed: `2936750f-8a3c-4bb5-90ab-70741ea6f21d`  
> CODE Actions: `34532967434` Ubuntu + Windows SUCCESS  
> docs/head Actions: `34533523171` Ubuntu + Windows SUCCESS  
> `pytest -q`: **601 passed**  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪只補 Artwork Placement V1 最後的 UV rotation / preview↔production parity / master identity / acceptance fail-closed 缺口。**不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore。**

## 本輪已接受，禁止退步

- caller projection 已不能替換 canonical artwork/product/engineering；`preview()` 以 live placement 為 authority。
- Blender payload 帶 canonical `artworkSha256`，worker 在套圖前重讀實際 image bytes 做 SHA-256 exact compare；digest mismatch BLOCK。
- SINGLE_SURFACE production 已有 full-surface canvas；CONTAIN 有 letterbox；COVER 會依 anchor/placement 推導 source crop；rotation/mirror 已進 production raster transform；STRETCH 仍 BLOCKED。
- MASTER relation 已保存 `seamSource`；CONFIG seam 可 deterministic replay；relationHash/seam/order/cropGeometry/masterHash 等已有基本 self-check。
- `realArtworkPreviewReady=false` 維持正確：本輪沒有 REAL artwork OptiX render，不可升 REAL。
- `physicalPrintValidated=false` 維持正確。
- CI 仍 `FOX3D_MOCK_BLENDER=1`，601 PASS 只能算 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不是 Production Ready。
- Demand / Vision / AI Video = **MOCK**；print preflight / OS sandbox / AR / barcode / McKee-BCT = **PARTIAL**；LIVE_CNC / LIVE_LASER / PLC / liveFactory = **BLOCKED**。

---

# Blocker 1 — 90°/270° UV rotation 對非正方形 uvRect 的數學目前是錯的

目前 `src/fox3d/artwork.py::canonical_final_sampling()` 與 `scripts/blender_job.py::canonical_uv_mapping()` 都是把 **絕對 UV 座標**直接繞 `(u0+u1)/2,(v0+v1)/2` 做 Euclidean 90° rotation：

```python
(cx - (y - cy), cy + (x - cx))
```

這只有在 UV rect 為正方形時才不會改變 source region。Artwork Placement 的真實案例通常不是正方形：

- SINGLE_SURFACE `CONTAIN` 可能是 `u=0..1, v=.375..625`；
- MASTER_SPLIT 四門可能是 `u=0..0.25, v=0..1`。

對這種 rect 做現在的 90° rotation，corners 會跑出原 uvRect，甚至可能跑出 `[0,1]`；例如 `u=0..0.25, v=0..1` 旋轉 90° 可得到約 `u=-0.375..0.625`。這代表 Blender preview 可能取到**不同 source pixels**，而 production raster 目前是 `orient_rgb()` 對原 source crop 做旋轉，所以兩邊仍非真正 parity。

### Required correction

建立一個唯一 canonical quarter-turn transform，兩邊共用相同語義：

- 先在 **rect-local normalized coordinates** `(s,t) ∈ [0,1]²` 做 0/90/180/270 + mirror，最後才 map 回 `[u0,u1] × [v0,v1]`；或直接用 corner permutation。
- quarter-turn 後所有 final UV corners **必須仍在原 canonical uvRect bounds 內**（允許浮點 epsilon），不得因 rect aspect ratio 改變而擴張 source region。
- `canonical_final_sampling()` 與 Blender worker `canonical_uv_mapping()` 不得維護兩份可能漂移的 rotation 規則；至少要用 shared deterministic table/algorithm並互相測 exact parity。
- 明確定義 transform order（例如 `mirror local-X` → `rotate quarter-turn`，或相反），production `orient_rgb()` 必須完全同一 order。
- 不要用 shader Mapping node 再套第二次 transform；仍維持 Scheme A / identity shader。

### Required tests

用**非正方形 uvRect**直接測：

1. `[0,1] × [.375,.625]` 的 90/180/270 + mirror。
2. `[0,.25] × [0,1]` 的 90/180/270 + mirror。
3. 每個 final corner 都在 canonical uvRect bounds 內。
4. 0/90/180/270 做四次 cycle 回原 orientation。
5. artwork-side `canonical_final_sampling` 與 worker-side `canonical_uv_mapping.finalSampling` exact/epsilon equal。
6. malformed/non-quarter rotation 仍 BLOCK。

---

# Blocker 2 — 現有 rotation parity 證據只比「同一套邏輯算出的 hash」，沒有證明 source pixels 一致

Round 4 的 `test_contain_cover_anchor_rotation_production_parity()` 對 rotation 主要驗：

- `rot_prod["rotationDeg"] == 90`
- `rot_prod["finalUvHash"] == applied_identity(...)["finalUvHash"]`

但兩個 hash 都來自同一套 canonical math；若 canonical math 自己錯，這仍會一起 PASS。現有 canonical runner 也只記錄 `rotationDeg=90 + finalUvHash/transformHash`，沒有 180、270、mirror，更沒有 asymmetric pixel landmark 對照。上一輪要求的「90/180/270 rotation + mirror production orientation 與 finalSampling parity」尚未完整證明。

### Required correction

新增一個**獨立 pixel-oracle parity test**，不能只 hash 自證：

- 產生非對稱 source artwork，例如四角/中心使用可辨識 RGB marker 或 3×2 / 4×3 landmark grid。
- 對 CONTAIN 與 COVER 至少各做：0、90、180、270、mirror、mirror+90（建議完整 8 orientations）。
- 從 canonical finalSampling 推導 Blender FRONT face 四角預期取樣的 source landmark；再讀 production PNG 實際對應 landmark，比對 orientation / source region。
- COVER 必須同時覆蓋 LEFT/CENTER/RIGHT（或 TOP/CENTER/BOTTOM，依 crop axis），確保 anchor 先決定 source crop，再套 orientation，順序固定。
- CONTAIN 要檢查 letterbox 位置與 rotated artwork landmarks；不能只驗黑邊存在。
- 若某組合不能保證 parity，先標 PARTIAL/BLOCK，不可 `productionArtworkFileReady=true`。

### Canonical evidence required

`ARTWORK_PLACEMENT_ACCEPTANCE.json/.md` 至少新增可機器驗證的：

- `orientationParity.0`
- `orientationParity.90`
- `orientationParity.180`
- `orientationParity.270`
- `orientationParity.mirror`
- `orientationParity.mirror90`

每項包含 source landmark expectation、production observed landmark、uv bounds/identity、PASS/BLOCK；不要只放一個 hash 字串。

---

# Blocker 3 — MASTER `masterId` 尚未被 relationHash 自身綁定，仍可 coordinated tamper

目前 `master_relation_hash()` 的 `_MASTER_RELATION_FIELDS` 包含 `masterHash/tenant/product/.../cropGeometry`，**但沒有 `masterId`**。`_authoritative_master()` 雖要求 `placement.masterId == relation.masterId`，若 relation.masterId 與所有 placements.masterId 一起被修改，並重新計算 placementHash，relationHash 本身不會變，因此 `masterId` 沒有 independent integrity binding。

上一輪要求的是 relation 對 `masterId/masterHash/...` 做 exact integrity 驗證，因此這點尚未達標。

### Required correction

二選一，選最小改動：

- 將 `masterId` 納入 `_MASTER_RELATION_FIELDS` / `relationHash`；或
- 讓 `masterId` deterministic derive from immutable relation identity，require 時重新推導 exact match。

不要同時保留「random masterId」又不讓任何 independent digest 綁它。

### Required tests

1. 只改 relation.masterId → BLOCK。
2. coordinated 改 relation.masterId + 所有 placement.masterId + 重新 placementHash → 仍 BLOCK。
3. legitimate relation round-trip仍 PASS。

---

# Blocker 4 — acceptance validator 對新增 scenario 仍 fail-open

`validate_artwork_acceptance_result()` 現在對 `containCenter / coverAnchor / rotationParity / masterSeam` 多採：

```python
if scenario:
    ...validate...
```

因此 scenario 若整個遺失、變成 `{}`、runner regression 沒產生，validator 可能完全不追加 failure。這不符合 canonical evidence fail-closed。

### Required correction

- Round 4/5 宣稱為 required 的 scenario 必須是 **required set**；missing、wrong type、empty、missing critical field 都要 failure。
- 至少 require：`cabinet4Single`、`containCenter`、COVER anchor parity、orientation parity matrix、master seam replay、caller forged preview art、wrong path/digest、master relation tamper、missing masterId。
- negative matrix 不得只把任意 truthy string 當 PASS；expected `BLOCKED` / expected error code 必須 exact。
- canonical runner 的 top-level `ok` 與 validator 都要獨立 fail-closed；刪掉任何一個 required evidence row，acceptance 必須失敗且不得 publish成功 canonical bundle。

### Required tests

1. 從一份原本 PASS 的 result 依序刪除每個 required scenario → validator FAIL。
2. scenario `{}` / wrong type → FAIL。
3. negative value從 `BLOCKED` 改 `passed` / `True` / missing → FAIL。
4. orientation 只剩 90、缺 180/270/mirror → FAIL。

---

# Re-Gate evidence required

完成 correction 後：

1. source + tests commit/push 新 **CODE_EVIDENCE_SHA**。
2. full `pytest -q` PASS。
3. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS。
4. 在 exact CODE SHA clean tree 跑 Artwork canonical runner，產生新的 `acceptanceGenerationId`；`evidenceCodeCommit=<exact CODE SHA>`、`workingTreeClean=true`。
5. canonical runner 必須真的包含非正方形 UV quarter-turn、pixel landmark parity、180/270/mirror、masterId coordinated tamper、required-scenario deletion fail-closed evidence。
6. 更新 `docs/GROK_PROGRESS_REPORT.md`、`docs/CURRENT_IMPLEMENTATION_AUDIT.md`、`docs/REAL_E2E_ACCEPTANCE.md`、`docs/ARTWORK_PLACEMENT_ACCEPTANCE.md/.json`。`CABINET_REAL_ACCEPTANCE.md` 無 truth change 不要硬改。
7. 若沒有 REAL artwork OptiX render，`realArtworkPreviewReady=false`；不要借用舊 Blender media把新 artwork path升 REAL。
8. `physicalPrintValidated=false`，除非有實體印刷/尺寸量測證據。
9. docs/head Actions Ubuntu + Windows SUCCESS。
10. Issue #1 短回報：CODE SHA、pytest count、CODE run、canonical generation、docs SHA/run、REAL/MOCK/PARTIAL/BLOCKED。
11. **STOP。Phase 841+ 仍不得開始，等待 ChatGPT Re-Gate。**

## Definition of Done

Phase 781–840 只有在以下條件同時成立才可放行：

> 非正方形 uvRect 的 90/180/270/mirror 不會改變 canonical source bounds；Blender finalSampling 與 production pixels 用獨立 landmark oracle 證明同 source region / orientation；masterId 被 independent relation integrity 綁定；canonical acceptance 對所有 required scenario/negative evidence fail-closed；Mock/physical/live truth boundary維持正確。
