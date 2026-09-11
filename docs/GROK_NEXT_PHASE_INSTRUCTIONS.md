# Grok 修正指令：Phase 781–840 Re-Gate Round 12 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `25ebadf14de72e8a64b61a30385c2f10908e1326`  
> Reviewed CODE evidence: `4977bedcaa54bb16df20b4b58e4bd6137a079eba`  
> Previous supervisor instruction: `22ed5212b4a0e864ae994011527bf01f67381bdc`  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪仍是 **correction-only**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore；不要自行開始 Phase 841+。`docs/CABINET_REAL_ACCEPTANCE.md` 若 cabinet engineering truth 沒變，保持不動。

## Round 11 已確認通過

1. CODE `4977bed` 已完成 serialized expected ↔ deterministic canonical expected **exact 3-int equality**，不再使用 ±48 tolerance。
2. near-tolerance coordinated RGB tamper 已有直接走 `validate_artwork_acceptance_result()` 的 negative，`+1/+8` 均 fail closed 在 canonical authority，而不是 RGB type。
3. canonical surface / panelIndex 已綁 deterministic 2400×1800 / 4-door fixture；payload 只作 evidence。
4. coordinated geometry tamper 已 fail closed；panelIndex `"2"` / `True` / `-1` / `999` / missing、surface width/height tamper 皆有 full-validator negative。
5. tamper flags 已拆成獨立 probes：`serializedOrientationTamperBlocked`、`strictTypeTamperBlocked`、`coordinatedOracleTamperBlocked`、`canonicalGeometryTamperBlocked`、`nearToleranceOracleTamperBlocked`。
6. full `pytest -q` 回報 **607 passed**。
7. exact CODE Actions `34584414875`：Ubuntu + Windows **SUCCESS**。
8. canonical generation `edd1142d-511d-4069-b794-1e6c35cf1002`：runner-bound `evidenceCodeCommit=4977bed...`、`workingTreeClean=true`。
9. docs/head `25ebadf` Actions `34586213912`：Ubuntu + Windows **SUCCESS**。
10. Truth labels 正確維持：Artwork validator **REAL_LOGIC / FIXTURE**；Blender artwork preview **MOCK / false**；physical print **BLOCKED / false**；Demand/Vision/AI Video **MOCK**；LIVE_CNC/LIVE_LASER/liveFactory **BLOCKED**；global/full/live readiness 維持 `false`。

以上代表 Round 11 的原定 blockers 已實質修正。但 Re-Gate 再檢查 canonical fixture geometry parser 時，仍發現一個新的 fail-open schema authority gap，因此 Phase 841+ 暫不放行。

---

# Blocker A — `_canonical_fixture_crops_bound()` 對 missing / NaN / coercion 仍非 fail-closed

目前 `_canonical_fixture_crops_bound()` 類似：

```python
abs(float(crop.get("xMm") or 0) - x_mm) > MM_EPS
abs(float(crop.get("yMm") or 0) - y_mm) > MM_EPS
abs(float(crop.get("widthMm") or 0) - width_mm) > MM_EPS
abs(float(crop.get("heightMm") or 0) - height_mm) > MM_EPS
```

以及 `cabinet4.widthMm` 只有「若存在才驗證」。

這會造成幾個 canonical geometry evidence fail-open：

- `xMm` / `yMm` 缺欄位時可被 `or 0` 默認成 0；對本來 canonical 值就是 0 的欄位，缺失資料可能被接受。
- `float("NaN")` 或 `float("nan")` 會得到 NaN；Python 中 `abs(NaN - expected) > MM_EPS` 為 False，因此 NaN 可能繞過 mismatch 判定。
- numeric string 例如 `"600"`、`"1800"` 可被 `float()` coercion 後接受，serialized schema 不再是 strict typed evidence。
- `cabinet4.widthMm` 若缺失，目前不會直接 FAIL。
- `canonicalSurfaces.*.widthMm/heightMm` 雖有 finite guard，但仍允許 numeric string 經 `float()` coercion；Round 12 請一併收斂 strict schema。

這不代表現有 deterministic fixture 計算錯，而是 **serialized canonical geometry evidence 的 schema 還能被缺欄位、NaN 或型別 coercion 放行**。

## Required correction A1 — 新增 strict finite millimetre parser（最小修改）

請在 artwork acceptance/validator 內新增小型 helper，不要建立第二套 Cabinet geometry engine，也不要改寫 CabinetSpec。

對 canonical geometry evidence 的 mm 欄位統一要求：

- key 必須存在；不得用 `or 0`、不得 missing fallback。
- type 必須是 exact `int` / `float`；**bool 禁止、string 禁止**。
- 必須 `math.isfinite(float(value))`。
- 再以 `MM_EPS` 對 deterministic expected geometry 比較。

例如概念：

```python
def _strict_finite_mm(mapping, key):
    if key not in mapping:
        return None
    v = mapping[key]
    if type(v) is bool or not isinstance(v, (int, float)):
        return None
    fv = float(v)
    if not math.isfinite(fv):
        return None
    return fv
```

名稱可自行調整，但語意必須 fail closed。

## Required correction A2 — `_canonical_fixture_crops_bound()` 全面 strict

至少必須：

