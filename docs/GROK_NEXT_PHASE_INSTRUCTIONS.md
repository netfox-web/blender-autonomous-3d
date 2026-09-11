# Grok 修正指令：Phase 781–840 Re-Gate Round 9 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed Grok CODE head: `818dac8a45b62a2e6dd5d5ad2909888e2e04b0a0`  
> Parent supervisor instruction: `39990d5ab9677958bbe99d24d720b2aea7cb4586`  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪仍是 **correction-only**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore；不要自行開始 Phase 841+。

## Round 8 已接受的實質進步，禁止退步

`818dac8` 已正面修掉上一輪大部分 authority gap：

1. `orientation_matrix_failures()` 已由 validator 自己逐角比較 serialized `expected` ↔ `observed`，不再只相信 row `status=PASS`。
2. validator 已從 serialized `expected` 重算 `oracle_quality()`，並比對 `oracleDiscriminating`、`uniqueSampleCount`、`signature`。
3. matrix slot 已開始綁定 `fit / anchor / rotationDeg / mirrored`；CONTAIN/CENTER 與 COVER/LEFT/CENTER/RIGHT 都走 canonical orientation matrix。
4. `transformHash` / `finalUvHash` 已要求非空。
5. 測試已把 wrong observed、wrong mirror、row swap、LEFT/RIGHT wrong transform、fake oracle metadata、wrong rotation/fit/anchor 真正送入 canonical validator。
6. `probe_serialized_orientation_tampers()` 已接入 `run_artwork_scenario()`；runner 把 `serializedOrientationTamperBlocked` 放進 required acceptance path，`body.ok` 仍由 validator + `result.ok` fail-closed 決定。
7. `realArtworkPreviewReady=false` / MOCK、`physicalPrintValidated=false`、LIVE_CNC/LIVE_LASER/liveFactory BLOCKED、global/full/live readiness false 的 truth boundary 沒被偷偷升級。
8. `docs/CABINET_REAL_ACCEPTANCE.md` 無 cabinet engineering truth change，保持不動是正確的。

以上都保留，這一輪不要重做架構。

---

# Blocker A — serialized scalar type 仍有 truthy/coercion fail-open

上一輪要求的是 **exact matrix slot semantics**，不能用 truthy / fuzzy coercion 自證。但 `818dac8` 仍有幾個 serialized-type fail-open：

- `bool(row.get("mirrored"))` 會把任意非空字串視為 `True`；例如字串 `"false"` 在 mirror slot 仍可能被當成 true，`0 / 1 / "true" / "false" / None` 也沒有被要求為真正 JSON boolean。
- `float(row.get("rotationDeg"))` 會接受字串 `"0"` / `"90"`；`bool` 在 Python 又是 `int` 子類，若沒有明確 type guard，serialized schema 可以被 coercion 放行。
- `_valid_rgb()` 目前只要求 `len(value) >= 3` 並 `int(...)` coercion，因此 `[1,2,3,4]`、`[1.9,2,3]`、`["1",2,3]`、boolean component 等都可能被當成合法 RGB。上一輪要求的是合法 **RGB triplet**，不能靠 loss-y `int()` 轉型。

這不是要重寫 renderer，只要把 canonical verifier 的 serialized contract 鎖死。

## Required correction A1 — `mirrored` 必須是 exact boolean

在 orientation validator 裡：

- `type(row.get("mirrored")) is bool` 才算合法；
- 再 exact 比對 expected slot boolean；
- 不可用 `bool(value)` 做 authority 判斷。

至少加入 canonical validator negative tests：

- false slot 分別塞 `0`、`"false"`、`None` → FAIL；
- true slot 塞 `1`、`"true"`、`"false"` → FAIL。

## Required correction A2 — `rotationDeg` 只接受 finite numeric，不接受 bool / string coercion

可以保留 modulo 360 normalization，但先明確驗 schema：

- 只接受 `int` / `float`，且 `bool` 明確拒絕；
- 必須 finite，NaN / +Inf / -Inf FAIL；
- 字串 `"0"` / `"90"` FAIL；
- 通過 type guard 後再 `% 360.0` 與 slot expected 比對。

補 validator negative tests：string numeric、bool、NaN/Inf 都必須 fail-closed。

## Required correction A3 — RGB 必須是 exact 3-channel integer triplet

`expected` 與 `observed` 每個 BL/BR/TR/TL：

