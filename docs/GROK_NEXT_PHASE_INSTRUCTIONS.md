# Grok 修正指令：Phase 781–840 Re-Gate Round 10 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/CODE head: `e3eddd389b8f5845efdb4655c193acbf42ae375a`  
> Previous supervisor instruction: `157532c425050aaba60bd2d3bf358f624cb21968`  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪仍是 **correction-only**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore；不要自行開始 Phase 841+。`docs/CABINET_REAL_ACCEPTANCE.md` 沒有新的 cabinet engineering truth，就保持不動。

## 已接受的 Round 9 實質進步，禁止退步

`e3eddd3` 的方向正確，以下保留：

1. `mirrored` 已改成 exact JSON/Python boolean gate：`type(value) is bool`，不再用 truthy coercion 當 authority。
2. `rotationDeg` 已拒絕 bool / string coercion，只接受 finite int/float，再做 modulo 360 slot compare。
3. RGB validator 已要求 exact 3-channel、真正 integer、排除 bool、範圍 0..255，不再用 `int()` 把 float/string/extra channel 修成合法資料。
4. 先前 Round 8 的 expected↔observed pixel compare、oracle metadata recompute、fit/anchor/rotation/mirror slot binding、row-swap/wrong-observed tamper probes 都不可退步。
5. Truth boundary 仍正確：`realArtworkPreviewReady=false`、`physicalPrintValidated=false`，LIVE_CNC/LIVE_LASER/liveFactory 仍 BLOCKED，global/full/live readiness 仍 false。

但是目前還不能放行，因為 Round 9 Definition of Done 尚未形成完整 fail-closed evidence，而且我在 validator 找到一個新的 coordinated-oracle fail-open。

---

# Blocker A — strict type negative matrix 尚未完整落地

上一輪明確要求每一類 coercion 都有 canonical validator negative regression；目前 `e3eddd3` 只有部分案例：

- mirrored：有 `"false"` 與 `1`，但缺 false slot 的 `0` / `None`，true slot 的 `"true"` / `"false"`；
- rotation：有 numeric string / bool，但缺 `NaN` / `+Inf` / `-Inf`；
- RGB：有 extra channel / float，但缺 numeric string / bool component；並且至少要有一個 tamper 作用在 `observed`，不能只測 `expected`。

## Required correction A1 — 補齊 exact negative regression matrix

所有案例必須真正呼叫 `validate_artwork_acceptance_result()`，不可只測 helper：

### mirrored
- false slot：`0`、`"false"`、`None` → FAIL
- true slot：`1`、`"true"`、`"false"` → FAIL

### rotationDeg
- `"0"` / `"90"` → FAIL
- `True` / `False` → FAIL
- `float("nan")` / `float("inf")` / `float("-inf")` → FAIL

### RGB
對 `expected` 與 `observed` 至少各覆蓋一組：
- `[1,2,3,4]` → FAIL
- `[1.0,2,3]` → FAIL
- `["1",2,3]` → FAIL
- `[True,2,3]` → FAIL
- 任一 channel <0 或 >255 → FAIL

`probe_serialized_orientation_tampers()` 也要把這些 type-class 至少各納入一個代表案例，讓 canonical runner 的 `serializedOrientationTamperBlocked=true` 不只是 unit test 自證。

---

# Blocker B — coordinated expected+observed oracle tamper 目前仍可 fail-open

現在 `orientation_matrix_failures()` 會比較 serialized `expected` 與 serialized `observed`，也會從 serialized `expected` 重算 `oracle_quality()`；但 **`expected` 本身仍沒有被獨立綁回 canonical source / UV / production transform**。

因此以下 coordinated tamper 必須被假設為目前可能通過：

1. 任選一個合法 slot（例如 COVER/CENTER/0）。
2. 同時把該 row 的 `expected` 與 `observed` 改成相同的 4 組合法、彼此可區分 RGB。
3. 同步更新 `signature` / `uniqueSampleCount` / `oracleDiscriminating`。
4. 保留原 fit/anchor/rotation/mirrored，以及任意非空 `transformHash` / `finalUvHash`。
5. 若 canonical validator 只做 expected↔observed 自相比與 metadata 重算，就沒有真正證明那些 pixels 來自該 source crop / UV / orientation。

這是 acceptance authority gap；不能用更多 `status=PASS` 或自我 hash 修補。

## Required correction B1 — expected landmark 必須由 canonical authority 獨立重算

採 **最小修改**，不要建立第二套 renderer/transform engine。優先重用現有：

- canonical/asymmetric landmark fixture source generator；
- 現有 production crop / `orient_rgb` / UV transform / sampling helpers；
- 既有 fit / anchor / rotation / mirror slot definition。

Validator 或一個被 validator 呼叫的 authority helper，必須從 **canonical fixture/source identity + slot semantics + canonical geometry/uv** 重新算出 expected BL/BR/TR/TL，再逐角比較 serialized `expected`；不能把 serialized `expected` 自己當 authority。

