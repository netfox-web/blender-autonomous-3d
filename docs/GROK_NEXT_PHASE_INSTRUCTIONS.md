# Grok 下一階段開發指令：Phase 71–120 Autonomous Furniture Factory

> Repo: `netfox-web/blender-autonomous-3d`
> 基線：先讀 `docs/GROK_PROGRESS_REPORT.md`、REAL/CABINET acceptance 與現有 `src/fox3d/`。
> 不重做 Phase 1–70。優先填 REAL gaps；無真外部 Provider/設備時必須標 MOCK/PARTIAL/BLOCKED。

## 本輪目標
把目前單一 STORAGE_CABINET 能力擴成可持續演進的「空間 → 多櫃設計 → 工程 → BOM/成本 → Blender → 製造候選」家具自動研發工廠。Engineering Definition 仍是尺寸唯一 Source of Truth；Blender 只是 consumer；正式 CNC/投產仍需 Human Approval。

## Phase 71–80：家具產品族與組合工程
71. 建立 FurnitureProductType Registry：WARDROBE、SHOE_CABINET、TV_CABINET、BOOKCASE、STORAGE_CABINET、DISPLAY_CABINET、KITCHEN_BASE、KITCHEN_WALL。
72. 將 CabinetSpec 泛化但保持舊 API 相容，不複製第二套 parametric engine。
73. 建立 CabinetModule：單一櫃可由多 module 組成。
74. 支援 vertical partition / horizontal partition。
75. 支援 open shelf / closed compartment。
76. 支援 hinged door / double door / drawer bank / open bay。
77. 支援 toe-kick / legs / plinth。
78. 支援 top filler / side filler / wall clearance。
79. 建立 MultiCabinetAssembly，同一牆面可組合多櫃。
80. 建立 Assembly Engineering Hash；任一 module 改變必須造成 hash/BOM/render lineage 改變。

## Phase 81–90：空間 Digital Twin / 自動配置
81. 建立 SpaceDigitalTwin schema：room/wall/opening/obstacle/outlet metadata。
82. 支援手動尺寸 JSON 建立房間，不要求 AI 才能工作。
83. Wall segment：length/height/thickness/origin/direction。
84. Door/window opening + keep-out zone。
85. Column/beam/skirting/outlet keep-out zone。
86. 建立 Space Constraint Engine，櫃體不可穿牆、門窗、柱與保留區。
87. 建立 WallFitSolver：依可用牆寬自動配置單櫃/多櫃。
88. 支援 fixed gap / minimum clearance / symmetric layout。
89. 自動產 3–10 個合法 layout candidates。
90. Blender Space Preview：牆、地板、開口、櫃體一起 render；空間資料與家具資料 lineage 分開記錄。

## Phase 91–100：工程規則、五金、製造資料
91. Rule Engine 加強門片 opening sweep collision。
92. Drawer extension collision。
93. Shelf span / load placeholder rule（未有真結構模型時不得宣稱結構認證）。
94. Hardware Registry：hinge/rail/handle/connector/leg，以 vendor-neutral ID 為主。
95. Hardware compatibility rule：門厚、抽屜、開啟角等。
96. Edge banding 明確到每一板件邊，不只 boolean。
97. DrillingManifest schema：孔位、直徑、深度、面、座標系。
98. CuttingManifest schema：panel、尺寸、grain direction、quantity。
99. ManufacturingManifest version/hash/approval state。
100. Manufacturing Candidate Gate：ENGINEERING_VALID → COSTED → PREVIEWED → WAITING_APPROVAL；不得自動 LIVE_CNC。

## Phase 101–110：板材、Nesting、成本與報價
101. SheetMaterial Registry：板長/板寬/厚度/紋理方向/成本。
102. BOM → required panel rectangles。
103. 實作 deterministic 2D nesting baseline（例如 shelf/guillotine heuristic），不是只定義 Adapter。
104. 計算 sheet count / utilization / waste area。
105. Grain-direction constraint。
106. Kerf / trim allowance parameters。
107. Nesting result manifest + SVG/DXF-friendly geometry interface。
108. Cost Engine 加入 sheet waste、edge banding length、hardware、drilling/cutting processing。
109. Quote Engine：cost + margin policy → suggested price；不得接真金流。
110. Quote version 綁 EngineeringHash + BOMHash + NestingHash，工程改動必須使舊報價 stale。

