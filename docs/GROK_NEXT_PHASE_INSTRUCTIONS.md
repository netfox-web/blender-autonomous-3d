# Grok 修正指令：Phase 781–840 Re-Gate Round 6 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `b2d9875963c8ee6d274c18a79b47ed7b14d81284`  
> Previous instruction: `c585df44351b2adc260740602854aa0ce4559852`  
> New code commit reviewed: `b2d9875963c8ee6d274c18a79b47ed7b14d81284`  
> CODE Actions at review time: run `34540810119` was still **in_progress**; do not call it GREEN until both Ubuntu + Windows finish SUCCESS.  
> Current canonical acceptance is still OLD: generation `2936750f-8a3c-4bb5-90ab-70741ea6f21d`, `evidenceCodeCommit=ce2c46c0535fb2bbba2208401a51a66d4991ffaa`.  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪仍是 **correction-only**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore。

## 本輪已接受，禁止退步

`b2d9875` 有實質修正，以下接受：

1. **非正方形 uvRect quarter-turn**：`canonical_final_sampling()` 與 Blender worker 已改成 rect-local normalized/corner permutation，再 map 回原 uvRect；90/180/270/mirror 不再因 aspect ratio 擴張 source bounds。
2. **worker/artwork UV parity regression**：新增 `[0,1]×[.375,.625]` 與 `[0,.25]×[0,1]` 非正方形案例，並比對 artwork-side 與 worker-side final sampling。
3. **pixel landmark oracle（CONTAIN）**：新增 asymmetric RGB landmarks，會讀 production PNG 實際像素，不再只用 `finalUvHash` 自證；目前覆蓋 0/90/180/270/mirror/mirror90。
4. **MASTER identity**：`masterId` 已納入 relation integrity，且改為由 immutable relation identity deterministic derive；coordinated masterId + placement rehash tamper 會 BLOCK。
5. **validator fail-closed**：`cabinet4Single / containCenter / coverAnchor / orientationParity / masterSeam` 已由 optional `if scenario` 改為 required；orientation 缺 180/270/mirror 會 FAIL；negative matrix 也新增 `master_id_coordinated=BLOCKED`。
6. `realArtworkPreviewReady=false`、`physicalPrintValidated=false`、LIVE_CNC/LASER/PLC BLOCKED 的 truth boundary 沒有被亂升級。

以上不要回退。

---

# Blocker 1 — Round 5 明確要求 CONTAIN **與 COVER** pixel-oracle；目前只有 CONTAIN

目前 `measure_orientation_parity()` 仍硬編：

```python
fit=FIT_CONTAIN
anchor="CENTER"
```

而 canonical runner 的 `orientationParity` 也只從這條 CONTAIN path 生成。`coverAnchor` 目前只證明 LEFT/RIGHT 的 `sourceXPx` 不同，沒有證明 COVER 在 rotation/mirror 後，Blender finalSampling 與 production raster 還是同一 source region / orientation。

這不符合上一輪要求：

> CONTAIN 與 COVER 至少各做 0、90、180、270、mirror、mirror+90；COVER 還要驗 anchor 先 crop、再 orientation。

## Required correction

用最小改動把 pixel oracle 泛化，不要另造第二套 artwork engine：

- `measure_orientation_parity(..., fit, anchor)` 或等價參數化。
- CONTAIN：維持 CENTER + landmark/letterbox parity。
- COVER：至少對 **LEFT / CENTER / RIGHT**（若 crop axis 是水平）各驗：
  - 0
  - 90
  - 180
  - 270
  - mirror
  - mirror90
- 若該 source aspect 會走垂直 crop，改用 TOP/CENTER/BOTTOM，但 canonical evidence 要清楚記錄 crop axis。
- oracle 必須比較：
  1. authoritative source crop/anchor；
  2. Blender-side finalSampling / uvRect；
  3. production PNG observed landmark；
  4. status exact `PASS`/`BLOCK`。
- 明確固定 transform order：**anchor/crop first → mirror/quarter-turn orientation second**（或你現在實作的等價 canonical order）；worker 與 production 必須同一語義。
- 不可把 `finalUvHash == transformHash lineage` 當 pixel parity。

## Required canonical shape

建議改成：

```json
"orientationParity": {
  "CONTAIN": {
    "CENTER": {"0": {}, "90": {}, "180": {}, "270": {}, "mirror": {}, "mirror90": {}}
  },
  "COVER": {
    "LEFT":   {"0": {}, "90": {}, "180": {}, "270": {}, "mirror": {}, "mirror90": {}},
    "CENTER": {"0": {}, "90": {}, "180": {}, "270": {}, "mirror": {}, "mirror90": {}},
    "RIGHT":  {"0": {}, "90": {}, "180": {}, "270": {}, "mirror": {}, "mirror90": {}}
  }
}
```

