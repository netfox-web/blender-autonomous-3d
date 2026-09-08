# Grok 下一階段開發指令：Phase 241–300 — Commercialization Hardening / Physical Product OS V2

> Repo: `netfox-web/blender-autonomous-3d`
> Review baseline: `f2f9eeca35077829a951d36a5336ce880f36a337`
> ChatGPT review result: **ACCEPT WITH SCOPE**
>
> Phase 181–240 有實質完成，可進下一輪。GitHub Actions `34252520536` 在 code commit `5d8c533` 為 SUCCESS（ubuntu + windows），current head `f2f9eec` 亦有 SUCCESS run `34252652466`。Local pytest 回報 89 passed，但仍只是 MOCK-Blender regression suite，不得當 REAL production evidence。
>
> REAL scope 可接受：durable remnant restart/TTL/tenant isolation、Nesting V3 baseline fallback + 10-case harness、KD DFA manifests、Retail 6/6 REAL T1000 OptiX previews、Packaging dieline + REAL fold preview、Acrylic 3/3 REAL previews、Human Approval Gate。
>
> Truth labels保持：cost/logistics/remnant valuation = ESTIMATED/CONFIG；Vision / AI Video / Demand = MOCK；OS sandbox / AR / packaging strength / print preflight = PARTIAL；LIVE_CNC / LIVE_LASER / electrical compliance = BLOCKED；`fullAutonomousFactoryReady=false`。

## 開工前先修 3 個 Truth / Evidence hygiene 問題

1. `docs/REAL_E2E_ACCEPTANCE.md` 頂部仍有未限定 scope 的 `productionReady: True`。改成 scoped readiness，例如 `coreRenderE2EReady=true`、`physicalProductOsPrototypeReady=true`、`globalProductionReady=false`，並明寫 scope；禁止讓讀者誤解整套 OS 已 Production Ready。
2. `docs/CURRENT_IMPLEMENTATION_AUDIT.md` Phase 68 仍寫 depth/normal/segmentation 未產，但後續 Phase 71–120 已有 REAL AOV evidence。同步 audit，保留當時歷史但 current status 要一致。
3. `MATERIAL_REMNANT_REAL_ACCEPTANCE.md`、`NESTING_V3_ACCEPTANCE.md` 等目前大量複製 Physical OS 共用表格。保留 summary 可以，但每份 domain acceptance 必須增加「本領域專屬、可機器驗證」evidence，避免用 unrelated retail/packaging rows 充數。

以上只做文件 truth cleanup，不重寫 Phase 1–240。

---

# Phase 241–250 — Evidence Integrity / Release Gates / Sandbox Boundary

## Phase 241 — Scoped Readiness Model
建立單一 readiness model，至少分：
- coreRenderE2EReady
- kdPrototypeReady
- retailPrototypeReady
- packagingPrototypeReady
- acrylicPrototypeReady
- commercialPricingReady
- liveProviderReady
- machineControlReady
- fullAutonomousFactoryReady

任何子系統 MOCK/PARTIAL 不得被一個全域 `productionReady=true` 蓋掉。

## Phase 242 — EvidenceBundle
所有 REAL acceptance 建立 immutable `EvidenceBundle`：commitSha、generatedAt、jobId、workerId、GPU UUID/name、Blender version、usedMock、artifactId/path、artifactHash、artifactSize、engineeringHash、bomHash、recipeVersion。

## Phase 243 — Acceptance Verifier
建立可執行 verifier，逐一檢查 EvidenceBundle 引用 artifact 真存在、hash/size 一致、`usedMock=false`、lineage hash 可追。驗證失敗時 acceptance 必須 FAIL，不能只靠 Markdown 文字。

## Phase 244 — Truth Label Validator
建立 regression，掃 readiness / acceptance machine-readable JSON，禁止：
- MOCK source 標 REAL
- CONFIG/ESTIMATED price 標 REAL_PROVIDER
- BLOCKED machine control 標 ready
- `fullAutonomousFactoryReady=true` while blockers remain

## Phase 245 — Approval Audit Trail
Human Approval Gate 加 immutable audit event：actor、entityVersion、engineeringHash、evidenceHash、approvedAt、decision、reason。

## Phase 246 — Approval Staleness
任何 engineering/BOM/nesting/cost/packaging hash 改變，既有 approval 自動 stale；不可沿用舊批准。

## Phase 247 — ReleaseCandidate State Machine
新增但沿用既有 approval flow：`PROTOTYPE → ENGINEERING_VALID → EVIDENCE_VERIFIED → WAITING_APPROVAL → APPROVED_FOR_EXPORT`。`APPROVED_FOR_EXPORT` 仍不等於 LIVE_CNC/LASER。

