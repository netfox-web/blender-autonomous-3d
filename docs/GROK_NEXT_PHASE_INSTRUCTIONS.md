# Grok 下一階段開發指令：Phase 121–180 Small-Space KD / Flat-Pack Product Factory

> Repo: `netfox-web/blender-autonomous-3d`
> 審核基線：main `4448ed39d70c2b65b1c126ce8ff30430df6fa847`
> 審核結論：**ACCEPT WITH SCOPE**。Phase 71–120 有實質完成，可進下一輪；但 readiness 必須限定範圍，不得把 MOCK/PARTIAL 說成全系統 Production Ready。

## ChatGPT 本輪審核結果

已核對 `GROK_PROGRESS_REPORT.md`、`CURRENT_IMPLEMENTATION_AUDIT.md`、`REAL_E2E_ACCEPTANCE.md`、`CABINET_REAL_ACCEPTANCE.md`、`FURNITURE_FACTORY_REAL_ACCEPTANCE.md/json`、新增 tests 與主要 nesting/acceptance execution path。

目前可接受的 REAL 證據：
- Blender 5.2.1 LTS 真 executable。
- NVIDIA T1000 4GB 真 discovery，UUID/VRAM/driver 有紀錄。
- Cycles/OptiX 真 probe。
- 3600mm wall → legal layouts → multi-cabinet → BOM → nesting → quote → real Blender preview → WAITING_APPROVAL。
- Assembly MP4 與 depth/normal/seg AOV 有真 artifact evidence。
- `pytest -q` 回報 57 passed；目前 GitHub commit 沒有 status checks，因此這是 local test evidence，不是 CI evidence。

仍需維持：
- Vision Judge = **MOCK**（無 live Provider）。
- AI Video = **MOCK**（無 ProviderAdapter）。
- OS sandbox = **PARTIAL**（path guard / SANDBOX ONLY，不是 OS jail）。
- LIVE_CNC = **BLOCKED**，`liveMachineControl=false`，Human Approval Gate 必須保留。

Readiness 命名必須改善：`productionReady=true` 目前只能代表「core deterministic furniture preview E2E 在此 host 可跑」，不能代表 Vision/AI Video/OS sandbox/CNC 全部 production ready。下一輪請加入明確 scoped readiness，例如 `coreFactoryE2EReady`、`commercializationReady`、`fullAutonomousFactoryReady`，並列 required/optional capability matrix。

## 本輪產品目標

把家具工廠從「系統櫃 / 多櫃」擴成真正適合學生、租屋、小宅、電商宅配的 **KD / Flat-Pack Product Factory**。

系統評分不能只看外觀，必須同時計算：

`可製造性 × 板材利用率 × 真廢料率 × 可回收餘料率 × 共用件率 × 包裝材積 × 包裝重量 × 物流成本 × 組裝難度 × 成本 × 毛利 × 商品需求分數`

市場需求若沒有真資料 Provider，只能標 MOCK/SIMULATED，不可寫 REAL。

---

# Phase 121–130：Small-Space Flat-Pack 產品族

## Phase 121 — FlatPackProductType Registry
在既有 Parametric / Furniture Registry 上擴充，不另建第二套引擎。至少支援：
- BEDSIDE_CABINET
- DESK_RISER
- OPEN_SHELF
- NARROW_BOOKCASE
- MOBILE_SIDE_TABLE
- STUDENT_DESK
- VANITY_DESK
- GARMENT_RACK
- APPLIANCE_RACK
- STORAGE_BENCH
- PET_FURNITURE
- RETAIL_DISPLAY

每一類至少有 geometry + BOM regression；不能只有 enum。

## Phase 122 — Standard Dimension Grid
建立可配置的 KD 標準模組尺寸，不硬編碼成唯一規則：
- width candidates：300/400/600/800mm
- depth candidates：250/300/400mm
- height candidates：400/800/1200/1600mm
允許產品族覆寫，但 Product R&D 優先使用標準尺寸以提高零件共用與排版效率。

## Phase 123 — Flat-Pack Engineering Definition
在既有 Engineering SoT 上加入 flatPack metadata：拆裝方向、panel grouping、connector zones、maximum loose-part count、tool requirements。禁止 Blender 成為第二尺寸來源。