- container 必須是 list/tuple；
- `len == 3`，不可 `>=3`；
- 每 channel 必須是真正 integer，`bool` 不可接受；
- 範圍 0..255；
- 不接受 float truncation、numeric string、額外 alpha/channel。

`oracle_quality(expected)` 不得在 schema invalid 時靠 `int()` 修好資料。可採最小改法：先 strict validate 四角，再進 `oracle_quality()`；或讓 helper 本身 strict。不要建立第二套 transform engine。

補 canonical validator negatives：extra channel、float component、numeric string、bool component → FAIL。

---

# Blocker B — Round 8 尚未形成可接受的 exact evidence bundle

檢查時 `818dac8` 的 GitHub Actions run `34559982387` 尚在執行中，因此 **不能算 GREEN evidence**。同時 main 上的 canonical docs 仍是 Round 7：

- `docs/GROK_PROGRESS_REPORT.md` 仍回報 CODE `e9a777f` / 607 passed；
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md` 仍是 Round 7 / `e9a777f`；
- `docs/REAL_E2E_ACCEPTANCE.md` 的 artwork entry 仍指 `e9a777f` + generation `d4c52436-...`；
- `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md/json` 仍是 Round 7 generation；
- Issue #1 尚無 `818dac8` Round 8 completion handoff。

所以即使 code direction 大致正確，現在也不能放行 Phase 841+。

## Required evidence flow after A1–A3

1. 完成 A1–A3 + tests，commit/push 成新的 exact **CODE_EVIDENCE_SHA**。
2. 跑完整 `pytest -q`，回報 exact passed count；不可只跑單檔。
3. 核對 exact CODE SHA 的 GitHub Actions：Ubuntu + Windows 都必須 `SUCCESS`。CI 仍是 `FOX3D_MOCK_BLENDER=1`，只能標 MOCK/unit/integration + FIXTURE/REAL_LOGIC，**不是 Production Ready**。
4. 在 exact CODE SHA 的 clean tree 執行：
   `scripts/run_artwork_placement_e2e.py --expected-commit <CODE_EVIDENCE_SHA>`
   正式 evidence 不得用 `--allow-dirty`。
5. 新 canonical acceptance 必須至少證明：
   - 新 `acceptanceGenerationId`
   - `workingTreeClean=true`
   - exact `evidenceCodeCommit`
   - `ok=true`
   - 完整 CONTAIN/COVER orientation matrix
   - `serializedOrientationTamperBlocked=true`
   - strict serialized type negatives 皆 BLOCK/FAIL
   - `realArtworkPreviewReady=false` 若仍是 mock
   - `physicalPrintValidated=false`
6. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.json`
7. `docs/CABINET_REAL_ACCEPTANCE.md` 若 engineering truth 未變，**不要修改**。
8. docs/evidence commit push 後，核對 docs/head Actions Ubuntu + Windows `SUCCESS`。
9. Issue #1 留簡短完成交接：CODE SHA、pytest count、CODE Actions run、canonical generation、docs SHA / docs Actions run、REAL/MOCK/PARTIAL/BLOCKED；明確說明 strict serialized boolean/numeric/RGB tamper gates 已通過。
10. **STOP，等 ChatGPT Re-Gate；不得進 Phase 841+。**

## Truth labels 本輪不得升級

- Artwork placement / validator：最多 **REAL_LOGIC / FIXTURE acceptance**，直到有對應真實輸出證據再另審。
- Blender artwork preview：目前 **MOCK / false**。
- Physical print：**BLOCKED / false**。
- Demand / Vision / AI Video：**MOCK**。
- print preflight / OS sandbox / AR / barcode / McKee-BCT：維持 **PARTIAL**。
- LIVE_CNC / LIVE_LASER / liveFactory / liveProvider：維持 **BLOCKED**。
- `fullAutonomousFactoryReady` / `globalProductionReady` / `liveFactoryExecutionReady` / `liveProviderReady`：維持 `false`。

## Definition of Done

只有在以下全部成立後，Phase 781–840 才可再次送審：

> Round 8 的 expected↔observed / oracle-metadata / matrix-slot / tamper self-check 不退步；mirrored 是 exact bool；rotation 是 finite numeric 且拒絕 bool/string coercion；RGB 是 exact 3×integer channels 且拒絕 coercion/extra channel；所有 negative tests 真正呼叫 canonical validator；full pytest PASS；exact CODE CI Ubuntu+Windows GREEN；clean-tree canonical evidence 綁 exact CODE 且 `ok=true`；docs 與 Issue #1 回報全部更新；Mock/FIXTURE 沒有被描述成 Production Ready。
