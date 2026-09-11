# Grok 修正指令：Phase 781–840 Re-Gate Round 10 Refresh — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `8541089645c93e01e1b51fb42962d6719d40aa7e`  
> Reviewed CODE evidence: `e3eddd389b8f5845efdb4655c193acbf42ae375a`  
> Previous supervisor instruction: `52e72218d95be310633246f0bb066da2339df122`  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪仍是 **correction-only**。不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore；不要自行開始 Phase 841+。`docs/CABINET_REAL_ACCEPTANCE.md` 沒有新的 cabinet engineering truth，就保持不動。

## 本次 Re-Gate 新觀察

main 自上一輪 supervisor instruction `52e7221` 後只有 1 個新 commit：`8541089`，而且是 **docs/evidence-only**。它把 Round 9 canonical evidence 重新綁到 `e3eddd3` / generation `fcfca28e-0e40-4b94-8b0b-7a04841015b8`，沒有新增 Round 10 code correction。

已確認：

1. `e3eddd3` GitHub Actions run `34563786351` 已完成，Ubuntu + Windows **SUCCESS**。
2. docs/head `8541089` GitHub Actions run `34565087971` 已完成，Ubuntu + Windows **SUCCESS**。
3. `docs/GROK_PROGRESS_REPORT.md`、`docs/CURRENT_IMPLEMENTATION_AUDIT.md`、`docs/REAL_E2E_ACCEPTANCE.md` 與 artwork canonical evidence 現在已指向 `e3eddd3` / `fcfca28e-...`。
4. Truth labels 沒有被錯誤升級：`realArtworkPreviewReady=false / MOCK`、`physicalPrintValidated=false`；LIVE_CNC/LIVE_LASER/live factory 仍 BLOCKED；global/full/live readiness 仍 false。
5. `docs/CABINET_REAL_ACCEPTANCE.md` 未被不必要修改，維持既有 cabinet engineering truth。

以上代表上一輪「CI 尚在跑 / docs 還停 Round 8」的 evidence timing blocker 已解除；**但 Round 10 的兩個核心 integrity blockers 完全尚未完成**。此外，目前 `docs/GROK_PROGRESS_REPORT.md` 仍寫 Source 旨令 `157532c`、Round 9 correction-only，沒有宣告已執行 `52e7221` Round 10；因此 `8541089` 不可當成 Round 10 完成回報。

---

# Blocker A — strict type negative matrix 仍未完整落地

`e3eddd3` 已接受並必須保留：

- `mirrored` exact bool，不得 truthy coercion；
- `rotationDeg` finite numeric、拒絕 bool/string；
- RGB exact 3-channel integer、拒絕 bool/float/string/extra channel、range 0..255；
- Round 8 expected↔observed、oracle metadata、slot binding、row-swap/wrong-observed guards。

但是上一輪要求的完整 negative matrix 尚未由新 CODE commit 補上。

## Required correction A1 — 完整 validator negative regression matrix

所有案例都必須真正呼叫 `validate_artwork_acceptance_result()`，不可只測 helper。

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
- 任一 channel < 0 或 > 255 → FAIL

`probe_serialized_orientation_tampers()` 也至少要把每個 type-class 納入一個代表 tamper，讓 canonical runner 的 tamper gate 不是只有 unit test 自證。

---

# Blocker B — serialized expected authority 仍未獨立綁回 canonical source/UV/slot

目前 `orientation_matrix_failures()` 會比較 serialized `expected` vs serialized `observed`，也會用 serialized `expected` 重算 oracle metadata；但 **serialized `expected` 本身仍不是獨立 authority**。

若攻擊者同時修改：

- `expected`
- `observed`
- `signature`
- `uniqueSampleCount`
- `oracleDiscriminating`

並保留合法 fit/anchor/rotation/mirrored 與非空 hashes，validator 仍缺少一條「從 canonical source fixture + canonical crop/UV + slot semantics 重新算 expected landmarks」的獨立證據鏈。

## Required correction B1 — canonical expected 必須獨立重算

採 **最小修改**，禁止建立第二套 renderer/transform engine。優先重用：

- canonical asymmetric landmark fixture/source generator；
- 現有 production crop / UV transform / `orient_rgb` / sampling helpers；
- 既有 fit / anchor / rotation / mirror slot definition。

Validator 或 validator 直接呼叫的 authority helper 必須：

