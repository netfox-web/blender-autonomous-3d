# Grok 修正指令：Phase 721–780 Re-Gate Round 3 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `2987dbfd6862fc6311d1bd8249c5dff8298e7ac0`  
> Reviewed CODE_EVIDENCE_SHA: `f4c2df8ed197c7e5ec7616c3d8b0170e290090f1`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 781+.** 這輪只修 Phase 721–780 剩餘的 serialized canonical authority / fail-closed 缺口。不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / EventJournal / Outbox / Backup。

## 本輪已接受，必須保留

- MANUAL / IMPORTED `pack_units()` 的 authoritative checklist gate 已實質修正：`checklistId` 必須 resolve exactly one existing checklist，tenant / prototypeUnitId / engineeringHash 為 required exact match；bogus checklist、wrong tenant/unit/hash、qty from other checklist 會 BLOCK；valid MANUAL checklist + PACKAGING DAM 才能過 packaging gate。
- Canonical 已要求 4 batches / 20 units / cartons / labor / FINAL QC / materials / costs / decisions authority，並已加入 FINAL QC FAIL、blank plan、wrong release/WO、duplicate FINAL、duplicate board row、missing decision、PLANNED skip、executedQuantity mismatch、ghost material unit、zero allocation、labor wrong hash/minutes、cost wrong lineage等 regressions。
- `requestedQuantity == exact unit set == execution-complete set` 的方向已落地，不能再只靠 `state != PLANNED` 跳過 execution checks。
- subprocess crash matrix create/release/reserve/start/consume/labor/QC/pack/HUMAN_BATCH_GO 維持 PASS；不要退步。
- `pytest -q` 本輪回報 **506 passed**。CODE Actions `34456077641` on exact `f4c2df8`、docs/head Actions `34456537012` on exact `2987dbf` 均 Ubuntu + Windows SUCCESS。
- CI 明確使用 `FOX3D_MOCK_BLENDER=1`，因此仍只算 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不得宣稱 Production Ready。
- Canonical generation `11ee2235-13d6-4e57-b092-4607bb194b0c` 誠實維持 `physicalPilotBatchValidated=false`、`batchLaunchDecision=WAITING_HUMAN_EVIDENCE`、`globalProductionReady=false`、`fullAutonomousFactoryReady=false`、`liveFactoryExecutionReady=false`、`liveProviderReady=false`、`liveMachineControl=false`。
- Prior REAL Blender 只可繼續引用已驗證 `7a87ea5` 的 4/4 Blender 5.2.1 + NVIDIA T1000 OptiX scope；本輪不能把 Mock CI 升格成 REAL。
- `docs/CABINET_REAL_ACCEPTANCE.md` 本輪沒有 truth change；不要為了進度或日期修改。

---

# Blocker 1 — FINAL QC canonical identity 還不是 required exact binding

目前 verifier 已要求 FINAL `ok=true` / `result=PASS` / 非空 `qcPlanHash`，但還有 optional/fail-open：

- `workOrderId`、`releaseHash` 目前只有「有值才比」，blank/missing 可跳過。
- `qcId` 沒有 required nonblank + 與 unit `qcId/qcFinalId` exact match。
- `releaseId` 沒有 canonical exact binding。
- `qcPlanHash` 目前只要求非空，沒有證明等於該 batch/release/WO 的 pinned authoritative plan hash；任意另一個非空 hash 可能通過。

## Required correction

對每個 positive acceptance unit：

1. exactly one FINAL QC authority row。
2. `qcId` required nonblank；unit `qcId` / `qcFinalId`（依現有模型）必須 exact resolve 到該 row。
3. `tenantId / batchId / unitExecutionId / workOrderId / engineeringHash / releaseId / releaseHash / qcPlanHash` 全部 required nonblank，且與 batch/unit/release/WO 的 authoritative lineage exact match。
4. `ok=true` 且 `result=PASS`；任何 FAIL / blank / stale / conflicting FINAL 都 fail-closed。
5. `qcPlanHash` 必須從現有 release/WO pinned QC plan authority 重算/取得，不可只比較 summary 與 copy authority。

### Mandatory negative regressions

- nonempty 但錯誤的 `qcPlanHash` => fail。
- blank/missing `qcId` => fail。
- unit `qcId/qcFinalId` 與 authority qcId mismatch => fail。
- blank/missing `workOrderId` => fail。
- blank/missing `releaseHash` => fail。
- wrong/blank/missing `releaseId` => fail。
- summary + copied QC authority 同時改成 bogus plan/hash/id，但底層 pinned authority不變 => fail。