## Phase 248 — Script Sandbox Backend Interface
沿用現有 path guard，抽象 `SandboxBackend`。至少支援 `PATH_GUARD_ONLY` 與未來 `CONTAINER/JOB_OBJECT` backend；未有真正 OS jail 時 status 仍 PARTIAL。

## Phase 249 — No-network / resource policy manifest
AI-generated Blender/Python job 明確產 policy manifest：filesystem allowlist、networkAllowed=false、CPU/memory/time limits、env allowlist。若 host 無法 enforce，標 PARTIAL/BLOCKED，不得假裝 enforce。

## Phase 250 — Release Gate Acceptance
建立 `docs/RELEASE_GATE_REAL_ACCEPTANCE.md` + JSON，證明 Evidence verifier、approval stale、cross-tenant、forbidden live-machine transition、truth-label regression。

---

# Phase 251–260 — Supplier Cost / Material / Logistics Provider Gateway

> 不另建 ERP/WMS。只做 adapter/provider gateway，讓未來公司既有 ERP/WMS/供應商資料可接入。

## Phase 251 — Provider Registry
建立 SupplierPriceProvider / HardwarePriceProvider / PackagingPriceProvider / LogisticsRateProvider / FxRateProvider interfaces，沿用現有 ProviderAdapter pattern。

## Phase 252 — Material Price Snapshot Import
支援 CSV/JSON/manual import：supplier、materialCode、thickness、sheetSize、currency、UOM、price、effectiveAt、expiresAt、sourceRef。Import execution 可 REAL，但資料來源若是 fixture/manual 要標 IMPORTED/MANUAL，不是 LIVE_PROVIDER。

## Phase 253 — Hardware Price Snapshot
vendor-neutral hardware ID 對應 supplier SKU/price/pack quantity/effective date；Engineering 仍只依 vendor-neutral ID。

## Phase 254 — Packaging Material Price Snapshot
paperboard/corrugated/acrylic/packing materials 同樣 versioned snapshot；不覆蓋 Engineering material definition。

## Phase 255 — Logistics Tariff Snapshot
支援 zone、weight、CBM、longest-side、oversize surcharge、base fee、effective date；可由匯入資料計算，不需要外部 API 才能運作。

## Phase 256 — FX Snapshot
成本跨幣別要綁 rate snapshot + source label。沒有 live provider 時允許 IMPORTED/MANUAL，但 `liveFxProviderReady=false`。

## Phase 257 — Mixed-source Landed Cost
每個 cost component 帶 source label：REAL_IMPORTED / MANUAL / CONFIG_ESTIMATE / LIVE_PROVIDER。總成本不可只給單一模糊 REAL 標籤。

## Phase 258 — Quote Validity / Stale Rules
報價綁 engineeringHash、bomHash、nestingHash、providerSnapshotIds、effective window。任一上游改變或過期即 stale。

## Phase 259 — Supplier Alternative Candidates
同工程材料規格下比較 supplier/material alternatives；禁止自動替換不相容厚度/材質。Rule Engine hard veto。

## Phase 260 — Provider/Cost Acceptance
建立 `docs/COMMERCIAL_COST_ACCEPTANCE.md` + JSON；明確區分 imported data execution REAL vs live provider connectivity。沒有真 credential 時 `liveProviderReady=false`。

---

# Phase 261–270 — Packaging Engineering V2 / Print Preflight

## Phase 261 — Board Grade Registry
Paperboard / corrugated 加 caliper、flute、ECT input、basis weight、grain/flute direction、source label。

## Phase 262 — Box Compression Estimate
若參數足夠可實作 deterministic engineering estimate（例如基於可追溯公式/參數），輸出 assumptions / safety factor / source；沒有實驗室測試不得標 certification。

## Phase 263 — Shipping Load Scenario
疊箱數、產品重量、storage/transport config 產 load scenarios；label=`ENGINEERING_ESTIMATE`。

## Phase 264 — Dieline Geometry Validator
檢查 cut/crease/perf/glue zone：self-intersection、非法 overlap、過短 flap、panel bounds、fold consistency。

## Phase 265 — Bleed / Safe-area Validator
依 packaging artwork zone 驗證 bleed/safe area metadata。不要宣稱完整印刷廠 preflight。

## Phase 266 — Artwork Asset Preflight
對 PDF/image artwork 做可取得的客觀檢查：page/artboard size、pixel dimensions、DPI estimate、color-space metadata、missing asset/font reference（能檢查才報）。不可憑猜測 PASS。