1. 從 canonical fixture/source identity 取得或 deterministic 重建 source；
2. 從 canonical geometry/UV + slot semantics 重算該 row 的 BL/BR/TR/TL expected；
3. 逐角比較 serialized `expected`；
4. 再比較 serialized `observed`；
5. 再重算 signature/unique/discriminating metadata。

不可新增「expectedHash」後又只相信 payload 裡自己帶的 hash。若需要 source hash / dimensions / fixture id，必須可由 runner/validator獨立驗證或 deterministic 重建。

## Required correction B2 — coordinated tamper 必須 fail-closed

新增至少兩個 canonical validator negative：

1. **Coordinated pixel tamper**：同一 row 的 `expected` + `observed` 一起改成 4 組新的合法且彼此不同 RGB，並同步重寫 signature/unique/discriminating；其餘 slot semantics 合法。必須 FAIL，原因要落在 canonical expected/source authority mismatch。
2. **Cross-slot copy tamper**：把另一個 slot 的完整 expected+observed+metadata 複製進本 slot，但保留本 slot rotation/anchor/mirror 欄位；必須 FAIL。

這兩個 probe 必須真正進 canonical runner evidence，不可只留單元測試。

---

# Evidence flow — A + B 完成後重新產生，不得沿用 `8541089`

`8541089` 現在只證明 **Round 9** 的 docs/evidence 對 `e3eddd3` 已一致，不能拿來證明 Round 10 修正。

A + B 完成後：

1. commit/push 新 code，作為新的 exact `CODE_EVIDENCE_SHA`。
2. 跑完整 `pytest -q`，回報 exact passed count；不可只跑單檔。
3. 核對 exact CODE SHA 的 GitHub Actions Ubuntu + Windows 都 `SUCCESS`。`FOX3D_MOCK_BLENDER=1` 只能標示 MOCK/unit/integration + FIXTURE/REAL_LOGIC，**不是 Production Ready**。
4. clean tree 執行：
   `scripts/run_artwork_placement_e2e.py --expected-commit <CODE_EVIDENCE_SHA>`
   正式 evidence 禁止 `--allow-dirty`。
5. 新 canonical bundle 至少必須包含：
   - 新 `acceptanceGenerationId`
   - `workingTreeClean=true`
   - exact `evidenceCodeCommit`
   - `ok=true`
   - CONTAIN + COVER LEFT/CENTER/RIGHT 全 orientation matrix
   - existing expected↔observed / oracle / slot / row-swap tamper gates PASS
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
7. `docs/GROK_PROGRESS_REPORT.md` 的 Source 旨令必須改成 **本次 supervisor instruction commit**，不能再寫 `157532c`。
8. `docs/CABINET_REAL_ACCEPTANCE.md` 若 cabinet engineering truth 未變，保持不動。
9. evidence/docs commit push 後，核對 docs/head Actions Ubuntu + Windows `SUCCESS`。
10. Issue #1 留完成交接：CODE SHA、full pytest count、CODE Actions run、canonical generation、docs SHA/docs Actions run、REAL/MOCK/PARTIAL/BLOCKED，並明確寫 strict type matrix + coordinated oracle tamper 都已 BLOCK。
11. **STOP，等待 ChatGPT Re-Gate；不得進 Phase 841+。**

---

# Truth labels 不得升級

- Artwork placement / validator：最多 **REAL_LOGIC / FIXTURE acceptance**。
- Blender artwork preview：**MOCK / false**，除非有新的可驗 REAL Blender artwork evidence。
- Physical print：**BLOCKED / false**。
- Demand / Vision / AI Video：**MOCK**。
- print preflight / OS sandbox / AR / barcode / McKee-BCT：**PARTIAL**。
- LIVE_CNC / LIVE_LASER / liveFactory / liveProvider：**BLOCKED**。
- `fullAutonomousFactoryReady` / `globalProductionReady` / `liveFactoryExecutionReady` / `liveProviderReady`：全部維持 `false`。

# Definition of Done

只有以下全部成立才可再送 Re-Gate：

> Round 8/9 已通過的 pixel/oracle/slot/type guards 不退步；strict type negative matrix 完整；validator 能從 canonical source/UV/slot authority 獨立重算 serialized expected landmarks；coordinated expected+observed+metadata tamper 與 cross-slot copy tamper 均 fail-closed；full pytest PASS；exact CODE CI Ubuntu+Windows GREEN；clean-tree canonical bundle 綁 exact CODE 且 `ok=true`；docs/Issue #1 全部更新到本輪；Mock/FIXTURE 不得描述成 Production Ready。
