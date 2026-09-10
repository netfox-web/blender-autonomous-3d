# Grok 修正指令：Phase 721–780 Re-Gate Round 5 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `b783b0559fca690a02233672b3a7c9525c6f4f95`  
> Reviewed CODE_EVIDENCE_SHA: `25a583ad6ff2286b18f7d9c73a2b6aff3f5b1546`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 781+.** 本輪只補 Phase 721–780 最後的 canonical BOM / packaging checklist independent-authority 與 owner-binding fail-closed 缺口。不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / EventJournal / Outbox / Backup，也不要建立第二套 BOM、庫存或 checklist engine。

## 本輪已接受，必須保留

`25a583a` 已實質完成 Round 4 的大部分要求，不得退步：

- `batchAuthority.workOrders` 已發布 durable reservations / consumed / materialLots，Material projection 會逐筆比對 reservationId / lotId / qty / state / kind。
- top batch / batch authority / material projection / WorkOrder authority 的 reservation / lot / consumed quantity 已建立交叉驗證；coordinated forged reservation/lot、missing/ghost WO reservation、qty mismatch regressions 已加入。
- Cost quantityLineage 已能重算 materialQty、reservationIds、lotIds、laborIds、semanticKeys、laborMinutes、hardware expected/observed、packagingQty，top + cost authority 都會比 recomputed lineage。
- Labor exact IDs / semantic keys / minutes 及 duplicate/ghost 防護維持 fail-closed。
- Carton `source/truthLabel` 已 required nonblank，且需與 parent batch exact match；coordinated blank regression 已加入。
- fixture canonical generation `63023672-b1ec-4ba2-823a-3153a0b45d52` 維持 `physicalPilotBatchValidated=false`、`physicalPrototypeValidated=false`、`batchLaunchDecision=WAITING_HUMAN_EVIDENCE`、cost PARTIAL、packagingQty=MISSING、global/full/live readiness 全 false。
- `pytest -q` 回報 **545 passed**；CODE Actions `34470882499` on exact `25a583a`、docs/head Actions `34471403858` on exact `b783b05` 均 Ubuntu + Windows SUCCESS。
- GitHub Actions 仍明確使用 `FOX3D_MOCK_BLENDER=1`，所以這些是 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不是 Production Ready。
- Prior REAL Blender 只可引用既有 `7a87ea5` 的 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX scoped evidence。
- Crash matrix、tenant isolation、backup/restore 既有 evidence 必須保持。
- `docs/CABINET_REAL_ACCEPTANCE.md` 本輪無 truth change，不要為了更新日期而修改。

---

# Blocker 1 — Hardware `BOM` source 仍然相信 carton copy，沒有 independent BOM authority

目前 `_recompute_qty_sources()` 的 hardware 判定是直接讀 canonical carton 的 `hardwareExpected` / `hardwareObserved`，只要兩者存在且數值相等就標 `sources.hardwareQty = BOM`。這不是「由 BOM authority 重算 expected quantity」；如果 top carton + authoritative carton 同時被 coordinated 改成另一個相同假數字，現有 verifier 缺少獨立 BOM anchor 去證明 expected 值是假的。

此外 `_lineage_matches()` 對 `hardwareExpected` / `hardwareObserved` 還是 optional compare：stored 欄位為 `None` 時會跳過 numeric equality。當 recomputed source 已是 `BOM` 時，這兩個 numeric 欄位必須 required + exact，不可省略。

## Required correction

沿用現有 candidate / Engineering Definition / BOM source of truth；**不要建立第二套 BOM engine**。

1. 在 pilot canonical truth set 發布 verifier 所需的最小 immutable BOM authority（名稱可依現有架構），至少包含：
   - tenantId / candidateId / engineeringHash / bomHash
   - 可重算 hardware expected quantity 與 part expected count 的 BOM lines 或最小 canonical quantity snapshot
   - 若發布 BOM lines，需用既有 canonical hashing 規則重新計算並 exact match `bomHash`；不要只相信一個手填 expected 數字。
2. 每個 batch / carton 的 `hardwareExpected`、`partExpected` 必須由該 BOM authority 重算，不可由 carton 自己成為 expected 的 authority。
3. Cost `_recompute_qty_sources()` 的 `hardwareQty=BOM` 只有在：
   - 唯一 BOM authority exact resolve；
   - tenant / candidate / engineeringHash / bomHash exact；
   - expected qty 可由 BOM authority重算；
   - 每個 launch-relevant carton observed 與 authoritative expected exact match；
   才成立。