## Phase 267 — Barcode/Label Zone
建立 barcode/label placement keep-out/quiet-zone metadata；若未接正式條碼驗證器，標 PARTIAL。

## Phase 268 — Package/Product Fit Regression
至少 20 組產品尺寸/箱型做 fit/clearance/fold regression，包含 impossible cases。

## Phase 269 — Carton Optimization
在工程合法前提下比較 box family、board area、waste、shipping CBM、estimated compression margin；Engineering veto 優先。

## Phase 270 — Packaging V2 Acceptance
新增 `docs/PACKAGING_V2_ACCEPTANCE.md` + JSON；strength 仍只能 ESTIMATE/PARTIAL，除非真測試資料存在。

---

# Phase 271–280 — Product Safety / DFM Risk Engine

> 這輪建立工程風險檢查，不宣稱法規認證。

## Phase 271 — SafetyRule Registry
家具/KD/retail/acrylic/packaging 共用 rule registry，規則帶 scope、severity、assumption、version。

## Phase 272 — Furniture Stability Estimate
建立重心/底面/傾倒風險的 deterministic approximate check；輸出 `ENGINEERING_ESTIMATE`，不是實驗室防傾倒認證。

## Phase 273 — Wall-anchor / Tall-product Warnings
高窄家具依 configurable policy 產 wall-anchor warning / approval requirement。

## Phase 274 — Pinch / Sweep / Sharp-edge Zones
延伸門片/抽屜 opening sweep，加入 pinch zone、可接觸銳邊/角 metadata。

## Phase 275 — Shelf/Panel Load Assumptions
由 span、material config、thickness 產 conservative load warning；無結構分析資料時 PARTIAL/ESTIMATE。

## Phase 276 — Retail Fixture Stability / Load
商品 planogram 總重、重心高度、base footprint 做 risk score；electrical compliance 保持 BLOCKED。

## Phase 277 — Acrylic Risk Rules
厚度、unsupported span、bend line proximity、edge exposure、heat-bend config 產 warnings；LIVE LASER 仍 BLOCKED。

## Phase 278 — Assembly Safety Instructions
Assembly V2 加工具、pinch、orientation、two-person-lift、wall-anchor warnings，來源可追。

## Phase 279 — Compliance Boundary Manifest
每個候選輸出：checkedRules / assumptions / unresolved / certificationRequired / notCertified=true。

## Phase 280 — Safety Acceptance
至少 KD 10 cases + retail 6 families + acrylic 3 products regression；包含應被 veto 的危險案例。

---

# Phase 281–290 — Commerce / Web3D / Asset Publication Package

## Phase 281 — ProductPublicationPackage
同一 ProductVersion 產可發布 bundle：spec JSON、BOM summary、packing summary、preview assets、360、3D references、assembly instructions、warnings。

## Phase 282 — GLB Publication Export
沿用 Digital Twin/DAM，建立 final GLB export + hash + dimensions validation，不另建 asset store。

## Phase 283 — Web 360 Package
統一 36-frame/manifest/thumb metadata，保留 recipe/worker lineage。

## Phase 284 — Web3D Manifest
產 viewer-neutral manifest：GLB URL/ref、camera bounds、units、dimensions、materials、variant IDs。AR runtime 若只是 manifest 仍 PARTIAL。

## Phase 285 — AR Export Boundary
若本機可真產 USDZ/AR artifact 才標 REAL；否則只做 adapter + BLOCKED/PARTIAL，不得假產檔名。

## Phase 286 — E-commerce Image Recipe Pack
由同一 Twin 產 WHITE_STUDIO、detail、scale-reference、dimension overlay reference、material close-up 等 recipe manifests；真 render 才 REAL。

## Phase 287 — Assembly Instruction Asset Pack
Part labels + step manifests + exploded images/MP4 統一成 publication asset set。

## Phase 288 — Packaging Artwork Template Export
Dieline + artwork zones + bleed/safe metadata產可供設計軟體使用的 SVG/DXF-friendly package，保持工程 hash。

## Phase 289 — SKU Family Catalog Builder
將 KD / retail / packaging / acrylic variants 編成 immutable catalog release，支援 superseded/stale 狀態。

## Phase 290 — Publication Acceptance
至少選 5 個不同 family 產完整 ProductPublicationPackage，驗證所有 artifact lineage/hash。

---

# Phase 291–300 — Closed-loop Product R&D / External Intelligence Boundary