## Phase 124 — KD Connector Standard
將 cam lock / dowel / screw / bolt / bracket / caster / handle 抽象成可版本化 connector recipe。五金仍 vendor-neutral；真品牌料號之後由 adapter mapping。

## Phase 125 — Product Templates
為 12 類產品建立最小可工作的 parametric template；優先 panel-based / KD-friendly。桌、架、櫃不得全部只是 STORAGE_CABINET 改名字。

## Phase 126 — Assembly Graph V2
每個產品輸出 assembly graph：part → connector → step dependencies。要能判斷可否拆平、是否有循環依賴、是否需要兩人組裝。

## Phase 127 — Common-Part Fingerprint
每個板件建立 canonical fingerprint：material/thickness/length/width/edge/drill pattern/grain。用來判斷跨 SKU 真正共用零件，不只尺寸接近。

## Phase 128 — SKU Family / Variant Family
同一 chassis 可衍生有門/無門、輪子/固定腳、不同高度、不同材質；建立 parent family + immutable SKU version lineage。

## Phase 129 — Common-Part Ratio
計算 `commonPartRatio`、`uniquePartCount`、`hardwareCommonality`。Product R&D 可把高共用件率當正向分數，但不能犧牲 Engineering Rule。

## Phase 130 — Flat-Pack Product Family Acceptance
建立 regression matrix，證明至少 8 個不同產品族真走：
`params → Engineering Definition → geometry → BOM → common-part fingerprint → Blender preview`。

---

# Phase 131–140：KD 包裝、物流與組裝難度

## Phase 131 — Flat-Pack Panel Envelope
由拆解後板件計算 largest panel、stack dimensions、loose hardware envelope，不可手填假紙箱尺寸。

## Phase 132 — PackagingBox Solver
從板件堆疊 + padding + hardware box 自動估算最小可行 carton L/W/H；保留 packaging recipe/version/hash。

## Phase 133 — Packaging Materials
建立 carton、EPE/蜂巢紙/護角/袋材等 packaging BOM；未有真供應商價格時標 ESTIMATED，不得 REAL COST。

## Phase 134 — Packed Weight
由 material density + hardware + packaging material 計算 gross/net weight；缺真 density 要標 assumption source。

## Phase 135 — Shipping Cube
計算 CBM、長寬高、最長邊、材積重；物流費規則必須 adapter/config 化，不硬綁單一台灣物流商。

## Phase 136 — Parcel Tier / Oversize Gate
建立 configurable shipping tiers，判斷是否超材/超重；若超過目標宅配級距，Product R&D 要能要求 redesign。

## Phase 137 — Assembly Instruction Manifest
由 Assembly Graph 產 step-by-step machine-readable manifest：step、parts、hardware、tool、orientation、warning。先資料正確，再做漂亮說明書。

## Phase 138 — Assembly Difficulty Score
至少包含：part count、unique fastener types、tool count、steps、reorientation count、two-person steps、estimated time。不可只用 LLM 主觀分數。

## Phase 139 — Tool-Minimization / Fastener-Minimization
Variant optimizer 可嘗試減少工具種類與五金種類；任何變動必須重新 engineering validate / BOM / hash。

## Phase 140 — KD Logistics Gate
建立 hard/soft constraints，例如：one-carton preference、max packed weight、max longest side、max assembly difficulty。門檻放 config/policy，不要寫死成全球標準。

---

# Phase 141–150：真廢料率、餘料與跨 SKU Nesting

## Phase 141 — Waste Accounting V2
修正目前 `wasteArea = sheet total - used parts` 過度簡化。至少分開：
- partUsedArea
- kerfLossArea
- trimLossArea
- reusableRemnantArea
- trueScrapArea
- utilizationRatio
- reusableRemnantRatio
- trueWasteRatio
總面積需守恆，可有 tolerance。

## Phase 142 — Remnant Qualification Policy
建立「可回收餘料」判斷 policy：min width/height/area、material、thickness、grain、quality grade。門檻可設定，不硬編碼 5%/8%/15%。

## Phase 143 — Remnant Inventory
建立 RemnantInventory：remnantId、sourceNestingRun、material、thickness、L/W、grain、location、status、reservedBy、consumedBy、createdAt。沿用現有 persistence style，不另建 WMS。

## Phase 144 — Nesting → Remnant Extraction
每張排版完成後，自動把符合資格的 free rectangles/guillotine remnants 寫入 RemnantInventory；小碎片才算 true scrap。

