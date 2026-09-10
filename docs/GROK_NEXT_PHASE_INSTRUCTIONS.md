# Grok 修正指令：Phase 721–780 Re-Gate Round 4 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `58bf2fe83290ecf24ed9e5323b913afe205ef3d8`  
> Reviewed CODE_EVIDENCE_SHA: `b1f29f8a6581de72e26b9215bd54719592f2c3d4`  
> Review result: **CHANGES REQUIRED**  
> **Do not enter Phase 781+.** 本輪只補 Phase 721–780 最後的 canonical independent-authority / quantity-lineage fail-closed 缺口。不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / MaterialLot / ManufacturingRelease / WorkOrder / QC / EventJournal / Outbox / Backup。

## 本輪已接受，必須保留

`b1f29f8` 已實質完成上一輪大部分要求，不得退步：

- FINAL QC：`qcId/qcFinalId` exact binding；tenant/batch/unit/WO/engineering/releaseId/releaseHash/qcPlanHash required；`qcPlanHash` 綁 `batchAuthority.workOrders` pinned value；FINAL 必須 PASS。
- Decision / board：fixture `kind=DERIVED_READINESS`；每 batch exactly one；board/decision required fields exact；blockers 由 fixture/cost 狀態重算；ghost/coordinated mutation regressions 已有。
- Carton：top vs authority L/W/H/weight exact；damage success 只接受 OK/PASS/NONE/NO；unit carton coverage exact。
- Unit execution：material quantity 必須 finite >0；4 batches × 5 units；requestedQuantity 與 execution-complete set 對齊。
- Labor：每 execution-complete unit exactly one labor；laborId exact；idempotencyKey/semantic key required 且重算；ghost labor fail。
- Cost：costId required；每 batch exactly one；fixture packagingQty=MISSING 時維持 PARTIAL/FIXTURE，沒有偽造 physical quantity。
- Crash matrix：create/release/reserve/start/consume/labor/QC/pack/HUMAN_BATCH_GO subprocess `os._exit` 維持 PASS。
- Canonical generation `31913444-645f-462a-acdf-d3dc61d102f5` 維持 `physicalPilotBatchValidated=false`、`batchLaunchDecision=WAITING_HUMAN_EVIDENCE`、所有 global/full/live flags false。
- `pytest -q` 回報 **533 passed**；CODE Actions `34464884088`、docs/head Actions `34465443220` 均 Ubuntu + Windows SUCCESS。
- GitHub Actions workflow 明確使用 `FOX3D_MOCK_BLENDER=1`，因此仍是 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不是 Production Ready。
- Prior REAL Blender 只可引用既有 `7a87ea5` 的 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX scoped evidence。
- `docs/CABINET_REAL_ACCEPTANCE.md` 本輪無 truth change，不要為了更新日期而修改。

---

# Blocker 1 — Material「durable snapshot」仍可 coordinated forged identity

目前 `canonical_authority()` 的 material `reservations/consumed/lotIds` 的確是從現有 WorkOrder 物件產生，但 serialized `batchAuthority.workOrders` 只發布 WO/release/QC-plan identity，沒有發布可供 verifier **獨立交叉驗證**的 reservation / lot / consume authority。Verifier 現在主要驗 material row 內部彼此一致、再與 batch summary 一致；因此若 serialized result 同時把 material row、batch authority、top batch 的 reservationId/lotId 一起換成一組新的假 identity，而 quantity/tenant/WO 不變，仍缺一個不隨該 projection 一起被改的 durable anchor。

這不符合上一輪要求的「reservationIds / lotIds / consume identity exact resolve 到 existing WorkOrder / MaterialLot durable authority」，也不符合 independent serialized truth set。

## Required correction

沿用既有 WorkOrder / MaterialLot；**不要建立第二套 inventory engine**。

1. `batchAuthority.workOrders`（或最小的新 `materialLedgerAuthority`，名稱可依現有模型）要發布 verifier 所需的 immutable durable identity：
   - workOrderId / tenantId / releaseId / releaseHash
   - reservation records：reservationId / lotId / quantity / state / kind
   - consumed records：reservationId / lotId / quantity / state / kind
   - authoritative materialLots lineage / allocationPolicy（現有資料有才發布）