## Phase 291 — OutcomeFeedback Schema
建立可匯入的 sales/traffic/margin/return/customer-feedback outcome schema；不另建 CRM/ERP。

## Phase 292 — DemandSignal Provider Registry V2
支援 LIVE_PROVIDER / IMPORTED / MANUAL / MOCK / UNAVAILABLE label。沒有真 provider 時保持 MARKET_UNVERIFIED。

## Phase 293 — Outcome Import
支援 CSV/JSON 匯入 SKU outcome，綁 productVersion/timeWindow/source；fixture data 不得標 real market data。

## Phase 294 — Experiment Lineage
Recipe/variant experiment 綁 productVersion、publication release、outcome window，避免把不同版本成效混在一起。

## Phase 295 — Evidence-weighted Ranking
只有有真 outcome source 時才能加入 market score；沒有時 ranking 明確標 engineering/material-only。

## Phase 296 — Inventory-to-Product R&D V2
將 remnants/material lots/common hardware/packing/logistics/safety/estimated margin 一起評分；Demand 不可偽造。

## Phase 297 — Material Shortage/Substitution Candidates
缺料時產 compatible alternatives + cost/waste impact；任何工程材料變更都建立新 immutable version並重新 approval。

## Phase 298 — Autonomous Research Queue
沿用現有 Queue/Scheduler，在 GPU idle/低優先級條件下產 experimental previews；Agent 不能直接改 PRODUCTION recipe/catalog。

## Phase 299 — Physical Product OS KPI Read Model
沿用現有 Admin，顯示：true scrap、remnant reuse、sheet savings、packing CBM、assembly difficulty、estimated vs provider cost coverage、approval stale、REAL/MOCK/PARTIAL/BLOCKED counts。

## Phase 300 — PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE
建立 `docs/PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.md` + JSON，至少驗證：
1. KD → engineering → nesting/remnant → provider-sourced/estimated cost split → safety → Blender/publication → approval gate
2. Retail → planogram/load-risk → nesting → Blender/publication → approval
3. Packaging → fit/dieline/preflight/strength-estimate → nesting → fold preview → publication
4. Acrylic → engineering/nesting/risk → Blender/publication
5. EvidenceBundle verifier + stale approval + tenant isolation

最後跑完整 pytest + GitHub Actions ubuntu/windows。Readiness 必須逐項 REAL / IMPORTED / MANUAL / CONFIG_ESTIMATE / MOCK / PARTIAL / BLOCKED。

`fullAutonomousFactoryReady` 只有在 Vision/Demand/live Provider/OS sandbox/machine boundaries 真正符合定義後才可 true；本輪預期仍為 false。

---

# 本輪不可違反規則

1. 不重寫 Scheduler / Queue / DAM / Recipe Registry / TwinStore / Cabinet Engineering SoT。
2. 不建立第二套 ERP/WMS/CRM；外部資料一律 adapter/import/provider boundary。
3. Mock pytest 是 regression，不是 Production Ready。
4. REAL Blender 必須真 artifact、hash、usedMock=false。
5. Imported/manual/config price 必須清楚標 source，不得冒充 LIVE_PROVIDER。
6. Engineering estimate 不得冒充法規/結構/電氣認證。
7. LIVE_CNC / LIVE_LASER 一律保持 BLOCKED，除非未來另有明確安全旨令；Human Approval Gate 不可移除。
8. AI-generated Python 若無真正 OS jail，sandbox 只能 PARTIAL。
9. 每個 Phase 要有 execution path + regression/evidence，不要空 schema/UI。
10. 若某外部 provider/工具/credential 不存在，標 BLOCKED/MOCK/PARTIAL 後繼續其他可完成項，不得造假。

## 回報契約

完成後：
- 更新 `docs/GROK_PROGRESS_REPORT.md`、`docs/CURRENT_IMPLEMENTATION_AUDIT.md`、readiness matrix。
- 新增本輪 acceptance docs + machine-readable JSON。
- 報 local pytest 結果與 GitHub Actions run ID / exact commit SHA。
- REAL Blender evidence 要列 worker/GPU/Blender/job/artifact/hash/usedMock。
- 明列哪些 provider 是 LIVE / IMPORTED / MANUAL / CONFIG / MOCK。
- 明列 PARTIAL/BLOCKED 與原因。
- commit + push `main`。
- Issue #1 留 code SHA、CI、REAL evidence、blockers、下一輪建議。
- 不要求使用者 copy/paste；ChatGPT 直接從 GitHub 接手。

現在直接從 `f2f9eec` 後的 repo state 開始。先做 truth/evidence hygiene，再依依賴順序完成 Phase 241–300。