---

# Blocker 2 — Decision / board authority 還可 coordinated mutation

目前每 batch 有一筆 decision，fixture 也要求 `WAITING_HUMAN_EVIDENCE`，但 verifier 仍有以下缺口：

- board vs decision 的 tenant/state/engineering 等欄位是「雙方有值才比」，blank/missing 可跳過。
- `decision.kind` 仍允許 `None`；fixture 應明確是 `DERIVED_READINESS`，真正人工決策才是 persisted human decision。
- `blockers` 沒有 exact compare / recompute。
- 沒有拒絕 extra/ghost decision authority row。
- board row + decision row 若同步改 `state`，目前沒有完整綁回 durable batch/unit/QC/carton/cost 所重算的 readiness，因此 coordinated state mutation 仍可能穿過。

## Required correction

1. `batchAuthority.decisions` batch ID set 必須 **exactly equal** canonical batch ID set；每 batch exactly one，無 missing、duplicate、extra、ghost。
2. fixture positive：`kind=DERIVED_READINESS` required；`decision=WAITING_HUMAN_EVIDENCE` required。不得接受 kind missing。
3. board row 與 decision authority 的 `tenantId / batchId / engineeringHash / state / decision / blockers` 全部 required 且 exact match。
4. DERIVED_READINESS 不能只相信 serialized row；必須用已發布的 authoritative batch/unit/QC/carton/cost truth 重算 readiness，再與 board/decision 比對。
5. 若日後有 HUMAN decision，必須 bind exactly one persisted decision record + actor/shift/reason/timestamp/idempotency identity；本輪 fixture 不得偽造 HUMAN decision。

### Mandatory negative regressions

- extra decision for ghost batch => fail。
- decision kind blank/None => fail。
- board or decision tenant/engineering/state blank => fail。
- blockers missing/extra/reordered-semantic mismatch => fail（可先 canonicalize set/order）。
- board row + decision authority 同步改成另一個非 GO state，但 underlying batch readiness 不變 => fail。
- board row + decision authority 同步改 blockers => fail。

---

# Blocker 3 — Carton serialized truth 還沒有 exact measurement / success semantic binding

目前 top carton 與 authority 會比 tenant/batch/engineering/checklist/packagingQty/damageDefect，unit set 也會比；但 L/W/H/weight 現在是「top 或 authority 任一邊有正數即可」，不是 exact equality。另 source/truthLabel、observed-vs-expected semantic、damage success semantics 還未完整 fail-closed。

## Required correction

1. top carton 與 authoritative carton 必須 exact compare：
   - `cartonId / tenantId / batchId / engineeringHash / checklistId`
   - exact `unitExecutionIds`
   - measured `lengthMm / widthMm / heightMm / weightKg`
   - `packagingQty`（若 applicable）
   - `partObserved / hardwareObserved` 與其 expected authority
   - `damageDefect`
   - `source / truthLabel`
2. 每個 unit 的 `cartonId` 必須 exact 指向 covering authoritative carton；不能只要求 nonblank。
3. success acceptance 的 damage/defect 必須是明確可接受結果，不可只因 top/authority 字串相等就 PASS。
4. MANUAL/IMPORTED launch-eligible carton 要繼續 re-resolve authoritative checklist + PACKAGING DAM；不要把 fixture 補成假 physical evidence。

### Mandatory negative regressions

- top + authority 其中一邊 measured dimension/weight 改成另一個正數 => fail。
- top + authority 同步改 measured value，但 underlying checklist/packaging authority不符 => fail（若該值已有 authority）。
- unit `cartonId` 改成另一個有效 carton但 coverage 不符 => fail。
- source/truthLabel mismatch => fail。
- damageDefect 改成 FAIL/DAMAGED/非成功值且兩邊一致 => fail。
- part/hardware observed 與 expected 不符 => fail。

---

# Blocker 4 — Material allocation 尚未綁到 durable reservation / lot / consume authority

目前 verifier 能證明 projection 的 unit ID exact set、quantity > 0、總和 == projection consumedQuantity，也能比 tenant/batch/WO；但還不能證明 `reservationIds / lotIds / consume` 真的是現有 WorkOrder / MaterialLot 的 durable authoritative records。

另外每-unit allocation quantity 尚未 required exact match該 unit 的 allocated/consumed quantity；top batch 的 reservation/lot/consumed summary 也未與 material authority exact 綁定。

## Required correction

沿用現有 WorkOrder / MaterialLot，不建立第二套庫存：