## Phase 145 — Remnant-First Nesting
Nesting 前先嘗試使用 compatible remnants，再開新整板；要記錄 savedNewSheetCount / remnantConsumedArea / costSaved。

## Phase 146 — Batch Single-SKU Nesting
支援同 SKU quantity=10/20/50/100 一次排版，不得只是把單件 nesting 結果乘數量。

## Phase 147 — Cross-SKU Nesting
可把不同 SKU 同材質/厚度板件合併排版，例如床邊櫃×20 + 書架×10 + 桌上架×30；保留每個 part 的 skuId/productVersion lineage。

## Phase 148 — Nesting Objective Function
至少可配置多目標：min sheets、min true scrap、max remnant value、min cut complexity、respect grain。保留 deterministic baseline；優化器結果要可重現（seed/config hash）。

## Phase 149 — Waste-Driven Redesign Feedback
若產品只差少量尺寸即可顯著提高排版效率，系統可提出候選修改，例如 620→600mm；只能提出 Candidate，必須重新跑 engineering/ergonomic constraints，不能偷偷改正式產品。

## Phase 150 — Nesting Benchmark
建立 benchmark：同一組訂單比較 independent SKU nesting vs batch single-SKU vs cross-SKU + remnant-first，輸出 sheetCount、utilization、trueWasteRatio、reusableRemnantRatio、cost delta。

---

# Phase 151–160：批量生產成本、物流成本與商品化經濟模型

## Phase 151 — ProductionBatch
建立 ProductionBatch：SKU versions + quantities + target date + material group；不接真 ERP 採購動作。

## Phase 152 — Aggregate BOM
跨 SKU 彙總板件、五金、包材需求；仍保留 source SKU lineage。

## Phase 153 — Hardware Purchasing Estimate
計算五金總需求、共用 SKU、整包採購 rounding；無真供應商 API 時標 ESTIMATED。

## Phase 154 — Processing Cost V2
成本加入 cut count、drill count、edge-band length、tool changes、nesting sheet count、assembly minutes。

## Phase 155 — Packaging Cost
由 packaging BOM 計算單箱包材成本；價格來源要有 `source=CONFIG/MOCK/REAL_PROVIDER`。

## Phase 156 — Logistics Cost Adapter
建立物流費 adapter interface，輸入 carton/weight/zone/service。沒有真物流 API 時用 CONFIG/SIMULATED，不宣稱即時運費。

## Phase 157 — Fully Landed Unit Cost
`material + waste + remnant credit + hardware + processing + packaging + logistics + assembly` → unit landed cost。Remnant credit 要有可追溯 policy，避免重複抵扣。

## Phase 158 — Margin / Price Policy V2
支援 target gross margin、minimum contribution、promo floor、channel fee placeholder。Payment 仍不在本輪。

## Phase 159 — Quantity Break Simulation
比較 1/10/20/50/100 件：unit cost、sheet utilization、pack cost、logistics、margin；顯示規模經濟而不是線性乘法。

## Phase 160 — Commercial Feasibility Gate
Candidate 至少通過 engineering、KD logistics、true waste、landed cost、margin policy 才能進 `COMMERCIAL_CANDIDATE`；市場需求資料若 MOCK，只能標 `MARKET_UNVERIFIED`。

---

# Phase 161–170：餘料反向開發新品 + AI Product R&D

## Phase 161 — MaterialInventory Snapshot Adapter
建立 read-only material availability interface：full sheets、remnants、hardware、packaging。無真 ERP/WMS 連線時可用 fixture，但標 MOCK/CONFIG。

## Phase 162 — Remnant Constraint Set
把一批餘料轉成設計限制：可用矩形、material/thickness/grain、最大零件尺寸、數量。

## Phase 163 — Reverse Product Search
從 Remnant Constraint Set 找可行 product templates，不先指定商品，例如餘料可候選桌上架/小層架/寵物碗架/小邊桌。先 deterministic feasibility，LLM 只負責 idea layer。

## Phase 164 — Remnant-Fit Variant Generator
對可行產品掃描尺寸參數，使使用餘料最大化；每個 variant 都要 Engineering Validate + KD Gate。