2. Material projection 必須逐筆 exact resolve 到上述 durable authority：ID、tenant、WO、lot、qty、state/kind；不得只比較 material row 自己的 copy。
3. `reservationIds`、`lotIds`、consume identity/count/set 都要 exact-set；missing/duplicate/extra/ghost/cross-tenant/cross-WO 一律 fail。
4. batch top / batchAuthority batch / material projection / durable WO authority 四方的 reservation/lot/consumedQuantity 必須一致。
5. 若 MaterialLot 本身已有 stable immutable fields 可驗，至少將必要 identity/hash 納入 authority；不要把「從 WO 複製到另一欄」當成獨立證據。

### Mandatory negative regressions

- 同時 coordinated 修改 top batch + batchAuthority batch + material projection 的 `reservationId/lotId` 成新的假值，但不改 durable WO authority => fail。
- 同時修改 material `reservations` 與 `consumed` 成另一組假 identity、總量保持相同 => fail。
- durable WO authority 少一 reservation / 多一 ghost reservation => fail。
- reservation quantity 與 durable consume quantity不一致但 batch total仍相同 => fail。
- cross-tenant / cross-WO reservation/lot => fail。

---

# Blocker 2 — Cost `quantityLineage` 目前只重算 source label/ok，沒有重算完整 quantity/identity

目前 `_recompute_qty_sources()` 只產生：

- `materialQty: MATERIAL_LOT|MISSING`
- `laborMinutes: LABOR_RECORD|MISSING`
- `hardwareQty: BOM|MISSING`
- `packagingQty: PACKAGING_CHECKLIST|MISSING`
- `ok`

Verifier 只比這些 source label 與 `ok`。但 canonical cost 內已有/可有 `laborLineage`、`laborMinutes`、`packagingQty` 等資料；目前沒有從 authoritative labor/material/carton/checklist/BOM truth **重新計算 numeric amount + exact IDs/semantic keys** 後再比對。因此 coordinated 修改 cost top + cost authority 的 nested `laborLineage` IDs/minutes（但保留 `sources.laborMinutes=LABOR_RECORD`）有 fail-open 空間。

另外目前 hardware source 只因 carton 任一 `hardwareObserved is not None` 就標 `BOM`，這不是「hardware quantity 已與 BOM authority exact bound」；非-fixture packaging 也不能只因任一 carton 有正數就宣告 `PACKAGING_CHECKLIST`。

## Required correction

1. 不要只回傳 source 字串；建立/擴充 recompute result，至少能從 canonical authoritative records重算：
   - material：reservation/consume IDs、lot IDs、consumed quantity total
   - labor：laborIds exact set、semantic/idempotency keys exact set、minutes total
   - hardware：BOM authoritative expected quantity + observed quantity exact match（若本輪 authority 中已有 BOM snapshot 就引用；沒有則發布最小 immutable BOM quantity authority）
   - packaging：對 MANUAL/IMPORTED 必須由 authoritative checklist exact resolve packagingQty；fixture 必須維持 MISSING
2. `cost.quantityLineage` top 與 cost authority 都必須 exact match recomputed result；不能只比較 `ok/sources`。
3. `laborLineage.laborIds/semanticKeys/minutes` 必須由 `batchAuthority.labor` 重算，順序可 canonicalize，但 set/count/total 要 exact。
4. `materialQty`/lot/reservation lineage 必須由 Blocker 1 durable material authority重算。
5. hardware `BOM` source 只有在 expected BOM qty 存在且 observed/executed qty exact match時成立；`hardwareObserved != None` 不足以證明 BOM authority。
6. MANUAL/IMPORTED packaging `PACKAGING_CHECKLIST` source 只有在每個 launch-relevant carton 的 authoritative checklist identity/qty完成且 exact match時成立；不能 `any(...)` 即通過。
7. fixture canonical 正向案例仍保持 `packagingQty=MISSING`, `quantityLineage.ok=false`, `completeness=PARTIAL`, `truthLabel=FIXTURE`。

