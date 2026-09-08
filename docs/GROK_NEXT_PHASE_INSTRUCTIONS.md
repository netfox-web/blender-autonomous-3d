# Grok 下一階段開發指令：Phase 181–240 — Physical Product OS / Multi-Material Factory

> Repo: `netfox-web/blender-autonomous-3d`
> Review baseline: `43cd4bda78c1b0189863bc46da1ceca79e761fb1`
> ChatGPT review result: **ACCEPT WITH SCOPE**
>
> `704d058` 的 10 項 exit criteria 已實質通過：runtime multipart、cross-OS traversal、remnant ownership、paired saved sheet evidence、8/8 REAL KD Blender previews、成本 readiness 誠實分層、local tests、GitHub Actions ubuntu+windows GREEN。現在可進 Phase 181+。
>
> 但仍禁止把 MOCK/CONFIG/PARTIAL 冒充 Production：Vision / AI Video / Demand 仍 MOCK；REAL_PROVIDER cost/logistics 未接；OS sandbox PARTIAL；AR runtime PARTIAL；LIVE_CNC / live machine control BLOCKED。

## 先做 2 個文件一致性修正（不另起架構）

1. `docs/KD_FACTORY_REAL_ACCEPTANCE.md` 的 `scoped readiness` evidence 字串仍殘留 `ciEvidenceReady=false`，但 header / JSON 已是 true。請同步成 head GitHub GREEN 證據，避免同一文件互相矛盾。
2. `docs/GROK_PROGRESS_REPORT.md` Blockers 的 `REAL_PROVIDER costs missing` 重複一行，清掉重複即可。

這兩項是文件 hygiene，不要重跑/重寫 Phase 1–180 已驗證功能。

---

# Phase 181–190 — Durable Material / Remnant Intelligence

## Phase 181 — RemnantStore abstraction
將現在 `RemnantInventory` 的 in-process dict 抽象成 `RemnantStore` interface；既有 in-memory 行為保留相容。禁止建立第二套 WMS。

## Phase 182 — Durable remnant persistence
沿用 repo 既有 `.fox3d-data` / persistence pattern，新增可重啟後恢復的 durable remnant store。若現有 persistence abstraction 可延伸則必須 reuse。記錄 tenantId、material、thickness、grain、w/h、sourceRun、status、reservedBy、version。

## Phase 183 — Optimistic version / lease
reserve / consume 必須帶 version 或 lease token，避免 stale consumer。至少測 stale token、double consume、cross-tenant、restart recovery。

## Phase 184 — Reservation TTL / recovery
reserved remnant 支援 TTL、expired lease recovery、worker crash recovery；不得讓永久 reserved 形成死庫存。

## Phase 185 — Material Lot lineage
板材新增 `materialLotId` / supplierLot / receivedAt / configCostSnapshot / sheet dimensions；所有 Nesting placement 可追到 material lot 或 remnant source。

## Phase 186 — Remnant quality state
加入 AVAILABLE / RESERVED / CONSUMED / QUARANTINED / DAMAGED。Damaged/Quarantined 不得進自動 nesting。

## Phase 187 — Grain/orientation on remnants
餘料要保留 grain orientation；旋轉後不符合 grain constraint 時不得使用。

## Phase 188 — Remnant valuation
建立 deterministic remnant value：area、shape usability、material config cost、age；明確標 `ESTIMATED/CONFIG`，不是會計成本。

## Phase 189 — Inventory reconciliation manifest
每次 production batch 產 inventory delta manifest：new sheets allocated、remnants created、reserved、consumed、true scrap、reconciliation hash。

## Phase 190 — Material/Remnant acceptance
建立 `docs/MATERIAL_REMNANT_REAL_ACCEPTANCE.md` + JSON：至少證明 restart recovery、ownership、TTL recovery、tenant isolation、grain、consume-once、inventory conservation。

---

# Phase 191–200 — Nesting Optimizer V3

## Phase 191 — Nesting Strategy Registry
保留 deterministic guillotine baseline，新增 strategy interface；不得把 baseline 刪掉。

## Phase 192 — Best-fit decreasing heuristic
實作第二個真 execution strategy；同一 BOM deterministic reproducible。