## Phase 165 — Small-Space Customer Profile
建立學生/租屋/小宅 profile：small footprint、easy move、one-carton preference、simple assembly、budget target。這是 product policy，不是個人資料。

## Phase 166 — DemandSignal Provider Interface
建立市場需求/搜尋/銷售訊號 adapter interface。無真資料 source 時回 `MOCK`/`UNAVAILABLE`，不得自己編「熱銷」數字。

## Phase 167 — Product R&D Score V2
分數拆開並保留明細：
- engineering validity（hard veto）
- true waste / sheet utilization
- remnant consumption
- common-part ratio
- packaging cube/weight
- assembly difficulty
- landed cost / margin
- demand score（可能 MOCK）
- visual score（可能 MOCK）
不要把不同可信度資料混成一個看似 REAL 的總分。

## Phase 168 — Autonomous Candidate Generation
可批次生成 100+ deterministic/seeded candidates，先低成本 rule/cost/nesting filter，再對 Top N 做 Blender preview；禁止 100 個全部高成本 final render。

## Phase 169 — Top-N Candidate Board
Admin/API 顯示候選：產品圖、尺寸、BOM、trueWasteRatio、remnantUsed、commonPartRatio、carton、weight、assembly score、landed cost、suggested price、data-confidence labels。

## Phase 170 — Human Product Approval
狀態：IDEA → ENGINEERING_VALID → DFM_VALID → COMMERCIAL_CANDIDATE → WAITING_PRODUCT_APPROVAL → APPROVED_FOR_PROTOTYPE。禁止直接 APPROVED_FOR_PRODUCTION / LIVE_CNC。

---

# Phase 171–180：電商素材、說明、CI 與 REAL Acceptance

## Phase 171 — E-commerce Render Recipe
用既有 Blender Queue/Recipes 產 white-background hero、3/4 view、detail view、scale/context shot；不另建 render queue。

## Phase 172 — Flat-Pack / Exploded Render
自動產 flat-pack contents view、exploded view、numbered assembly preview；part IDs 必須與 Assembly Instruction Manifest 一致。

## Phase 173 — 360 / Web3D Asset
沿用 Digital Twin / DAM 輸出商品 360 與 GLB/Web3D manifest；不得另外建立資產庫。

## Phase 174 — AR Metadata
輸出真實尺寸、floor/wall placement intent、bounding box、anchor metadata；AR renderer 若沒有真 runtime，標 PARTIAL，不是假 REAL。

## Phase 175 — Assembly Instruction Assets
由 manifest + Blender 自動生成每步 preview images；若生成 PDF/HTML 說明，內容必須由同一 assembly graph，禁止人工另一套步驟資料。

## Phase 176 — Retail Display Bridge
讓 `RETAIL_DISPLAY` 也走同一 flat-pack/BOM/nesting/waste/packaging pipeline，證明底層不是只適用住宅櫃。

## Phase 177 — CI Evidence
若 repo 尚無 CI，加入最小 GitHub Actions：lint/typecheck（若專案已有）+ pytest。REAL Blender/OptiX 不強迫跑在 GitHub hosted runner；但 unit/regression test 必須有可見 CI status。若權限/環境阻擋，標 BLOCKED 並保留 local evidence。

## Phase 178 — Scoped Readiness Matrix
新增 capability readiness：
- `coreFactoryE2EReady`
- `kdDfMReady`
- `commercialCostModelReady`
- `marketDemandVerified`
- `liveVisionReady`
- `liveVideoReady`
- `osSandboxReady`
- `liveMachineControlReady`
- `fullAutonomousFactoryReady`
每個 boolean 必須由明確 required checks 計算，不能手填。

## Phase 179 — `KD_FACTORY_REAL_ACCEPTANCE`
新增 `docs/KD_FACTORY_REAL_ACCEPTANCE.md` + JSON，至少 REAL 跑：
1. 3 個不同 KD SKU family。
2. quantity batch。
3. cross-SKU nesting。
4. waste V2 面積守恆。
5. reusable remnants 產生與再次消耗。
6. packaging carton + packed weight + assembly score。
7. landed cost + quote lineage。
8. 真 Blender product preview。
9. WAITING_PRODUCT_APPROVAL。
Mock demand/vision/video 必須分開列。

