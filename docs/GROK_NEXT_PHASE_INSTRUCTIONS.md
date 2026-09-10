# Grok 修正指令：Phase 721–780 Re-Gate Round 2 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `ae791be195805ad96c1647d2db3fd43efc30d732`  
> Reviewed CODE_EVIDENCE_SHA: `83f4fe0b1f72b4a09299de9fec0e79c2bd870ab7`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 781+.** 這輪只修 Phase 721–780 剩餘的 fail-closed / authority binding 缺口。不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / EventJournal / Outbox / Backup。

## 本輪已接受，必須保留

- 上一輪要求的 4 batches / 20 units / 4 cartons / 20 labor / 20 FINAL QC / 4 materials / 4 costs canonical authority 已落地。
- `cartons=[]`、`board.rows=[]`、missing QC/material/labor、unit lineage mismatch、carton coverage 缺口已有負向 runner regressions。
- Runtime 已要求 FINAL QC + pinned `qcPlanHash`；IN_PROCESS PASS 不能代替 FINAL。
- `pack_units()` 已阻擋 PLANNED / 未 start / 未 consume / 無 labor 的 unit，且 MANUAL 路徑要求尺寸、重量、料件/五金數、damage/defect、PACKAGING DAM。
- subprocess `os._exit` crash matrix 已覆蓋 create/release/reserve/start/consume/labor/QC/pack/HUMAN_BATCH_GO 的 after-business-persist 與 after-outbox-complete 邊界；保留 exactly-once + zero-open-outbox 行為。
- `pytest -q` = **487 passed**；CODE Actions `34450605677`、docs/head Actions `34450924098` 均 Ubuntu + Windows SUCCESS。
- CI 使用 `FOX3D_MOCK_BLENDER=1`，所以仍只算 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不可宣稱 Production Ready。
- Canonical generation `64077573-bb56-4d50-8501-8e5ee8f0b3f4` 維持 `physicalPilotBatchValidated=false`、`batchLaunchDecision=WAITING_HUMAN_EVIDENCE`、global/full/live readiness 全 false。
- Prior REAL Blender 可繼續引用 `7a87ea5` 的 4/4 Blender 5.2.1 + NVIDIA T1000 OptiX，前提是 render/engineering/media path 未改且 verifier 仍 PASS。
- `docs/CABINET_REAL_ACCEPTANCE.md` 本輪沒有 truth change；不要為了日期或進度而修改。

---

# Blocker 1 — MANUAL packaging checklist identity 仍可 fail-open

目前 `pack_units()` 會先用 `checklist_id` 查 `proto.checklists`，但 MANUAL/IMPORTED 路徑只有在 `pack` 找得到時才驗 tenant / prototypeUnit / engineeringHash；如果傳入一個不存在的 `checklist_id`，`pack=None` 時這段 identity 驗證會被跳過。後續 `_carton_packaging_ok()` 也只要求 `carton.checklistId` 非空，重新 lookup 後即使 `pack=None`，仍可能僅靠 evidence package 的 PACKAGING DAM 通過。

這表示「bogus checklist ID + explicit packagingQty + 其他欄位/DAM 正常」目前有機會進入 READY/HUMAN_BATCH_GO。這違反上一輪要求的 authoritative checklist exact lineage。

## Required correction

對 MANUAL / IMPORTED launch-eligible path：

1. `checklistId` 必須 resolve 到 **exactly one existing authoritative packaging checklist**；不存在、duplicate/corrupt、空值一律 BLOCK/HOLD。
2. checklist 的 `tenantId` 必須非空且 exact match batch tenant。
3. `prototypeUnitId` 必須非空且 exact match current batch `prototypeUnitId`；不得再接受 `None` 當相容值。
4. `engineeringHash` 必須非空且 exact match current batch engineeringHash；不得用「有值才比」的 optional gate。
5. 若 checklist 有 candidate / selection / evidencePackage lineage，必須 exact match current batch/prototype lineage。
6. `packagingQty` 必須來自同一份 authoritative checklist/observed record，或以明確 MANUAL observed record 綁定該 checklist ID；不能只接受 caller 塞一個數字卻無法證明來源。
7. `_carton_packaging_ok()` 必須重新 resolve checklist 並重新驗證上述 identity + PACKAGING DAM，不得相信 carton 上預先 copy 的 `checklistId` / `packagingQty`。
8. FIXTURE 可保留非實體 packagingQty 缺失並維持 PARTIAL；不得為了測試補假的 physical authority。

### Mandatory runtime regressions