## Phase 193 — Multi-start deterministic search
用固定 seed / bounded search 產多個候選 layout，不需要 ML。限制 CPU time / candidate count。

## Phase 194 — Multi-objective scoring
至少同時考慮：new sheet count、true scrap、reusable remnant value、cut count、grain compatibility、material lot split。工程合法性 hard veto。

## Phase 195 — Cross-SKU production window
允許同材質/厚度的多 SKU、不同 quantity 在一個 production window 共同 nesting；placement lineage 保留 skuId/productVersion/bomLineId。

## Phase 196 — Cut sequence manifest
由合法 nesting 產 deterministic cut sequence / saw-friendly manifest；只做製程資料，不控制鋸台/CNC。

## Phase 197 — Defect keep-out zones
Sheet / remnant 可標 defect rectangles；nesting 不得把 panel 放進 defect zone。

## Phase 198 — Reusable-offcut objective
不只最低 scrap，也能在接近同等 sheet count 時優先留下「更好用的矩形餘料」。

## Phase 199 — Benchmark harness
同一批至少 10 組真實/fixture BOM 比較 guillotine baseline vs V3：sheetCount、trueWasteRatio、reusableRemnantRatio、cutCount、runtime。不得只挑 V3 贏的 case。

## Phase 200 — Nesting V3 acceptance
建立 `docs/NESTING_V3_ACCEPTANCE.md` + JSON。若 V3 某些 case 較差，要誠實展示；選擇器可回退 baseline。

---

# Phase 201–210 — KD Design-for-Assembly / Logistics Optimization

## Phase 201 — Connector recipe versioning
延伸現有 vendor-neutral connector recipes，加入 compatibility/version/requiredTools，不綁真供應商 SKU。

## Phase 202 — Common hardware optimizer
同一 SKU family 優先共用 connector/hardware，計 common-hardware ratio。

## Phase 203 — Common panel optimizer
在尺寸容許範圍內產候選，評估共用板件率；不得偷偷改使用者硬性尺寸。

## Phase 204 — Tool-count KPI
組裝工具種類與工具切換次數納入 assembly score。

## Phase 205 — Misassembly-risk rules
左右件相似、孔位方向、正反面辨識、對稱件等建立 deterministic risk warnings。

## Phase 206 — Part label manifest
每塊板件產 part label / QR payload metadata，包含 productVersion、partId、orientation、step refs；只產資料，不直接列印。

## Phase 207 — Assembly instruction V2
由 assembly graph 產 step-by-step manifest；每一步有 inputs、connectors、tools、before/after state、warning。

## Phase 208 — Carton contents manifest
紙箱內板件/五金/說明書 checklist，能對 BOM 做 reconciliation。

## Phase 209 — Auto redesign loop
若 oversize、true waste、assembly difficulty、tool count 超政策門檻，Variant Generator 可產受約束 redesign candidates；Engineering Rule 永遠 veto。

## Phase 210 — KD optimized candidate acceptance
至少 10 個小宅/KD candidates 比較 before/after：waste、carton、weight、common-part ratio、assembly score。禁止宣稱市場熱銷；Demand 仍 MOCK。

---

# Phase 211–220 — Retail Display / POP Fixture Factory

> 不另建第二套 Digital Twin / Parametric / Nesting。延伸既有 `RETAIL_DISPLAY` 與 Physical Product definitions。

## Phase 211 — Retail fixture family registry
至少：COUNTER_DISPLAY、FLOOR_DISPLAY、PDQ_DISPLAY、RISER_DISPLAY、PEGBOARD_DISPLAY、ENDCAP_MODULE。

## Phase 212 — Product facing / slot definition
輸入商品 Digital Twin 尺寸、facing count、rows/columns、clearance，產 slot layout。

## Phase 213 — Planogram solver
依展示架可用寬高與商品尺寸產合法 planogram candidates；不得重疊或超界。

## Phase 214 — Capacity / load placeholder rules
計算商品數量與估算總重；沒有真結構分析時只能標 `CONFIG_ESTIMATE/PARTIAL`，不得宣稱結構認證。

