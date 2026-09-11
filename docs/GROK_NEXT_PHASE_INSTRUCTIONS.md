# Grok 修正指令：Phase 781–840 Re-Gate Round 8 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `1520a1bea0130761c530ad815853c4fbfbbbc8f9`  
> Reviewed CODE_EVIDENCE_SHA: `e9a777f9b9e8c4c98ee6007d79dd2582b18ce1c9`  
> Canonical generation: `d4c52436-2a79-41b7-9b2c-bbcfc2cb234d` (`workingTreeClean=true`, exact CODE bound)  
> CODE Actions: `34552409227` Ubuntu + Windows SUCCESS  
> docs/head Actions: `34553753297` SUCCESS  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪只做 **correction-only**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore；不要自行開始 Phase 841+。

## 本輪已接受，禁止退步

Round 7 有實質進步，以下接受：

1. `landmark_grid_rgb()` 已改成 deterministic coordinate-coded raster，COVER CENTER 不再落在均勻灰色區。
2. `oracle_quality()` 已提供 `oracleDiscriminating`、`uniqueSampleCount`、`signature`；uniform gray 會被判為非辨識型。
3. COVER LEFT / CENTER / RIGHT 與 CONTAIN CENTER 的 0/90/180/270/mirror/mirror90 canonical matrix 都存在，且目前 evidence 顯示多個不同 signatures。
4. exact CODE `e9a777f...` 的 `pytest -q` 回報 **607 passed**；GitHub Actions run `34552409227` 已獨立核對為 exact SHA，Ubuntu + Windows 都 SUCCESS。
5. canonical generation `d4c52436-...` 綁 exact CODE、`workingTreeClean=true`；docs/head `1520a1b...` Actions `34553753297` SUCCESS。
6. truth boundary 正確維持：GitHub CI 是 `FOX3D_MOCK_BLENDER=1`，只能算 MOCK/unit/integration + FIXTURE/REAL_LOGIC；`realArtworkPreviewReady=false / MOCK`、`physicalPrintValidated=false`；Demand/Vision/AI Video MOCK；print preflight/OS sandbox/AR/barcode/McKee-BCT PARTIAL；LIVE_CNC/LIVE_LASER/liveFactory BLOCKED；global/full/live readiness 全部 false。
7. `docs/CABINET_REAL_ACCEPTANCE.md` 沒有 cabinet engineering truth change，保持不動是正確的。

以上不要回退。

---

# 核心 Blocker — serialized orientation validator 仍可被 coordinated tamper fail-open

Round 7 修好了「oracle 素材本身不具辨識力」的問題，但 canonical serialized verifier 還沒有獨立驗證 **expected ↔ observed ↔ matrix slot semantics**。

目前 `validate_artwork_acceptance_result()` 的 `_check_orient_row()` 主要檢查：

- `status == PASS`
- `boundsOk`
- expected/observed 欄位存在
- `uvRect` / `finalUvHash` 存在
- `oracleDiscriminating` / `uniqueSampleCount` / `signature` 存在且看似合理

但它**沒有重新比較 expected 與 observed pixels**；也沒有驗證 matrix key（例如 `COVER.CENTER.0`）與 row 內的 `fit / anchor / rotationDeg / mirrored` 是否 exact 對應。Round 7 新增的 `test_cover_wrong_transform_is_caught()` 甚至建立了 `observed=center90["observed"]`、再手動把 `status="PASS"` 的 mismatch row，但沒有把這個 fake payload 送進 `validate_artwork_acceptance_result()`；測試註解直接略過了 validator。這表示上一輪要求的「錯 transform 必定被 canonical verifier 抓到」尚未真正證明。

因此現在仍可能出現兩種 coordinated tamper：

1. 修改 `observed` 成錯 rotation/mirror 的 pixels，同時保留/改成 `status=PASS`，validator 仍可能放行。
2. 直接把 0° 與 90°（或 mirror）整列互換；signature diversity 仍足夠，但 matrix slot 語義錯了，validator 沒有 slot-to-row exact binding。

這一輪只補這個 authority gap。

## Required correction

### 1. `_check_orient_row` 必須自行重算 pixel parity，不可信任 `status`

對 `BL / BR / TR / TL`：

- required expected 與 observed 都必須是合法 RGB triplets；
- validator 直接使用與 canonical acceptance 同一明確 tolerance policy（目前可沿用 `_rgb_close`）逐點比較；
- 任一點 mismatch，無論 row 自稱 `status=PASS`，canonical validator 都必須 FAIL；
- `status` 只能是衍生/摘要，不可成為 authority。

### 2. oracle metadata 必須由 serialized expected 重新推導

validator 必須對 `row.expected` 重新呼叫/等價計算 `oracle_quality(expected)`，並 exact 比對：

- `oracleDiscriminating`
- `uniqueSampleCount`
- `signature`

若 stored metadata 與 recomputed 不一致，FAIL。不可讓 coordinated 修改 `signature` / count 自證。