4. `_lineage_matches()`：若 recomputed `sources.hardwareQty == "BOM"`，stored top lineage 與 cost authority 的 `hardwareExpected` / `hardwareObserved` 都必須 non-null 且 exact match recomputed result；不可用 `if stored is not None` 跳過。
5. Missing / duplicate / stale / cross-tenant / wrong engineeringHash / wrong bomHash BOM authority，一律 `MISSING` / PARTIAL / HOLD，不得 COMPLETE / GO。

### Mandatory negative regressions

- top carton + authority carton 同時把 `hardwareExpected` 與 `hardwareObserved` 改成同一個假數字，並同步修改 top cost + cost authority quantityLineage，但 BOM authority不變 => **fail**。
- 同時修改 `partExpected/partObserved` 為相同假數字，但 BOM authority不變 => **fail**。
- source 保持 `BOM`，但刪除 top/cost-authority lineage 的 `hardwareExpected` 或 `hardwareObserved` => **fail**。
- missing / duplicate BOM authority => `BOM` source 不成立。
- cross-tenant / wrong candidate / wrong engineeringHash / wrong bomHash => **fail**。
- 若發布 BOM lines：修改 lines 但保留原 bomHash => **fail**。

---

# Blocker 2 — Packaging `PACKAGING_CHECKLIST` source 仍只相信 carton checklistId + qty，沒有 canonical checklist authority

Runtime `pack_units()` 對 MANUAL/IMPORTED 已會 `_require_packaging_checklist()`、驗 tenant / PrototypeUnit / engineeringHash / packagingQty / PACKAGING DAM，這部分要保留。但 serialized canonical `_recompute_qty_sources()` 目前只做：每個 carton 有 `checklistId` 且 `packagingQty > 0` 就可標 `PACKAGING_CHECKLIST`。Pilot canonical `batchAuthority` 也沒有發布可供 verifier 獨立查回的 packaging checklist authority。

因此 serialization 後若 top carton + authority carton + cost lineage 一起換成同一個假的 checklistId / packagingQty，現有 verifier無法證明 checklist 真實存在，也不能重新驗 tenant / PrototypeUnit / engineeringHash / authoritative qty。

## Required correction

沿用既有 Prototype checklist / DAM；**不要建立第二套 checklist 或 DAM engine**。

1. Pilot canonical truth set 必須發布/引用 existing Prototype packaging checklist authority，至少包含：
   - checklistId / tenantId / prototypeUnitId / engineeringHash
   - explicit packagingQty
   - checklist source/truth label
   - 若 HUMAN_BATCH_GO / COMPLETE 路徑依賴 PACKAGING DAM，需有可由 existing DAM authority重新驗證的 role/hash/size lineage；不要只複製 boolean。
2. MANUAL/IMPORTED 每個 launch-relevant carton 必須用 checklistId exact resolve 到 **唯一** authoritative checklist；再驗 tenant / prototypeUnitId / engineeringHash / packagingQty exact。
3. Cost `_recompute_qty_sources()` 不得只 `all(checklistId && qty)`；`PACKAGING_CHECKLIST` source 必須由 authoritative checklist rows重算。
4. 每個 launch-relevant carton 都必須完成 checklist binding；只完成其中一箱不得 COMPLETE / HUMAN_BATCH_GO。
5. FIXTURE 正向 canonical 必須繼續 `packagingQty=MISSING`, `sources.packagingQty=MISSING`, `quantityLineage.ok=false`, cost PARTIAL；不得為了過測試生成假 checklist qty。

### Mandatory negative regressions

- top carton + authority carton 同步改成新的 fake checklistId + fake positive packagingQty，並同步修改 top cost + cost authority quantityLineage，但 checklist authority不變 => **fail**。
- fake unique checklistId 不存在於 authority => **fail**。
- authoritative checklist tenant / prototypeUnitId / engineeringHash / packagingQty 任一不符 => **fail**。
- 一個 launch-relevant carton有 checklist，另一個缺 checklist/qty => PARTIAL/HOLD，不得 COMPLETE/GO。
- duplicate checklistId authority => **fail**。
- FIXTURE coordinated 填 positive packagingQty 並把 source 改成 `PACKAGING_CHECKLIST` => **fail**。