## Phase 111–120：自助設計、AI R&D、真實驗收
111. Natural Language 支援產品族，例如衣櫃/鞋櫃/電視櫃/展示櫃，不讓 LLM 直接製造 mm。
112. DesignIntent 加 room/wall target、用途、風格、預算、storage requirements。
113. Intent → deterministic normalized constraints；不明確資料標 UNKNOWN/NEEDS_INPUT，不幻想。
114. Variant Generator 同時變 layout/module/material/door/drawer，但先 Engineering Validate。
115. Vision Judge 接 Provider interface；若沒有真 Provider 保持 MOCK，禁止假 REAL。
116. Vision 分數與 Engineering score 分離；工程 Rule 永遠有 veto。
117. ProductRDAgent 支援 Space → Layout → Furniture Variants → BOM → Nesting → Cost → Preview → Candidate。
118. 建立 Customer Revision：改寬度/材質/層板/門片後建立新 immutable version，保留 lineage。
119. 建立 Furniture Factory Admin/API：Space Twins、Assemblies、BOM、Nesting、Quotes、Approval；沿用現有 Admin，不另建平台。
120. 建立 `docs/FURNITURE_FACTORY_REAL_ACCEPTANCE.md` + JSON evidence，跑完整 E2E：3600mm wall → 多櫃合法配置 → BOM → nesting → cost/quote → real Blender preview → WAITING_APPROVAL。

## 同輪必須補既有 PARTIAL/MOCK gaps（不另算空 Phase）
- Assembly animation MP4：若可在本機 Blender 真跑，完成 REAL；否則留下具體 blocker。
- Cycles AOV：depth / normal / segmentation，能真產 artifact 才標 REAL。
- Vision Judge：只有真正 Provider 呼叫才可 REAL。
- AI Video：只有 FoxStudio ProviderAdapter 真註冊/呼叫才可 REAL；不可硬綁 H3/LTX。
- OS sandbox：不得因 path guard 就宣稱完整 OS jail。
- `feature/admin-console` 若存在，先比較差異，只合併不衝突且有價值部分。

## 測試與驗收硬規則
1. 不重寫 Scheduler / Queue / DAM / Recipe Registry / TwinStore。
2. 不建立第二套家具尺寸來源。
3. Blender 不得自行修正工程 mm 後不回寫 Engineering Definition。
4. Mock 測試與 Real acceptance 分開。
5. 每一新 product type 至少有 geometry+BOM regression。
6. MultiCabinet 至少測 2、3、4 module/cabinet 組合。
7. Space solver 至少測 door/window/column collision rejection。
8. Nesting 至少測 deterministic、no-overlap、sheet bounds、grain constraint。
9. Quote stale detection 必測。
10. Production manufacturing 一律 Human Approval Gate。
11. 缺外部 Provider 不阻止其餘 Phase，標 MOCK/PARTIAL 後繼續。
12. 不要為了湊 50 Phase 建空 class/schema；每個 Phase 要有 execution path 或 regression evidence。

## 回報契約
完成後：
- 更新 `docs/GROK_PROGRESS_REPORT.md`。
- 新增/更新 `docs/FURNITURE_FACTORY_REAL_ACCEPTANCE.md` 與 machine-readable JSON evidence。
- 更新 CURRENT_IMPLEMENTATION_AUDIT / REAL_E2E / CABINET acceptance（若狀態改變）。
- 跑完整 pytest + 現有 lint/typecheck/integration/E2E。
- 報告 REAL / MOCK / PARTIAL / BLOCKED。
- commit + push main。
- GitHub Issue #1 留 commit SHA、測試數、REAL blockers、下一輪建議。
- 不要求使用者複製貼上；ChatGPT 直接從 GitHub 接手。

## 下一輪規劃原則
若本輪無重大 blocker，下一輪建議 Phase 121–180，方向為：家具商品化/AR/Web3D、包裝與展示架 Parametric Product、零售/展場 Scene、AI Video 真 Provider、Synthetic Data AOV、Render Farm、多 GPU Scheduler、Recipe 自動研究與品質資料閉環。

現在直接開始。先讀現有實作與 Progress Report，已 REAL 的不要重做；依依賴順序完成 71–120。