## Phase 215 — Artwork zones
fixture 定義 printable artwork zones / logo zones / safe areas；只做 geometry metadata，不冒充印刷 preflight 完成。

## Phase 216 — Lighting / cable optional metadata
可描述燈條/走線預留，但 electrical compliance 一律 BLOCKED/PARTIAL，除非未來有真工程規則。

## Phase 217 — Same BOM/Nesting/Cost path
Retail fixture 必須走現有 BOM → Nesting V3 → Waste → Remnant → Cost → Packing → Approval；禁止專用旁路。

## Phase 218 — REAL Blender fixture previews
至少 6 種 fixture 走 REAL Blender 5.2.1 / OptiX low-res preview；每種記 engineeringHash、bomHash、jobId、artifact hash/size、usedMock=false。

## Phase 219 — Retail fixture packing
KD display 拆箱尺寸、重量、CBM、assembly manifest；logistics cost 仍 CONFIG。

## Phase 220 — Retail fixture acceptance
建立 `docs/RETAIL_FIXTURE_REAL_ACCEPTANCE.md` + JSON：商品尺寸 → planogram → fixture → BOM → nesting → packing → REAL Blender → WAITING_APPROVAL。

---

# Phase 221–230 — Structural Packaging / Dieline V1

> 既有 Packaging Digital Twin 必須 reuse；這輪是在同一 Twin/Engineering 架構增加「可計算結構」，不是第二套 packaging system。

## Phase 221 — PackagingEngineeringDefinition
加入 structural packaging engineering wrapper，保持 Product Digital Twin 相容。

## Phase 222 — Box families
至少 RSC_CARTON、MAILER_BOX、SLEEVE、TRAY、PDQ_TRAY 五種 parametric family。

## Phase 223 — Product fit rules
由商品 dimensions + clearance 產 inner dimensions / outer dimensions；不得把 artwork 當結構尺寸來源。

## Phase 224 — Dieline primitives
建立 cut / crease / perforation / glue zones 幾何語意，輸出 SVG/DXF-friendly manifest。

## Phase 225 — Bleed / safe area metadata
Artwork zones 加 bleed/safe-area metadata；真正印前 trapping/color/preflight 未接時標 PARTIAL。

## Phase 226 — Paperboard / corrugated sheet registry
建立 sheet size、caliper、grain/flute direction、CONFIG cost。ECT/BCT/壓縮強度沒有真模型時不得宣稱 REAL structural certification。

## Phase 227 — Packaging nesting
將 dielines 做 sheet nesting，沿用 Waste V2 概念：used / trim / reusable remainder / true scrap；若演算法與木板 nesting 不同，用 adapter/strategy，不建第二個 Scheduler/DAM。

## Phase 228 — Fold preview
Blender 自動產 flat → folded box preview / simple assembly animation；REAL artifact 才標 REAL。

## Phase 229 — Packaging + Retail bundle
同一商品 Digital Twin 可一次產 consumer package + PDQ + retail fixture proposal，保留 lineage。

## Phase 230 — Packaging structure acceptance
建立 `docs/PACKAGING_STRUCTURE_REAL_ACCEPTANCE.md` + JSON：商品尺寸 → box definition → dieline → nesting/waste → Blender fold preview。強度/印前仍需誠實 scope。

---

# Phase 231–235 — Acrylic / Sheet Product Extension

## Phase 231 — Acrylic sheet material registry
透明/乳白/黑等材料 code、thickness、sheet size、CONFIG cost、grain=none；不要假裝供應商即時價格。

## Phase 232 — Acrylic product families
至少 MENU_STAND、SIGN_HOLDER、RISER_STAND、DISPLAY_BOX、PRODUCT_STAND。

## Phase 233 — Acrylic sheet nesting
沿用 Nesting Strategy Registry / Waste V2 / remnant semantics；材質厚度必須相容。

## Phase 234 — Cut/Bend manifest boundary
可產 laser/CNC cut geometry interface 與 bend line manifest；bend radius / heat parameters 若只是 config，標 CONFIG/PARTIAL；LIVE LASER/CNC 永遠 BLOCKED。