1. `cabinet4.widthMm` **必須存在**，strict finite numeric，且與 `2400.0` 在 `MM_EPS` 內一致。
2. `panelCrops` 必須是 list 且 **exact length 4**。
3. 每一個 crop 必須是 dict，並明確包含：
   - `xMm`
   - `yMm`
   - `widthMm`
   - `heightMm`
4. 四欄都必須 strict finite numeric：不接受 bool / string / NaN / ±Inf / missing。
5. 每個 crop 必須與 `canonical_cabinet4_panel_mm(i)` deterministic 結果一致。
6. 不得把 payload 本身當 geometry authority；deterministic fixture remains authority。

## Required correction A3 — `canonicalSurfaces` width/height 同步 strict type

目前 `_canonical_surface_mm()` 對 `widthMm/heightMm` 會 `float(raw)`；請收斂成：

- key required
- exact int/float
- bool/string 拒絕
- finite required
- compare deterministic fixture dimensions
- `panelIndex` 維持 exact `int` + exact expected index

不要因為數字字串可轉 float 就接受。

---

# Blocker B — 新增 canonical fixture geometry strict negative matrix

所有下列 negative 都必須 **直接呼叫 `validate_artwork_acceptance_result()`**，不能只測 helper：

## B1. Missing field

至少包含：

- `cabinet4.widthMm` missing → FAIL
- crop 0 `xMm` missing → FAIL（特別重要：canonical x 本來為 0，不能被 default 0 放行）
- 任一 crop `yMm` missing → FAIL（canonical y 本來為 0）
- `widthMm` missing → FAIL
- `heightMm` missing → FAIL

## B2. Non-finite

對 canonical fixture geometry 至少測：

- `float("nan")`
- `float("inf")`
- `float("-inf")`

需涵蓋 `cabinet4.widthMm` 與至少一個 crop field。

## B3. Coercible wrong types

至少測：

- numeric string `"0"`
- numeric string `"600"`
- numeric string `"1800"`
- `True` / `False`

需涵蓋 crop geometry 與 `canonicalSurfaces.COVER.widthMm/heightMm`。

## B4. Coordinated authority tamper

建立一個資料看起來完全自洽的 coordinated tamper：

- geometry evidence 使用非法 schema 值（例如 string / NaN / missing-zero field）
- expected / observed / signature / uniqueSampleCount / oracleDiscriminating 仍保持可自洽或重新計算
- validator 必須 FAIL 在 `canonical_geometry` / canonical authority 類 failure
- 不得只是因 `_rgb` type 錯而 FAIL

目的：證明即使攻擊者協調修改 oracle metadata，也不能用 schema coercion 繞過 geometry authority。

---

# Blocker C — Canonical geometry schema evidence 要能獨立證明

目前 `canonicalGeometryTamperBlocked=true` 已證明 Round 11 的 index/dimension coordinated tamper；Round 12 要再證明 strict finite schema 本身。

請採下列其中一種，但推薦第一種：

### 推薦：新增獨立 flag

- `finiteCanonicalGeometryTamperBlocked`

由專屬 probe 計算，涵蓋 missing / NaN / ±Inf / string / bool matrix。

runner / acceptance JSON/MD / progress report 都要發布此 flag，`ok` 必須要求它為 true。

### 若不新增 flag

可以擴充 `canonicalGeometryTamperBlocked`，但 canonical evidence 必須額外發布 per-case matrix/results，能清楚證明每一類 strict schema negative 都真的被執行，不能只剩一個 aggregate boolean。

---

# Evidence flow — Round 12 修正後全部重產

1. commit/push 新 code，作為新的 exact `CODE_EVIDENCE_SHA`。
2. 跑完整 `pytest -q`，回報 exact passed count；不可只跑 `test_artwork.py`。
3. exact CODE SHA 的 GitHub Actions Ubuntu + Windows 都必須 `SUCCESS`。
4. clean tree 執行：
   `scripts/run_artwork_placement_e2e.py --expected-commit <CODE_EVIDENCE_SHA>`
   正式 evidence 禁止 `--allow-dirty`。
5. 新 canonical bundle 至少包含：
   - 新 `acceptanceGenerationId`
   - `workingTreeClean=true`
   - exact `evidenceCodeCommit`
   - `ok=true`
   - Round 8–11 原有 tamper flags 全維持 true
   - strict finite canonical geometry schema gate true
   - missing/NaN/Inf/string/bool geometry negative evidence
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
10. Issue #1 留完成交接：CODE SHA、full pytest count、CODE Actions run、canonical generation、docs SHA/docs Actions run、strict geometry matrix/flag、REAL/MOCK/PARTIAL/BLOCKED。
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

> Round 11 已通過的 exact canonical expected、orientation/type/oracle/geometry/near-tolerance gates 不退步；canonical fixture 的 `cabinet4.widthMm` 與每個 crop `xMm/yMm/widthMm/heightMm` 全部 required + strict finite numeric，禁止 missing fallback / bool / string / NaN / ±Inf；`canonicalSurfaces` geometry 同樣 strict typed；full-validator negative matrix 全 PASS；strict geometry evidence 可獨立證明；full pytest PASS；exact CODE CI Ubuntu+Windows GREEN；clean-tree canonical bundle 綁 exact CODE 且 `ok=true`；docs/Issue #1 全部更新；Mock/FIXTURE 不得描述成 Production Ready。