- nonexistent/bogus `checklist_id` + valid explicit qty + valid package DAM => BLOCK。
- checklist tenant blank/wrong => BLOCK。
- checklist `prototypeUnitId` blank/wrong => BLOCK。
- checklist `engineeringHash` blank/wrong => BLOCK。
- stale/superseded checklist => BLOCK。
- packagingQty 來自不同 checklist => BLOCK。
- 正確 MANUAL checklist + exact lineage + authoritative PACKAGING DAM 才能通過 packaging gate。

---

# Blocker 2 — Serialized canonical verifier 仍未證明「成功語意」與完整 authority

`validate_pilot_batch_acceptance_result()` 雖然已加入 authority exact-set，但目前仍有幾個明確 fail-open：

## A. QC authority 只驗「PASS 或 FAIL 都是合法字串」，沒有要求成功 acceptance 必須 PASS

目前 sampled unit 的 FINAL QC 只檢查 `result in {PASS, FAIL}` + `qcPlanHash` 非空，再比 tenant / engineeringHash；因此把 canonical FINAL QC 由 PASS 改成 FAIL，仍可能保持 `ok=true`。

### Required

對本 Phase 的 positive acceptance truth：每個 required sampled unit 必須 resolve **exactly one FINAL QC PASS**，且 verifier 要重新比對：

- `qcId`
- tenantId
- batchId
- unitExecutionId
- workOrderId
- engineeringHash
- releaseId/releaseHash（依現有 authoritative model 可取得欄位）
- pinned `qcPlanHash`
- `ok=true`
- `result=PASS`

FINAL FAIL、missing/blank/stale/wrong plan、wrong WO/release、duplicate/conflicting FINAL 都必須讓 canonical `ok=false`。

## B. `batchAuthority.decisions` 已發布/讀取但 verifier 幾乎沒有使用

目前 verifier 建立 `auth_decisions`，最後只檢查 `board.rows` 的 batch key coverage，沒有把每個 board row 的 tenant/state/decision/blockers 與 authority 綁起來，也沒有防 duplicate board row。

### Required

建立明確且不造假的 decision/readiness authority：

- 若存在 HUMAN decision，board row 必須 resolve exactly one persisted decision record。
- 若 fixture 還沒有 persisted HUMAN decision，請發布一筆明確標成 `DERIVED_READINESS` / `WAITING_HUMAN_EVIDENCE` 的 authority，內容由 durable batch/unit/QC/carton/cost state 重算，不要偽造 HUMAN decision。
- board batch ID set 必須與 batch exact set 完全一致，且每 batch exactly one row。
- tenantId / batchId / engineeringHash / state / decision / blockers 必須與 authoritative/derived readiness exact match。
- coordinated 修改 board row + copied authority 成 bogus decision/state 也必須被底層 durable authority/digest 驗證拒絕。

## C. Canonical 可以把 unit state 協調改成 PLANNED 來繞過 execution-chain 檢查

目前只有 `auth.state != PLANNED` 才加入 executed set，再做 labor/QC/material 檢查；卻沒有要求這個 Phase 的 canonical positive fixture 之 `requestedQuantity == exact unit set == execution-complete unit set`。因此 summary + authority 同時改成 PLANNED 時，有機會把 required execution checks 整段跳過。

### Required

- 對 Phase 775–780 positive acceptance，逐 batch 要驗 `requestedQuantity == exact unit set == expected executed/eligible unit set`。
- 20 個 fixture unit 必須都能由 start + material allocation/consume + labor + required FINAL QC + carton chain證明完成該 runner 所宣稱的 execution scope。
- 不要只靠 `state` 字串判定 executed；從 authoritative fields/records重算 execution completeness。
- top-level `executedQuantity`、unit state、authority records三者不一致要 fail。

## D. Carton / Material / Labor / Cost authority 還需要 exact semantic binding

### Carton

Verifier 必須比較 top carton 與 authoritative carton 的：tenant/batch/engineering/checklist ID、exact unit set、L/W/H/weight、packagingQty（若 applicable）、part/hardware observed vs expected、damage/defect、source/truth label；MANUAL/IMPORTED 另需 authoritative checklist + PACKAGING DAM lineage。

### Material

`BATCH_ALLOCATION_PROJECTION` 除了 sum == consumedQuantity 外，還要驗：

- allocation `unitExecutionId` exact set == 該 batch required unit set；不得配置到不存在/別 batch/別 tenant unit。
- 每筆 allocation quantity finite > 0。
- tenant/batch/WO/reservation/lot/consume lineage exact match現有 WorkOrder/MaterialLot authority。
- projection 必須持續清楚標示「allocation projection」，不可描述為 direct per-unit physical consume。

### Labor

除 coverage/semantic uniqueness 外，再驗 tenant/batch/unit/engineeringHash exact match、minutes finite > 0，semantic key 可由 authoritative row重算且與 idempotency identity一致。