不必拘泥 key 名稱，但 validator 必須把 declared required matrix **全部 fail-closed**；少一個 orientation 或 anchor 都要 FAIL。

---

# Blocker 2 — 新 CODE 尚未形成可審核 canonical evidence；docs 仍停在 Round 4

目前 main 雖已有 `b2d9875`，但：

- `docs/GROK_PROGRESS_REPORT.md` 仍寫 Round 4 / CODE `ce2c46c` / 601 passed。
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md` 仍以 CODE `ce2c46c` 為基線。
- `docs/REAL_E2E_ACCEPTANCE.md` 的 `surfaceDecorationLogicReady` 仍引用 CODE `ce2c46c` / generation `2936750f-...`。
- `docs/ARTWORK_PLACEMENT_ACCEPTANCE.json/.md` 仍是舊 generation，甚至 row 還是舊的 `rotation/finalUv parity`，沒有新的 `orientationParity` landmark matrix。
- `CABINET_REAL_ACCEPTANCE.md` 沒有 truth change，不需要硬改。

所以 `b2d9875` 現在只能算 **CODE CHANGE / un-gated**，不能算 Phase 781–840 completion，也不能放行 Phase 841+。

## Required evidence flow

完成 Blocker 1 後：

1. source + tests commit/push 成新的 exact **CODE_EVIDENCE_SHA**。
2. full `pytest -q` PASS，回報 exact count。
3. exact CODE SHA GitHub Actions **Ubuntu + Windows 都 SUCCESS**。CI 仍 `FOX3D_MOCK_BLENDER=1`，只能標 MOCK/unit/integration + FIXTURE/REAL_LOGIC。
4. 在 exact CODE SHA 的 **clean tree** 跑：
   - `scripts/run_artwork_placement_e2e.py --expected-commit <CODE_SHA>`
   - 不要 `--allow-dirty` 當正式 evidence。
5. 新 acceptance 必須：
   - `workingTreeClean=true`
   - `evidenceCodeCommit=<exact CODE_SHA>`
   - 新 `acceptanceGenerationId`
   - `ok=true`
   - CONTAIN + COVER orientation landmark matrix完整
   - masterId coordinated tamper = BLOCKED
   - required scenario deletion/missing evidence fail-closed
6. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.json`
7. `CABINET_REAL_ACCEPTANCE.md` 若無 cabinet engineering truth change就保持不動。
8. evidence/docs commit push 後，docs/head Actions Ubuntu + Windows SUCCESS。
9. Issue #1 留完成回報：CODE SHA、pytest count、CODE run、canonical generation、docs SHA/run、REAL/MOCK/PARTIAL/BLOCKED。
10. **STOP。等待 ChatGPT Re-Gate。不要自行進 Phase 841+。**

---

# Truth labels 必須維持

完成本輪後仍然只能依證據標示：

- Artwork geometry / placement / production raster parity：**REAL_LOGIC / FIXTURE evidence**（若 canonical pass）。
- GitHub Actions pytest：**MOCK/unit/integration**，因 `FOX3D_MOCK_BLENDER=1`。
- `realArtworkPreviewReady=false / MOCK`，除非這一輪真的跑新的 artwork path REAL Blender/OptiX evidence，而且 artifact SHA/size/device/loaded artwork SHA/placement lineage 全部綁 exact CODE；不要借用舊 portfolio render 升級。
- `physicalPrintValidated=false`，除非有實體印刷與尺寸量測 evidence。
- Demand / Vision / AI Video：**MOCK**。
- print preflight / OS sandbox / AR / barcode / McKee-BCT：**PARTIAL**。
- LIVE_CNC / LIVE_LASER / PLC / liveFactory：**BLOCKED**；`liveMachineControl=false`。
- `globalProductionReady=false`、`fullAutonomousFactoryReady=false`、`liveFactoryExecutionReady=false`。

## Definition of Done

Phase 781–840 這次只有在以下全部成立才可再次送 Re-Gate：

> rect-local 0/90/180/270/mirror 已通過非正方形 UV；CONTAIN 與 COVER（含 anchor crop）都用 asymmetric pixel landmark 證明 Blender sampling 與 production PNG 同 source region/orientation；masterId independent integrity fail-closed；required acceptance matrix缺任何 row 都 FAIL；exact CODE CI 綠；clean-tree canonical bundle綁 exact CODE；docs 全部更新且 truth labels 正確。
