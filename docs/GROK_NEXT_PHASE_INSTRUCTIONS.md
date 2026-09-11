# Grok 修正指令：Phase 781–840 Re-Gate Round 11 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `321820f074c88b6b1686a4b97f7857464ba001f7`  
> Reviewed CODE evidence: `f002c55a4645edb27b8cc3ba8cb7fbeb93f98253`  
> Previous supervisor instruction: `f961e950fdbe799abd59971e1fe11d26210c3eef`  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪仍是 **correction-only**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore；不要自行開始 Phase 841+。`docs/CABINET_REAL_ACCEPTANCE.md` 沒有新的 cabinet engineering truth 就保持不動。

## 已確認通過的 Round 10 內容

1. CODE `f002c55` 已新增 canonical landmark source、canonical expected 重算、strict serialized type guards 與 coordinated oracle negative probes。
2. full `pytest -q` 回報 **607 passed**。
3. exact CODE Actions run `34569201347` 已完成，Ubuntu + Windows **SUCCESS**。
4. canonical generation `ff5ec0b8-26bc-4ce8-9036-c76538a6b90d`：`workingTreeClean=true`、`evidenceCodeCommit=f002c55...`、`ok=true`。
5. docs/head `321820f` Actions run `34570727491` 已完成，Ubuntu + Windows **SUCCESS**。
6. Truth labels 正確：Artwork validator 仍是 **REAL_LOGIC / FIXTURE**；Blender artwork preview **MOCK / false**；physical print **BLOCKED / false**；Demand/Vision/AI Video **MOCK**；LIVE_CNC/LIVE_LASER/liveFactory **BLOCKED**；global/full/live readiness 維持 `false`。
7. `docs/CABINET_REAL_ACCEPTANCE.md` 未被不必要修改。

以上證明 Round 10 有實質進展，但仍有兩個 fail-open authority 問題，故本輪不能 GO Phase 841+。

---

# Blocker A — canonical expected 使用 ±48 容差，近距離 coordinated tamper 仍可通過

目前 `orientation_matrix_failures()` 對 serialized `expected` 與 deterministic `canonical_orientation_expected()` 的比較使用 `_rgb_close(..., tol=48)`。

這不符合「serialized expected 不是 authority」的目標：canonical expected 與 serialized expected 都是 deterministic integer RGB，不存在真實渲染取樣誤差；因此攻擊者可以把 `expected` + `observed` 同步小幅改動（例如每 channel +1 / +8 / +16，仍在 0..255），同步重算 `signature / uniqueSampleCount / oracleDiscriminating`，在 ±48 容差內仍可能被接受。

## Required correction A1 — canonical expected 必須 exact

- `serialized expected` ↔ `canonical_orientation_expected()`：**exact 3-int equality**，不得使用 tolerance。
- `serialized observed` ↔ canonical/expected：若真有 raster/sampling 差異，可以保留明確、最小、可解釋的 tolerance，但不能讓 serialized expected 本身有容差。
- 不要用新增 hash 取代 exact compare；payload 自帶 hash 不是 authority。

## Required correction A2 — 新增 near-tolerance coordinated tamper

至少新增一個真正呼叫 `validate_artwork_acceptance_result()` 的 negative：

1. 取一個 COVER/CENTER row。
2. 對四角 `expected` 與 `observed` 同步改成合法 RGB，例如每個 channel 在不溢位前提下 `+1` 或 `+8`。
3. 同步重算 `signature / uniqueSampleCount / oracleDiscriminating`，保留 fit/anchor/rotation/mirror 合法。
4. 必須 FAIL，failure 必須落在 `canonical_expected`（或等價 canonical authority mismatch），不能因 RGB type 非法才失敗。

此 negative 必須同時進 unit test 與 canonical runner evidence。

---

# Blocker B — `_canonical_surface_mm()` 仍信任 serialized `canonicalSurfaces`，panelIndex 非法時會跳過 geometry binding

目前流程：

- `widthMm / heightMm` 直接讀 `orientationParity.canonicalSurfaces[fit]`；
- `panelIndex` 也讀 serialized payload；
- 只有 `panelIndex` 是合法 `int` 且落在 `cabinet4.panelCrops` 範圍時，才比較 surface width/height；
- 若 `panelIndex` 被改成字串、out-of-range 或其他非法值，函式仍會回傳 serialized width/height，而不是 fail closed。

因此攻擊者可改 `panelIndex + widthMm + heightMm`，再依新的 attacker-controlled geometry 重算全部 expected/observed/metadata，canonical expected 仍可能被帶著走。

## Required correction B1 — canonical surface authority 必須 fail closed

採最小修改，不建立第二套 geometry engine：

- CONTAIN 與 COVER 的 canonical panel index 必須由 code/fixture definition 決定，不由 payload 決定。
- serialized `panelIndex` 若保留，只能作 evidence，必須 **exact int + exact expected index**；字串 `"2"`、bool、None、負數、out-of-range 全 FAIL。
- `cabinet4.panelCrops` 缺失、型別錯、index row 缺失時，直接 FAIL，不得 fallback 回 serialized width/height。
- canonical surface width/height 必須從獨立 fixture geometry authority 取得或重算，再 exact/epsilon 對 payload 做驗證；不要把 payload 本身當 geometry authority。
- 若用 `cabinet4.panelCrops` 當中介，必須再把 crop geometry 綁回 deterministic cabinet4 fixture（2400×1800、4 doors / canonical fixture spec），避免 coordinated tamper `panelCrops + canonicalSurfaces` 一起自洽後通過。