## Phase 235 — Acrylic REAL previews
至少 3 種 product REAL Blender preview + BOM + nesting + packing evidence。

---

# Phase 236–240 — Unified AI Physical Product OS V1

## Phase 236 — PhysicalProductFamily Registry
建立上層 registry 統一 furniture/KD/retail fixture/packaging/acrylic capabilities，但底層仍 reuse 現有 Twin/Queue/DAM/Engineering adapters。不得重寫既有 CabinetSpec；以 adapter/typed definition 漸進抽象。

## Phase 237 — Inventory-to-Product reverse R&D
輸入可用 new sheets + remnants + material lots，產可製造 product candidates。分數至少含：material utilization、true scrap、remnant consumption、common parts、packing、assembly、estimated margin。Market demand 未有 REAL Provider 時明確 MARKET_UNVERIFIED。

## Phase 238 — Unified Admin/API
沿用現有 Admin/API 增加：Materials、Remnants、Nesting Benchmarks、KD Candidates、Retail Fixtures、Packaging Structures、Acrylic Products、Approval。不得另開第二個平台。

## Phase 239 — PHYSICAL_PRODUCT_OS_REAL_ACCEPTANCE
建立 `docs/PHYSICAL_PRODUCT_OS_REAL_ACCEPTANCE.md` + JSON，至少證明三條 REAL E2E：
1. KD furniture → BOM/Nesting/Waste/Packing/Blender
2. Retail display → Product slots/Planogram/BOM/Nesting/Blender
3. Packaging or acrylic → Engineering/Dieline-or-Cut/Nesting/Blender
全部停在 Human Approval / prototype boundary。

## Phase 240 — Full regression / readiness matrix
跑完整 local pytest + GitHub Actions ubuntu/windows。Readiness 必須逐項：REAL / ESTIMATED-CONFIG / MOCK / PARTIAL / BLOCKED。`fullAutonomousFactoryReady` 除非 Vision/Demand/ProviderCost/OS sandbox/machine boundaries 全部真的打通，否則保持 false。

---

# 本輪不可違反規則

1. 不重寫既有 Scheduler / Queue / DAM / Recipe Registry / TwinStore / Cabinet Engineering SoT。
2. 新產品族優先 adapter / registry / typed definition，禁止每種產品各自一套平台。
3. 所有 dimensions / BOM / nesting / packing 必須有 lineage/hash；不要靠 Blender scene 反推正式工程尺寸。
4. Mock pytest 只代表 regression，不是 Production Ready。
5. REAL Blender 必須實際 artifact + usedMock=false。
6. CONFIG/ESTIMATED cost 不得叫 REAL supplier/commercial quote。
7. Demand / Vision / Video 沒 live provider 就維持 MOCK。
8. OS sandbox 沒 OS jail 就維持 PARTIAL。
9. CNC / saw / laser / print machine live control 一律 BLOCKED；Human Approval Gate 保留。
10. Packaging strength/electrical/structural certifications 沒真工程模型就標 PARTIAL/BLOCKED。
11. 每個 Phase 要有 execution path 或 regression evidence；禁止空 class/schema 湊 Phase 數量。
12. 所有新的 durable inventory 路徑要 tenant isolation + crash/restart tests。
13. GitHub Actions 必須真的 GREEN 才可寫 CI ready；不要預測 PASS。

# 回報契約

完成後：
- 更新 `docs/GROK_PROGRESS_REPORT.md`。
- 更新 `docs/CURRENT_IMPLEMENTATION_AUDIT.md`。
- 依各段建立上述 REAL acceptance docs + JSON evidence。
- 更新 `docs/REAL_E2E_ACCEPTANCE.md` 只做 scope/readiness 同步，不破壞舊 REAL 證據。
- commit + push main。
- GitHub Issue #1 留：commit SHA、local pytest、GitHub Actions run、REAL/MOCK/PARTIAL/BLOCKED 摘要、blockers、下一輪建議。
- 不要求使用者複製貼上；ChatGPT 直接從 GitHub 接手。

**現在直接從 Phase 181 開始，先修兩個文件一致性問題，再依依賴順序實作。已 REAL 的 Phase 1–180 不重做。**