## Phase 180 — Small-Space SKU Candidate Catalog
產生第一批 20–30 個「學生/租屋/小宅」候選 SKU（不是自動投產），至少涵蓋桌、架、床邊、書櫃、電器架、衣架、收納、寵物/展示其中 6 類。每個候選必須帶：
- dimensions
- engineeringHash / BOMHash
- commonPartRatio
- sheetCount
- utilizationRatio
- trueWasteRatio
- reusableRemnantRatio
- carton L/W/H
- packedWeight
- assemblyDifficulty / estimatedMinutes
- landedCost / suggestedPrice
- demandDataConfidence
- Blender preview asset
- approvalState

依 deterministic DFM/commercial metrics 排 Top candidates；若 demand source 為 MOCK，不可宣稱「市場最熱銷」。

---

# 必須修正/加強的既有點

1. **Waste 語義**：目前 acceptance `util=0.641 / wasteM2=6.4123`，而現有 NestingEngine 把未使用板面全部視為 waste。Phase 141–145 必須拆出 reusable remnant vs true scrap，這是本輪最高優先。
2. **Readiness 語義**：不要再用一個模糊 `productionReady=true` 代表整套系統。改 scoped readiness；舊欄位若為相容保留，必須帶明確 `scope`。
3. **CI**：目前 commit 無 GitHub status checks。57 passed 可保留為 local evidence，但下一輪要補可見 unit/regression CI，若做不到就明確 BLOCKED。
4. Vision/AI Video 無 Provider 繼續 MOCK，不要為了升 REAL 偽造 adapter response。
5. OS sandbox 未完成就維持 PARTIAL。
6. Live CNC 維持 BLOCKED；本輪只做到 prototype/manufacturing candidate data。

# 驗收硬規則

- 不重寫現有 Scheduler / Queue / DAM / Recipe Registry / TwinStore / Parametric SoT。
- 不為 KD 另建第二套 mm source。
- 每個新增 product type 必須有 execution path，不准 enum-only。
- 所有成本都要有 confidence/source label：REAL_PROVIDER / CONFIG / ESTIMATED / MOCK。
- Waste 必須面積守恆，且 remnant 不可同時又算 waste 又算 inventory credit。
- Cross-SKU nesting 必須保留 SKU/version/part lineage。
- Remnant reservation/consumption 必須防止重複使用。
- 包裝尺寸必須由板件/packing logic 推導，不手填假值。
- Assembly score 必須 deterministic，可測試。
- Engineering Rule 永遠可以 veto Vision/Market score。
- 任何正式投產/採購/CNC 動作都保持 Human Approval。
- 缺外部 Provider 不阻擋 deterministic core；標 MOCK/PARTIAL/BLOCKED 後繼續。
- 不要為湊 Phase 數量建空殼。每個 Phase 都需 regression 或 acceptance evidence。

# 測試最低要求

新增測試至少覆蓋：
- 12 product types geometry+BOM。
- common-part fingerprint/hash stability。
- one-carton packing solver / oversize rejection。
- packed weight / CBM deterministic。
- assembly dependency acyclic / difficulty score。
- waste area conservation。
- remnant qualification/reservation/consume-once。
- batch single-SKU nesting。
- cross-SKU no-overlap/bounds/grain/lineage。
- remnant-first sheet savings case。
- quote stale after engineering/nesting/packaging changes。
- quantity break cost non-linear behavior。
- reverse remnant product feasibility。
- Product R&D engineering veto。
- readiness matrix truthful labels。

# 回報契約

完成後：
- 更新 `docs/GROK_PROGRESS_REPORT.md`。
- 更新 `docs/CURRENT_IMPLEMENTATION_AUDIT.md`。
- 新增 `docs/KD_FACTORY_REAL_ACCEPTANCE.md` + JSON。
- 若 readiness schema 改變，更新既有 REAL/FURNITURE/CABINET acceptance，保留歷史可理解性。
- 跑完整 pytest + lint/typecheck + 能跑的 integration/E2E。
- 明確報告 REAL / MOCK / PARTIAL / BLOCKED 與 data confidence。
- commit + push main。
- Issue #1 留 commit SHA、tests、REAL acceptance、blockers、下一輪建議。
- 不要求使用者手動搬運報告。

現在直接從 `4448ed3` 後開始，依依賴順序做 Phase 121–180。已 REAL 的 1–120 不重做，只在必要時 extension/refactor 且保持相容。