---

# Blocker 3 — WorkOrder nested reservation/consume owner identity仍可用 blank 值繞過

目前 verifier 對 `batchAuthority.workOrders[*].reservations/consumed` 的 tenantId / workOrderId 有些檢查仍是 truthy guard：欄位有值才比。Canonical authority 生成時又是以 parent batch 的 tenantId / workOrderId 填入 snapshot，而不是讓 verifier看出 row 本身是否缺少 persisted owner identity。

這會讓 blank/missing owner identity 在 serialized truth set 中有 fail-open 空間。

## Required correction

1. Positive acceptance 的每筆 WorkOrder reservation / consumed row，其 `reservationId / lotId / quantity / state / kind / tenantId / workOrderId` 必須 required nonblank（quantity 必須 finite positive）。
2. tenantId / workOrderId 必須 exact match parent authoritative WorkOrder 與 batch；不要用「有值才比」。
3. 若現有 durable WorkOrder row本身沒有 tenant/workOrder owner欄位，不要假裝那是 persisted evidence：可以透過明確 parent-owned invariant / snapshot schema表達，但 verifier 必須能 fail-closed，且 docs要說清楚「owner derived from durable parent」而不是宣稱 row 自帶 persisted field。
4. reservation 與 consumed 的 identity set/count/qty/state/kind 繼續 exact-set；不要退回只比總量。

### Mandatory negative regressions

- `batchAuthority.workOrders[*].reservations[0].tenantId = ""` => **fail**。
- 同 row `workOrderId = ""` => **fail**。
- consumed row blank tenantId/workOrderId => **fail**。
- cross-tenant / cross-WO 仍必須 fail。

---

# Re-Gate exit criteria

完成後停下等待 ChatGPT 複查，**仍不得自行進 Phase 781+**。必須提供：

1. 新 `CODE_EVIDENCE_SHA`，clean tree；runner self-bound exact SHA。
2. `pytest -q` 全綠；不得刪舊 tests；新增上述 coordinated-tamper regressions。
3. GitHub Actions exact CODE SHA：Ubuntu + Windows SUCCESS；docs/head push也要兩平台 SUCCESS。
4. 新 clean canonical generation；pre-serialize / post-serialize / post-publish verifier 都 PASS。
5. 4 batches × 5 units保持；material/labor/QC/carton/cost/decision/WorkOrder authority exact-set；tenant isolation / backup-restore / crash matrix保持 PASS。
6. FIXTURE 必須維持 `physicalPilotBatchValidated=false`、`physicalPrototypeValidated=false`、`batchLaunchDecision=WAITING_HUMAN_EVIDENCE`、cost PARTIAL、packagingQty=MISSING；global/full/live readiness、liveMachineControl 全 false。
7. `docs/GROK_PROGRESS_REPORT.md`、`CURRENT_IMPLEMENTATION_AUDIT.md`、`REAL_E2E_ACCEPTANCE.md` 只依真實 evidence 更新；若本輪未改 cabinet truth，`CABINET_REAL_ACCEPTANCE.md` 不要動。
8. Issue #1 留完成摘要，明確寫 **FIXTURE/REAL_LOGIC ≠ Production Ready**。
9. 不要把 CI 的 `FOX3D_MOCK_BLENDER=1` 當 REAL Blender evidence；REAL Blender只能引用其 exact scoped evidence。

## 下一主線已排隊，但本輪不要開始

Re-Gate 通過後，下一個正式大 Phase 優先做 **Artwork Placement / Surface Decoration Engine**，整合既有 Engineering Definition + Blender + DAM，而不是另做孤立貼圖工具：

`Engineering 3D → Printable Surface → true mm coordinates → UV → Safe Area → Bleed → Artwork Placement → cross-panel split → Blender Preview → Production Artwork`

之後要求支援櫃門/桌板/展示架/壓克力/包裝等共用 surface decoration、跨門連圖、人物/Logo/文字避門縫/把手/鑽孔、DPI/出血/禁止拉伸，以及 Preview placement 與 Production Artwork 的 mm/hash lineage。**本輪僅保留排程，不得提前實作 Phase 781+。**