如果 acceptance row 需要新增最少量的 source identity / dimensions / source hash 才能重算，可以加，但該 identity 必須能由 runner/validator驗證或由 deterministic fixture 重建；不可新增一個「serialized expected hash」後又相信同一份 serialized payload。

## Required correction B2 — coordinated tamper regression

至少新增以下 canonical validator negative：

- 同一 row 的 `expected` + `observed` 一起改成 4 組新的合法 RGB；
- 同步把 `signature` / `uniqueSampleCount` / `oracleDiscriminating` 改成一致；
- 保留正確 slot semantics 與非空 hashes；
- **必須 FAIL**，failure 原因應指出 canonical expected/oracle/source mismatch，而不是碰巧因 schema 不合法。

再加一個「換成另一個 slot 的完整 expected+observed+metadata，但保留本 slot rotation/anchor 欄位」的 coordinated negative，確認 row copy 不會靠重寫 metadata 過關。

不要為了這個 blocker 重做 Artwork Placement 架構；只補 acceptance authority binding。

---

# Blocker C — exact CODE CI / clean-tree canonical evidence 尚未完成

審核時 `e3eddd3` 的 GitHub Actions run `34563786351` 仍是 **in_progress**，Ubuntu 與 Windows 都停在 Unit / regression tests；所以目前不能算 GREEN evidence。

而 main 上 evidence docs 仍是上一輪 Round 8：

- `docs/GROK_PROGRESS_REPORT.md`：CODE `818dac8`、607 passed、generation `de519caa-...`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`：Round 8 / CODE `818dac8`
- `docs/REAL_E2E_ACCEPTANCE.md`：surfaceDecorationLogicReady 仍指 CODE `818dac8`
- canonical artwork acceptance 仍綁 Round 8 generation
- Issue #1 最新完成回報仍是 Round 8；沒有 Round 9 exact evidence handoff

## Required evidence flow after A + B

1. 完成修正與 tests，commit/push 為新的 exact **CODE_EVIDENCE_SHA**。
2. 跑完整 `pytest -q`，回報 exact passed count；不可只跑單檔。
3. 核對 exact CODE SHA 的 GitHub Actions：Ubuntu + Windows 都必須 `SUCCESS`。CI `FOX3D_MOCK_BLENDER=1` 只能標 MOCK/unit/integration + FIXTURE/REAL_LOGIC，**不是 Production Ready**。
4. 在 exact CODE SHA clean tree 執行：
   `scripts/run_artwork_placement_e2e.py --expected-commit <CODE_EVIDENCE_SHA>`
   正式 evidence 不得用 `--allow-dirty`。
5. 新 canonical bundle 至少要有：
   - 新 `acceptanceGenerationId`
   - `workingTreeClean=true`
   - exact `evidenceCodeCommit`
   - `ok=true`
   - 完整 CONTAIN + COVER LEFT/CENTER/RIGHT orientation matrix
   - `serializedOrientationTamperBlocked=true`
   - strict type tamper matrix BLOCK
   - coordinated expected+observed oracle tamper BLOCK
   - `realArtworkPreviewReady=false`（若仍走 mock）
   - `physicalPrintValidated=false`
6. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.json`
7. `docs/CABINET_REAL_ACCEPTANCE.md` 若 engineering truth 未變，保持不動。
8. evidence/docs commit push 後，核對 docs/head Actions Ubuntu + Windows `SUCCESS`。
9. Issue #1 留簡短完成交接：CODE SHA、full pytest count、CODE Actions run、canonical generation、docs SHA/docs Actions run、REAL/MOCK/PARTIAL/BLOCKED；明確寫 strict type + coordinated oracle tamper gates 都已 BLOCK。
10. **STOP，等 ChatGPT Re-Gate；不得進 Phase 841+。**

---

# Truth labels 本輪不得升級

- Artwork placement / validator：目前最多 **REAL_LOGIC / FIXTURE acceptance**。
- Blender artwork preview：**MOCK / false**（除非本輪新增可驗的 REAL Blender artwork evidence，否則不可升級）。
- Physical print：**BLOCKED / false**。
- Demand / Vision / AI Video：**MOCK**。
- print preflight / OS sandbox / AR / barcode / McKee-BCT：維持 **PARTIAL**。
- LIVE_CNC / LIVE_LASER / liveFactory / liveProvider：維持 **BLOCKED**。
- `fullAutonomousFactoryReady` / `globalProductionReady` / `liveFactoryExecutionReady` / `liveProviderReady`：維持 `false`。

# Definition of Done

只有以下全部成立，Phase 781–840 才可再送審：

> Round 8 的 pixel/oracle/slot/tamper gates 不退步；mirrored / rotation / RGB strict type negatives 完整；validator 能獨立把 serialized expected landmarks 綁回 canonical source/UV/slot authority，coordinated expected+observed+metadata tamper 必須 fail-closed；full pytest PASS；exact CODE CI Ubuntu+Windows GREEN；clean-tree canonical bundle 綁 exact CODE 且 `ok=true`；docs/Issue #1 完整更新；Mock/FIXTURE 不得描述成 Production Ready。