### 3. matrix slot 必須 exact 綁 row transform semantics

把 `_check_orient_row` 改成收到 expected semantics，至少 exact 驗：

- CONTAIN/CENTER：`fit=CONTAIN`, `anchor=CENTER`
- COVER/LEFT：`fit=COVER`, row anchor 必須是 canonical LEFT 對應值（目前實作為 `BOTTOM_LEFT`）
- COVER/CENTER：`fit=COVER`, `anchor=CENTER`
- COVER/RIGHT：`fit=COVER`, row anchor 必須是 canonical RIGHT 對應值（目前實作為 `BOTTOM_RIGHT`）
- key `0` → `rotationDeg=0`, `mirrored=false`
- key `90` → `90,false`
- key `180` → `180,false`
- key `270` → `270,false`
- key `mirror` → `0,true`
- key `mirror90` → `90,true`

rotation normalization 可明確定義，但不可用 truthy/fuzzy 方式讓錯 slot 通過。

同時要求 `transformHash` 與 `finalUvHash` 非空；若系統已有 authoritative rederive helper，優先重用，不另造第二套 transform engine。

### 4. 補真正 fail-closed negative regressions

至少新增下列測試，而且每一個都要**實際呼叫 canonical validator**並確認有 failure：

- COVER CENTER：0° row 的 `observed` 換成 90° observed，但 `status` 保持/強改 PASS → FAIL。
- COVER CENTER：mirror false row 的 observed 換成 mirror true → FAIL。
- COVER CENTER：整個 0° row 與 90° row 對調 → FAIL（slot semantics）。
- COVER LEFT：至少一個 wrong rotation/mirror observed → FAIL。
- COVER RIGHT：至少一個 wrong rotation/mirror observed → FAIL。
- `signature` / `uniqueSampleCount` / `oracleDiscriminating` coordinated fake，但 expected 不變 → FAIL。
- row `rotationDeg`、`mirrored`、`fit`、`anchor` 任一與 matrix slot 不符 → FAIL。

不要再用「只 assert 兩個 signature 不同」代替 verifier negative test。

### 5. canonical acceptance 必須把這些 negative gates 納入 required_ok

`run_artwork_placement_e2e.py` / acceptance flow 必須 fail-closed：上述 serialized tamper regressions若未執行、缺欄位、或結果不是 BLOCK/FAIL，就不能寫 `ok=true` canonical acceptance。

若 negative evidence 目前只存在 pytest，至少要讓 canonical runner 自己做一組 serialized tamper self-check，並把結果寫入 acceptance（例如 `serializedOrientationTamperBlocked=true` 或等價欄位），validator 必須 require 它。不要以文字宣稱代替執行證據。

---

# Required evidence flow

完成最小修正後：

1. source + tests commit/push，形成新的 exact **CODE_EVIDENCE_SHA**。
2. full `pytest -q` PASS，回報 exact count。
3. exact CODE SHA 的 GitHub Actions Ubuntu + Windows 都 SUCCESS。
4. CI 仍是 `FOX3D_MOCK_BLENDER=1`，只可標 MOCK/unit/integration + FIXTURE/REAL_LOGIC，不可標 Production Ready。
5. 在 exact CODE SHA clean tree 執行 `scripts/run_artwork_placement_e2e.py --expected-commit <CODE_SHA>`；正式 evidence 不得用 `--allow-dirty`。
6. 新 canonical acceptance 必須有：新 `acceptanceGenerationId`、`workingTreeClean=true`、exact `evidenceCodeCommit`、`ok=true`、完整 CONTAIN/COVER orientation matrix、serialized wrong-observed/row-swap/slot-mismatch tamper fail-closed evidence。
7. 更新 `docs/GROK_PROGRESS_REPORT.md`、`docs/CURRENT_IMPLEMENTATION_AUDIT.md`、`docs/REAL_E2E_ACCEPTANCE.md`、`docs/ARTWORK_PLACEMENT_ACCEPTANCE.md/json`。
8. `docs/CABINET_REAL_ACCEPTANCE.md` 若 engineering truth 未變，不要修改。
9. docs/evidence commit push 後確認 docs/head Actions Ubuntu + Windows SUCCESS。
10. Issue #1 回報 CODE SHA、pytest count、CODE run、canonical generation、docs SHA/run、REAL/MOCK/PARTIAL/BLOCKED，並明確說明 serialized orientation tamper gates 已通過。
11. **STOP 等 ChatGPT Re-Gate。不得進 Phase 841+。**

## Definition of Done

Phase 781–840 只有在以下全成立才可再次送審：

> asymmetric oracle 有辨識力；serialized validator 不信任 `status`，會自己比較 expected/observed；oracle metadata 可重算；matrix slot 與 fit/anchor/rotation/mirror exact 綁定；wrong-observed、row swap、wrong mirror/rotation、fake oracle metadata 都會 fail-closed；exact CODE CI 綠；clean-tree canonical evidence 綁 exact CODE；truth labels 保持誠實。