### Mandatory negative regressions

- top cost + cost authority 同時把 `laborLineage.minutes` 改成另一個正數，但 labor authority不變 => fail。
- 同時把 laborLineage laborIds/semanticKeys 換成假的 unique IDs/keys => fail。
- 同時修改 material numeric qty/lot lineage，但 durable material authority不變 => fail。
- hardware source 保持 `BOM`，但 BOM expected vs observed qty mismatch => fail。
- MANUAL/IMPORTED 僅一個 carton 有 packagingQty、其他 launch-relevant carton缺 checklist qty => PARTIAL/HOLD，不得 COMPLETE/GO。
- top + authority coordinated 改 `sources/ok` 但底層 authority不變 => fail。

---

# Blocker 3 — Carton source/truthLabel requiredness仍有小型 fail-open

目前 verifier 會比較 top carton vs authoritative carton 的 `source/truthLabel`，但 authoritative carton 與 parent batch 的比較使用 truthy guard；如果 top + authority 同時把 `source/truthLabel` 清空，parent mismatch check 可能被跳過。

## Required correction

1. 每個 positive acceptance carton 的 `cartonId/tenantId/batchId/engineeringHash/source/truthLabel` 全部 required nonblank。
2. `source/truthLabel` 必須與 parent authoritative batch exact match；不要用「有值才比」。
3. MANUAL/IMPORTED 仍必須 re-resolve checklist + DAM；FIXTURE 仍必須標 FIXTURE，不可 blank、不可冒充 MANUAL_EVIDENCE。

### Mandatory negative regressions

- top carton + authority carton 同時將 source/truthLabel blank => fail。
- top + authority 同時改成另一種 truth label、parent batch不變 => fail。

---

# Re-Gate exit criteria

完成後才停下等待 ChatGPT 複查，**仍不得自行進 Phase 781+**。必須提供：

1. 新 `CODE_EVIDENCE_SHA`，clean tree，runner self-bound exact SHA。
2. `pytest -q` 全綠；不得刪舊 tests；新增上述 coordinated-tamper regressions。
3. GitHub Actions exact CODE SHA：Ubuntu + Windows SUCCESS；docs/head push 也要兩平台 SUCCESS。
4. 新 clean canonical generation；pre-serialize / post-serialize / post-publish verifier 都 PASS。
5. 4 batches × 5 units 保持；authority exact-set；tenant isolation / backup-restore / crash matrix保持 PASS。
6. `physicalPilotBatchValidated=false`、fixture `batchLaunchDecision=WAITING_HUMAN_EVIDENCE`、cost PARTIAL/MISSING packaging、所有 global/full/live readiness false。
7. `docs/GROK_PROGRESS_REPORT.md`、`CURRENT_IMPLEMENTATION_AUDIT.md`、`REAL_E2E_ACCEPTANCE.md` 只依真實 evidence 更新；`CABINET_REAL_ACCEPTANCE.md` 若 truth 未變就不要動。
8. Issue #1 留完成摘要，明確寫「FIXTURE/REAL_LOGIC ≠ Production Ready」。

## 下一主線已排隊，但本輪不要開始

Re-Gate 通過後，下一個正式大 Phase 優先做 **Artwork Placement / Surface Decoration Engine**，直接整合既有 Engineering Definition + Blender + DAM，而不是另做孤立貼圖工具。預定方向：

`Engineering 3D → Printable Surface → true mm coordinates → UV → Safe Area → Bleed → Artwork Placement → cross-panel split → Blender Preview → Production Artwork`

要求之後支援櫃門/桌板/展示架/壓克力/包裝等共用 surface decoration、跨門連圖、人物/Logo/文字避門縫/把手/鑽孔、DPI/出血/禁止拉伸，以及 preview placement 與 production asset 的 mm/hash lineage。**本輪僅記錄排程，不得提前實作 Phase 781+。**