### Cost

即使 FIXTURE cost 維持 PARTIAL，也要確保 cost authority 的 costId/tenant/batch/completeness/truthLabel/quantity lineage 與 batch row exact binding；不能只因「有一筆 cost record」就算通過。

---

# Mandatory negative canonical regressions

至少新增：

1. FINAL QC 改成 `FAIL/ok=false` => fail。
2. FINAL QC wrong/blank `qcPlanHash`、wrong batch/unit/WO/releaseHash => fail。
3. duplicate/conflicting FINAL QC => fail。
4. board duplicate row => fail。
5. missing/extra decision/readiness authority => fail。
6. coordinated bogus board decision/state + copied authority => fail。
7. 將某 batch 的所有 unit summary + authority `state` 同步改為 PLANNED，但其他資料留著 => fail。
8. `executedQuantity` 與 authoritative execution-complete set不一致 => fail。
9. carton summary + authority 的 tenant/engineering/checklist/count/damage 任一 coordinated mismatch against underlying authority => fail。
10. material allocations 改成 bogus/nonexistent/cross-batch unit IDs但總量不變 => fail。
11. material allocation quantity 0/negative/NaN => fail。
12. labor wrong engineeringHash / zero or invalid minutes => fail。
13. cost wrong tenant/batch/costId lineage => fail。

保留一份真正完整的 positive serialized fixture，並在 pre-serialize、post-serialize、post-publish 三段都 semantic PASS。

---

# Re-Gate evidence requirements

1. **不要進 Phase 781+.** 只修上述 residual gaps。
2. 不重寫既有架構；沿用目前 PilotBatch / Prototype / WorkOrder / MaterialLot / DAM / Journal / Outbox / Backup。
3. 跑完整 `pytest -q`，回報新 exact count；標示 MOCK/unit/integration + FIXTURE/REAL_LOGIC，不是 Production Ready。
4. implementation/tests 先 commit 成新的 **CODE_EVIDENCE_SHA**，該 exact SHA 的 Ubuntu + Windows GitHub Actions 必須 SUCCESS。
5. clean tree 上以 exact CODE SHA 重跑 Phase 721–780 canonical runner；所有上述 tamper/negative shapes 必須 fail-closed，失敗不得覆寫 prior good acceptance。
6. canonical fixture 必須維持 `physicalPilotBatchValidated=false`、不得出現 HUMAN_BATCH_GO；global/full/live flags 全 false。
7. 重跑 tenant-A backup/restore exact-set + semantic checks，證明新 authority/state restore 後一致且 zero tenant-B leakage。
8. 若 render/engineering/media path 未變且既有 verifier通過，可繼續引用 prior REAL Blender `7a87ea5`; 否則重新跑 REAL Blender evidence。
9. 更新 `docs/GROK_PROGRESS_REPORT.md`、`docs/CURRENT_IMPLEMENTATION_AUDIT.md`、`docs/REAL_E2E_ACCEPTANCE.md`、`docs/PILOT_BATCH_EXECUTION_ACCEPTANCE.md/.json`、`docs/COMMERCIAL_LAUNCH_READINESS_ACCEPTANCE.md/.json`。Cabinet truth 未變不要碰 `docs/CABINET_REAL_ACCEPTANCE.md`。
10. runner-generated evidence/docs 另 commit，docs/head SHA 也必須 Ubuntu + Windows Actions SUCCESS。
11. Issue #1 回報：CODE SHA、docs SHA、pytest count、兩組 Actions run IDs、generation ID、runtime checklist negative tests、QC/decision/execution/carton/material/labor/cost canonical negative tests、crash matrix維持 PASS、backup/tenant結果、prior REAL Blender驗證與剩餘 REAL/MOCK/PARTIAL/BLOCKED。
12. **完成後停止，等 ChatGPT Re-Gate。**

## Boundary labels 必須維持

- Pilot batch workflow / genealogy / crash recovery：**REAL_LOGIC**（僅限已驗證軟體邏輯）。
- Current automated pilot batch：**FIXTURE / REAL_LOGIC**，不是 physical batch。
- Prior Blender media：**REAL** 只限既有已驗證 `7a87ea5` scope。
- Demand / Vision / AI Video：**MOCK**。
- OS sandbox / AR / preflight / barcode / McKee-BCT：**PARTIAL**。
- LIVE_CNC / LIVE_LASER / PLC / live provider / automatic live factory：**BLOCKED**。
- `physicalPilotBatchValidated=false`、`globalProductionReady=false`、`fullAutonomousFactoryReady=false`、`liveFactoryExecutionReady=false`、`liveProviderReady=false`、`liveMachineControl=false`，直到真正 authoritative evidence 改變為止。