1. canonical `batchAuthority` 新增最小必要的 **material durable authority snapshot**，來源只能是現有 WorkOrder/MaterialLot durable records，例如 reservations/consumes/lots 的 immutable identity、tenant、WO、lot、qty、material/spec/engineering/release lineage。名稱可依既有模型，但不要複製一套新 inventory engine。
2. `BATCH_ALLOCATION_PROJECTION` 必須清楚維持 projection label，且：
   - tenant/batch/WO exact。
   - `reservationIds` / `lotIds` / consume identity exact resolve 到 durable authority。
   - no missing / duplicate / extra / ghost / cross-tenant / cross-WO lot or reservation。
   - sum 必須與 durable consume qty exact。
3. 每個 unit allocation qty finite >0，並與該 unit authoritative `allocatedQuantity/consumedQuantity`（依目前模型）一致；不得只看 batch total。
4. top batch `reservationIds / lotIds / consumedQuantity / allocationPolicy / consumeKind` 必須與 authoritative material snapshot exact binding（對 applicable 欄位）。
5. `_unit_execution_complete()` / canonical execution-complete 判定的 material 部分必須用 authority record + positive quantity，不可 `consumedQuantity is not None` 就算完成；0 / NaN / negative 一律不完整。

### Mandatory negative regressions

- bogus reservationId / lotId，但 projection total 不變 => fail。
- cross-tenant / cross-WO lot or reservation => fail。
- top batch 與 material authority reservation/lot mismatch => fail。
- per-unit projection qty 與 unit consumed/allocated qty mismatch，但總量仍相同 => fail。
- unit `consumedQuantity=0` + 其他欄位正常 => execution incomplete/fail。
- extra material authority for ghost batch => fail。

---

# Blocker 5 — Labor exact identity / exact-set 還有漏口

目前 labor tenant/batch/engineering、minutes >0、duplicate ID/semantic key有檢查，但：

- 若 `idempotencyKey` 缺失但 `laborId` 存在，目前可通過，derived semantic identity不會被 required exact compare。
- coverage 只驗 required executed units 是 labor covered 的 subset；extra ghost labor row 可能存在。
- unit `laborId` 沒有 required exact match該 unit唯一 authoritative labor row。

## Required correction

1. 每個 execution-complete unit exactly one authoritative labor row；labor unit ID set exactly equal required execution unit set，無 extra/ghost。
2. `laborId` required nonblank、global unique；unit `laborId` exact match該 row。
3. `idempotencyKey` / semantic key required nonblank，且必須從 authoritative `tenant/batch/unit/engineering/minutes/reason` 重算 exact match。
4. tenant/batch/unit/engineeringHash exact；minutes finite >0；reason 欄位若參與 semantic key則 required consistent。
5. backup/restore 後仍維持同一 exact semantic identity，duplicate corruption fail-closed。

### Mandatory negative regressions

- laborId 存在但 idempotencyKey blank => fail。
- unit laborId 與 authority laborId mismatch => fail。
- extra unique ghost labor record => fail。
- semantic key 與 row fields不一致 => fail。

---

# Blocker 6 — Cost authority / quantityLineage 仍可只靠 copy fields

目前一 batch 一 cost 的方向有了，但 costId requiredness、exact set、PARTIAL quantityLineage 的 recompute/binding還不完整。Fixture cost 必須繼續 PARTIAL，但 PARTIAL 也必須是「有證據地 PARTIAL」，不是任意 copied object。

## Required correction

1. cost authority batch ID set exactly equal batch set；每 batch exactly one，無 extra/ghost。
2. `costId / tenantId / batchId / completeness / truthLabel` required nonblank/applicable 且 top summary exact match authority。
3. `quantityLineage` 不得相信 serialized `ok`；從本輪發布的 material/labor/packaging/hardware authority重算：
   - material qty source/amount
   - labor IDs/semantic keys/minutes
   - hardware qty/BOM authority
   - packaging qty/checklist authority（fixture 可 MISSING，因此整體 PARTIAL）
4. Fixture 目前沒有 physical packaging qty 就維持 `completeness=PARTIAL`, `truthLabel=FIXTURE`, `quantityLineage.ok=false`；不可補假數據。
5. 若 top costId 缺失、authority costId 缺失、兩者 mismatch、或 lineage coordinated tamper，都 fail。

### Mandatory negative regressions

- blank/missing costId => fail。
- top costId vs authority costId mismatch => fail。
- extra cost authority for ghost batch => fail。
- 修改 quantityLineage source/minutes/material qty/packaging source，但 summary仍 PARTIAL => fail。
- top + cost authority 同步修改 lineage boolean/source，但 underlying material/labor/packaging authority不變 => fail。

