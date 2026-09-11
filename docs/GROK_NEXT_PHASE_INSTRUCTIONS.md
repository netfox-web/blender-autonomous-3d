# Grok 修正指令：Phase 781–840 Re-Gate Round 7 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `f586f3ef823e9be9e2dabc38d281f33a5e4d71c6`  
> Reviewed CODE: `1661da5b31842e5eb0c3a0ff9c695b4722c00c68`  
> Canonical generation: `62bed682-1076-4e06-9e1e-d1a971d46793` (`workingTreeClean=true`, `evidenceCodeCommit=1661da5...`)  
> CODE Actions: `34544647655` Ubuntu + Windows SUCCESS  
> docs/head Actions: `34546147312` Ubuntu + Windows SUCCESS  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪只做 **correction-only**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore，也不要自行擴張 Phase 841+。

## 本輪已接受，禁止退步

Round 6 有實質完成，以下接受：

1. `measure_orientation_parity(..., fit, anchor)` 已泛化，CONTAIN CENTER 與 COVER LEFT/CENTER/RIGHT 都有 0/90/180/270/mirror/mirror90 matrix。
2. COVER UV 已改為 authoritative source crop window，並與 production raster transform 共用語義。
3. required nested orientation matrix 已 fail-closed；缺 anchor / orientation row 會 FAIL。
4. exact CODE `1661da5...` 的 pytest 為 **605 passed**，GitHub Actions Ubuntu + Windows SUCCESS。
5. canonical acceptance 為新 generation `62bed682-...`，`workingTreeClean=true`、`evidenceCodeCommit=1661da5...`、`ok=true`。
6. truth boundary 正確：`realArtworkPreviewReady=false`、`physicalPrintValidated=false`、Demand/Vision/AI Video MOCK、print preflight PARTIAL、LIVE_CNC/LIVE_LASER BLOCKED、`globalProductionReady=false`、`fullAutonomousFactoryReady=false`。
7. `CABINET_REAL_ACCEPTANCE.md` 無 cabinet engineering truth change，保持不動是正確的。

以上不要回退。

---

# 唯一核心 Blocker — COVER CENTER pixel oracle 仍是非辨識型（degenerate oracle）

目前 canonical evidence 雖然有 COVER LEFT/CENTER/RIGHT × 全 orientation，但 **COVER CENTER** 的 expected / observed 四角在 0/90/180/270/mirror/mirror90 全部都是同一個灰色 `[80, 80, 80]`。

也就是：即使 CENTER 的 rotation / mirror 實作錯了，這個 oracle 仍可能 PASS。這不符合上一輪 Definition of Done：必須用 asymmetric pixel landmark 真正證明 Blender sampling 與 production PNG 對同一 source region / orientation，而不是只證明「取到一塊均勻區域」。

## Required correction

用最小改動強化 **oracle 本身的可辨識性**，不要另造第二套 artwork engine：

### 1. 改用 crop 內部可辨識的 deterministic test raster

目前 landmark 圖的 CENTER crop 落在均勻灰色區，必須調整測試 raster / landmark 分佈，使 LEFT / CENTER / RIGHT 三個 COVER crop 各自都包含足夠的非對稱資訊。

可接受做法：

- 建立 deterministic coordinate-coded / asymmetric landmark raster；
- 不只在原圖四個外角放顏色，還要在內部多個位置放唯一值；
- 或使用 3×3 / 5×5 的 canonical sample grid，讓 CENTER crop 也能判斷方向；
- sample 點避開 crop 邊界與插值敏感位置，保持 deterministic nearest / integer pixel semantics。

### 2. 每個 COVER anchor 都必須有「oracle quality gate」

對 COVER `LEFT / CENTER / RIGHT`，在送進 PASS 前先驗 oracle 是否具辨識力。至少要有等價條件：

- 每個 anchor 的 baseline expected sample signature 不能是全相同值；
- 至少有 **3 個不同 sample values / landmark identities**；
- 0 / 90 / 180 / 270 / mirror / mirror90 中，理論上應不同的 orientation signature 不可全部相同；
- 若測試素材本身對某 transform 對稱到無法辨識，該案例必須 `BLOCKED_ORACLE` / FAIL，而不是 PASS。

建議在 acceptance row 明確輸出：

```json
{
  "oracleDiscriminating": true,
  "uniqueSampleCount": 4,
  "signature": "..."
}
```

欄位名稱可不同，但 validator 必須 fail-closed：欄位缺失、false、或 unique count 不足都不能 PASS。

### 3. expected 與 observed 必須保持獨立來源

- expected：由 authoritative source bytes + authoritative source crop + canonical transform 計算。
- Blender-side：使用 `uvRect` / `finalSampling` 驗 source region / orientation。
- observed：重新讀 production PNG 實際 pixels。
- 不可用 production output 反推 expected，也不可只用 `finalUvHash` / `transformHash` 自證。