## Required correction B2 — geometry authority negative matrix

至少新增：

- `panelIndex="2"` → FAIL
- `panelIndex=True` → FAIL
- `panelIndex=-1` → FAIL
- `panelIndex=999` → FAIL
- 缺 `panelIndex` → FAIL（若 schema 要求存在）
- 改 `canonicalSurfaces.COVER.widthMm/heightMm`，其餘不改 → FAIL
- **coordinated geometry tamper**：改 `panelIndex + widthMm/heightMm + expected + observed + signature/unique/discriminating` 成另一組完全自洽資料 → 必須 FAIL 在 geometry/canonical authority，而不是靠其他偶然錯誤。

這些都要直接走 `validate_artwork_acceptance_result()`。

---

# Blocker C — 三個 tamper evidence flags 目前共用同一個 boolean，不足以證明三種 gate 各自成立

目前 `run_artwork_scenario()` 是：

```python
tamper_blocked = probe_serialized_orientation_tampers(result)
result["serializedOrientationTamperBlocked"] = tamper_blocked
result["strictTypeTamperBlocked"] = tamper_blocked
result["coordinatedOracleTamperBlocked"] = tamper_blocked
```

這會讓三個不同 claims 只由一個 aggregate boolean 代表，evidence 粒度不足。

## Required correction C1 — 分離 gate

最小修改即可，至少拆成獨立可驗證結果：

- `serializedOrientationTamperBlocked`
- `strictTypeTamperBlocked`
- `coordinatedOracleTamperBlocked`
- 建議新增 `canonicalGeometryTamperBlocked`
- 建議新增 `nearToleranceOracleTamperBlocked`

每個 flag 必須由其對應 probe 自己計算；最後 `ok` 再要求全部 true。可以共用 helper，但不能只是把同一 aggregate boolean 複製到多個欄位。

---

# Evidence flow — Round 11 修正後全部重產

1. commit/push 新 code，作為新的 exact `CODE_EVIDENCE_SHA`。
2. 跑完整 `pytest -q`，回報 exact passed count；不可只跑單檔。
3. exact CODE SHA 的 GitHub Actions Ubuntu + Windows 都必須 `SUCCESS`。CI 仍是 MOCK/unit/integration + FIXTURE/REAL_LOGIC evidence，**不是 Production Ready**。
4. clean tree 執行：
   `scripts/run_artwork_placement_e2e.py --expected-commit <CODE_EVIDENCE_SHA>`
   正式 evidence 禁止 `--allow-dirty`。
5. 新 canonical bundle 至少包含：
   - 新 `acceptanceGenerationId`
   - `workingTreeClean=true`
   - exact `evidenceCodeCommit`
   - `ok=true`
   - serialized expected ↔ canonical expected exact compare gate
   - near-tolerance coordinated oracle tamper BLOCK
   - canonical geometry/panelIndex coordinated tamper BLOCK
   - strict type matrix BLOCK
   - cross-slot copy tamper BLOCK
   - `realArtworkPreviewReady=false`（若仍 mock）
   - `physicalPrintValidated=false`
6. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.json`
7. `docs/GROK_PROGRESS_REPORT.md` Source 旨令必須指向本次 supervisor instruction commit。
8. `docs/CABINET_REAL_ACCEPTANCE.md` 若 cabinet engineering truth 未變，保持不動。
9. evidence/docs commit push 後，核對 docs/head Actions Ubuntu + Windows `SUCCESS`。
10. Issue #1 留完成交接：CODE SHA、full pytest count、CODE Actions run、canonical generation、docs SHA/docs Actions run、各 tamper gate 狀態、REAL/MOCK/PARTIAL/BLOCKED。
11. **STOP，等待 ChatGPT Re-Gate；不得進 Phase 841+。**

# Truth labels 不得升級

- Artwork placement / validator：最多 **REAL_LOGIC / FIXTURE acceptance**。
- Blender artwork preview：**MOCK / false**，除非新增可驗 REAL Blender artwork evidence。
- Physical print：**BLOCKED / false**。
- Demand / Vision / AI Video：**MOCK**。
- print preflight / OS sandbox / AR / barcode / McKee-BCT：**PARTIAL**。
- LIVE_CNC / LIVE_LASER / liveFactory / liveProvider：**BLOCKED**。
- `fullAutonomousFactoryReady` / `globalProductionReady` / `liveFactoryExecutionReady` / `liveProviderReady`：全部維持 `false`。

# Definition of Done

只有以下全部成立才可再送 Re-Gate：

> serialized expected 對 deterministic canonical expected 為 exact equality；near-tolerance coordinated tamper fail-closed；canonical surface/panelIndex 不再由 serialized payload 自我授權；coordinated geometry tamper fail-closed；各 tamper evidence flags 獨立計算；Round 8–10 已通過的 pixel/oracle/slot/type guards 不退步；full pytest PASS；exact CODE CI Ubuntu+Windows GREEN；clean-tree canonical bundle 綁 exact CODE 且 `ok=true`；docs/Issue #1 全部更新；Mock/FIXTURE 不得描述成 Production Ready。