---

# Blocker 7 — Positive fixture 要成為完整可獨立驗證的 serialized truth set

完成上述修正後，positive fixture 的成功不能仰賴 Python 物件記憶體或同一來源欄位彼此互抄。

## Required invariants

- 4 batches exactly。
- 20 units exactly，逐 batch requestedQuantity == 5 == execution-complete authoritative unit set。
- 每 unit：start identity + positive material authority + exactly one labor + exactly one FINAL QC PASS + exactly one carton coverage。
- board/decision exact 4 rows，fixture 全部 DERIVED_READINESS / WAITING_HUMAN_EVIDENCE。
- material/labor/QC/carton/cost authority均 exact-set，拒絕 extra ghost rows。
- pre-serialize、post-serialize、post-publish 都 semantic validate PASS。
- 任一 negative/tampered run不得覆寫 prior good canonical acceptance。

---

# Re-Gate evidence requirements

1. **不要進 Phase 781+.** 只修上述 residual canonical authority gaps。
2. 不重寫既有架構；沿用 PilotBatch / Prototype / WorkOrder / MaterialLot / DAM / Journal / Outbox / Backup。
3. 完整跑 `pytest -q`，回報 exact count；標示 MOCK/unit/integration + FIXTURE/REAL_LOGIC，不是 Production Ready。
4. implementation + tests 先 commit 為新的 **CODE_EVIDENCE_SHA**；exact SHA 的 Ubuntu + Windows GitHub Actions 必須 SUCCESS。
5. clean tree 上用 exact CODE SHA 重跑 canonical runner；`evidenceCodeCommit` exact match、`workingTreeClean=true`。
6. canonical fixture 必須維持 `physicalPilotBatchValidated=false`、`batchLaunchDecision=WAITING_HUMAN_EVIDENCE`；不得出現 HUMAN_BATCH_GO；所有 global/full/live flags仍 false。
7. 重跑 tenant-A backup/restore exact-set + semantic verifier；zero tenant-B leakage。新增的 material/QC/decision/labor/cost authority也必須 restore 後一致。
8. crash matrix create/release/reserve/start/consume/labor/QC/pack/HUMAN_BATCH_GO 必須維持 subprocess `os._exit` PASS；本輪若改動相關 persistence，至少重跑完整 matrix。
9. render/engineering/media path未變且 prior verifier仍 PASS，可引用 `7a87ea5` REAL Blender；若有變則重新跑 REAL evidence。
10. 更新 `docs/GROK_PROGRESS_REPORT.md`、`docs/CURRENT_IMPLEMENTATION_AUDIT.md`、`docs/REAL_E2E_ACCEPTANCE.md`、`docs/PILOT_BATCH_EXECUTION_ACCEPTANCE.md/.json`、`docs/COMMERCIAL_LAUNCH_READINESS_ACCEPTANCE.md/.json`。Cabinet truth未變就不要修改 `docs/CABINET_REAL_ACCEPTANCE.md`。
11. runner evidence/docs另 commit，docs/head exact SHA 的 Ubuntu + Windows Actions也必須 SUCCESS。
12. Issue #1 留完成回報：CODE SHA、docs SHA、pytest count、兩組 Actions run IDs、generation ID、上述 QC/decision/carton/material/labor/cost negative tests、crash matrix、backup/tenant isolation、prior REAL Blender驗證與 REAL/MOCK/PARTIAL/BLOCKED matrix。
13. **完成後停止，等 ChatGPT Re-Gate。**

## Boundary labels 必須維持

- Pilot batch workflow / genealogy / crash recovery：**REAL_LOGIC**（僅限已驗證軟體邏輯）。
- Current automated pilot batch / CI batch：**FIXTURE / REAL_LOGIC**，不是 physical batch。
- Prior Blender media：**REAL** 只限已驗證 `7a87ea5` scope。
- Demand / Vision / AI Video：**MOCK**。
- OS sandbox / AR / preflight / barcode / McKee-BCT：**PARTIAL**。
- LIVE_CNC / LIVE_LASER / PLC / live provider / automatic live factory：**BLOCKED**。
- `physicalPilotBatchValidated=false`、`physicalPrototypeValidated=false`、`globalProductionReady=false`、`fullAutonomousFactoryReady=false`、`liveFactoryExecutionReady=false`、`liveProviderReady=false`、`liveMachineControl=false`，直到真正 authoritative evidence 改變為止。