### 4. 增加「錯 transform 必定被抓到」negative regression

至少針對 **COVER CENTER** 增加負向測試：

- 將 expected rotation 固定 0，但 observed/worker sampling 模擬成 90（或交換 corner permutation），必須 FAIL；
- mirror false ↔ true mismatch 必須 FAIL；
- crop 不變但 orientation 被 tamper，必須 FAIL；
- 若把 CENTER orientation signatures 全改成同值，validator/oracle quality 必須 FAIL。

LEFT / RIGHT 也至少各保留一個錯 orientation regression，避免未來 landmark 改動導致 oracle 再次失去辨識力。

### 5. canonical acceptance matrix 必須證明 CENTER 不再退化

新的 `orientationParity` 至少保留：

```json
"CONTAIN": {
  "CENTER": {"0": {}, "90": {}, "180": {}, "270": {}, "mirror": {}, "mirror90": {}}
},
"COVER": {
  "LEFT":   {"0": {}, "90": {}, "180": {}, "270": {}, "mirror": {}, "mirror90": {}},
  "CENTER": {"0": {}, "90": {}, "180": {}, "270": {}, "mirror": {}, "mirror90": {}},
  "RIGHT":  {"0": {}, "90": {}, "180": {}, "270": {}, "mirror": {}, "mirror90": {}}
}
```

且每個 COVER anchor 要能從 evidence 直接看出它不是 uniform / degenerate oracle。

---

# Required evidence flow

完成上述窄修正後：

1. source + tests commit/push，形成新的 exact **CODE_EVIDENCE_SHA**。
2. full `pytest -q` PASS，回報 exact count。
3. exact CODE SHA GitHub Actions Ubuntu + Windows 都 SUCCESS。
4. 注意 CI 仍 `FOX3D_MOCK_BLENDER=1`，只能標 `MOCK/unit/integration + FIXTURE/REAL_LOGIC`，不可標 Production Ready。
5. 在 exact CODE SHA clean tree 執行：
   - `scripts/run_artwork_placement_e2e.py --expected-commit <CODE_SHA>`
   - 正式 evidence 不得用 `--allow-dirty`。
6. 新 canonical acceptance 必須：
   - `workingTreeClean=true`
   - `evidenceCodeCommit=<exact CODE_SHA>`
   - 新 `acceptanceGenerationId`
   - `ok=true`
   - CONTAIN + COVER full matrix
   - COVER LEFT/CENTER/RIGHT 全部 oracle discriminating
   - negative wrong-rotation / wrong-mirror regression fail-closed
   - 既有 masterId coordinated tamper、required scenario deletion 等不得退步。
7. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.json`
8. `docs/CABINET_REAL_ACCEPTANCE.md` 若 cabinet engineering truth 沒變就不要為了湊 commit 硬改。
9. evidence/docs commit push 後，確認 docs/head Actions Ubuntu + Windows SUCCESS。
10. Issue #1 留完成回報：CODE SHA、pytest count、CODE run、canonical generation、docs SHA/run、REAL/MOCK/PARTIAL/BLOCKED。
11. **STOP。等待 ChatGPT Re-Gate。不要自行開始 Phase 841+。**

---

# Truth labels 必須維持

- Artwork geometry / placement / production raster parity：**REAL_LOGIC / FIXTURE evidence**（canonical pass 後）。
- GitHub Actions pytest：**MOCK/unit/integration** (`FOX3D_MOCK_BLENDER=1`)。
- `realArtworkPreviewReady=false / MOCK`，除非未來真的跑 artwork path 的 REAL Blender/OptiX evidence，且 artifact SHA/size/device/loaded artwork SHA/placement lineage 全綁 exact CODE。
- `physicalPrintValidated=false`，除非有實體印刷與尺寸量測 evidence。
- Demand / Vision / AI Video：**MOCK**。
- print preflight / OS sandbox / AR / barcode / McKee-BCT：**PARTIAL**。
- LIVE_CNC / LIVE_LASER / PLC / liveFactory：**BLOCKED**；`liveMachineControl=false`。
- `globalProductionReady=false`、`fullAutonomousFactoryReady=false`、`liveFactoryExecutionReady=false`。

## Definition of Done

Phase 781–840 這輪只有在以下全部成立才可再次送 Re-Gate：

> COVER LEFT/CENTER/RIGHT 的 source crop 都有可辨識 asymmetric pixel evidence；每個 anchor 的 0/90/180/270/mirror/mirror90 都能真正區分 orientation；錯 rotation/mirror 會被獨立 pixel oracle 抓出；exact CODE CI 綠；clean-tree canonical bundle 綁 exact CODE；truth labels 正確。Phase 841+ 繼續 HOLD。
