# Grok 開發指令：Phase 781–840 — Artwork Placement / Surface Decoration Engine V1 — ACCEPT WITH SCOPE / GO

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `0be2da49e92f539dcad886380982aebc3a633a78`  
> Accepted Phase 721–780 CODE_EVIDENCE_SHA: `12ef5462711604971cb4e5beaad63119376d996d`  
> Accepted canonical generation: `4c1fa7ed-57d2-45bf-b3d1-ecf70e3efb53`  
> Re-Gate result: **ACCEPT WITH SCOPE — Phase 721–780 evidence chain is complete; Phase 781–840 may start.**  
> 下一主線：**Artwork Placement / Surface Decoration Engine V1**。沿用既有 Engineering Definition + Blender + DAM + publish/evidence 能力，不建立第二套產品工程或素材系統。

## Phase 721–780 Re-Gate 結論 — 已接受，禁止退步

以下 evidence 已完成並重新核對：

- `pytest -q`：**567 passed**。
- exact CODE Actions `34481806339` on `12ef5462711604971cb4e5beaad63119376d996d`：Ubuntu **SUCCESS** / Windows **SUCCESS**。
- runner-bound evidence docs `9a58803067ace0e69638739dcad0430e0dfb60cb`：Actions `34483517716` Ubuntu/Windows **SUCCESS**。
- current docs/head `0be2da49e92f539dcad886380982aebc3a633a78`：Actions `34485140483` Ubuntu/Windows **SUCCESS**。
- canonical JSON 是 runner 實際重新產生，不是只改字串：new generation `4c1fa7ed-57d2-45bf-b3d1-ecf70e3efb53`、new batch IDs、tenant digest `889866450a2141b0e1201598478d3aaab3406449d60f59d5c87e934f747f2213`。
- `evidenceCodeCommit=12ef5462711604971cb4e5beaad63119376d996d`、`workingTreeClean=true`、`evidenceCommitMatchesHead=true`。
- 4 batches × 5 units / 20 execution units；canonical exact-set authority、BOM/checklist authority、WorkOrder owner、FINAL QC、decision、cost lineage、crash matrix、tenant isolation、backup/restore 均維持既有 accepted REAL_LOGIC。

Truth boundary 仍必須維持：

- CI 設定 `FOX3D_MOCK_BLENDER=1`，所以 CI = **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，**不是 Production Ready**。
- `physicalPilotBatchValidated=false`
- `physicalPrototypeValidated=false`
- `batchLaunchDecision=WAITING_HUMAN_EVIDENCE`
- fixture cost = `PARTIAL`；packagingQty/hardwareQty 缺真實 evidence 時維持 MISSING。
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`
- `liveProviderReady=false`
- `liveMachineControl=false`
- LIVE_CNC / LIVE_LASER / PLC / automatic factory = **BLOCKED**
- Demand / Vision Judge / AI Video = **MOCK**
- OS sandbox / AR / print preflight / barcode / McKee-BCT = **PARTIAL**
- Prior REAL Blender 只能引用既有 scoped evidence，例如 `7a87ea5` 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX；本輪新的 Mock CI 不得冒充 REAL Blender。

**不要再修改 Phase 721–780 已通過邏輯，除非新測試真的發現 regression。**

---

# 這一輪的商業目標

把「3D 模型上看起來貼到門板」升級成可追溯、毫米級、可輸出生產檔的共用 Surface Decoration 能力：

`Engineering 3D → Printable Surface → true mm coordinates → Artwork Asset → Placement → UV/mm transform → Safe Area / Bleed / Keep-out → Cross-panel split → Blender Preview → Production Artwork → DAM/Evidence`

核心原則：

> **Blender Preview 的圖案位置必須來自同一份毫米級 Placement Source of Truth；生產檔不得再人工重新排一次。**

這不是只做櫃門。V1 架構要能共用於：

- KD 櫃門 / 抽屜面 / 側板 / 桌板
- Retail Fixture / POP 展示面
- Acrylic 壓克力平面
- Packaging 可印刷平面

但本輪只做上述既有產品家族，不為未來假想類型重寫整個系統。

---

# 不可違反的架構規則

1. **禁止重寫既有核心：** Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec/Parametric、MaterialLot、WorkOrder、PilotBatch、Journal、Backup/Restore、ManufacturingRelease。
2. Artwork Placement 要作為既有 Engineering Definition / Product Version 的延伸；**不得建立第二個 mm source of truth**。
3. Blender 只消費 canonical engineering + surface + placement；不得在 `blender_job.py` 另外藏一套手調位置。
4. DAM 只擴充必要 artwork role/metadata；不得做第二個素材庫。
5. 所有 persisted identity 必須 tenant-scoped，並綁 product/candidate/version/engineeringHash。
6. stale engineeringHash / stale artwork hash / cross-tenant / cross-product 必須 fail-closed。
7. 純程式幾何/轉換可以標 **REAL_LOGIC**；Mock Blender 渲染只能標 **MOCK**；沒有實際列印與人工量測，不可宣稱 Physical Print REAL / Production Ready。
8. 不要偷偷加入 live Vision/AI 自動辨識人物臉。V1 的 important-content regions 可由 caller/config/import 提供；若沒有 live provider，就標 CONFIG/IMPORTED/MOCK，而不是 REAL Vision。
9. 不要開 LIVE_CNC/LASER，也不要改既有 Human Approval Gate。

---

# Phase 781–788 — Printable Surface Canonical Model

建立共用 printable/decoratable surface model，建議新增 focused module，例如 `src/fox3d/artwork.py` 或 `src/fox3d/surface_decoration.py`；名稱可依現有風格，但不要把邏輯散到十幾個舊模組。

至少需要：

- `PrintableSurface`
  - `surfaceId`
  - `tenantId`
  - product/candidate/version identity
  - `engineeringHash`
  - `componentId`
  - `face` / local face identity
  - local origin/basis/orientation
  - `widthMm`, `heightMm`
  - trim/safe/bleed defaults（若是 CONFIG 要標出來源）
  - keep-out regions
  - deterministic `surfaceHash`
- Surface 必須由既有 Engineering components / geometry 衍生，不接受 caller 任意填一組與工程不一致的寬高後當 authoritative。
- 所有 mm 必須 finite、>0；orientation/basis 要可 deterministic canonicalize。
- Door/board 正反面或旋轉方向要有明確 local axes，避免左右門貼圖鏡像。
- Engineering resize / revision 後，舊 surfaceHash 必須 stale，不可靜默沿用。

測試至少：cabinet door、table/top-like panel、retail fixture face、acrylic face、packaging face；invalid dimensions / wrong component / stale hash / cross-tenant 全部 BLOCK。

---

# Phase 789–796 — Artwork Asset + Placement Intent

沿用 DAM，建立 artwork metadata/identity，不複製素材儲存系統。

Artwork metadata 至少包含：

- `artworkId`
- `tenantId`
- DAM asset identity / role
- source label：`IMPORTED` / `GENERATED` / 其他既有可證明來源
- bytes `sha256` + `size`
- MIME
- pixel width/height（能可靠解析才填）
- color space/profile（不知道就 UNKNOWN，不要猜）
- `artworkHash`

`ArtworkPlacement` 至少包含：

- surfaceId + surfaceHash
- artworkId + artworkHash
- xMm / yMm
- widthMm / heightMm
- rotationDeg
- anchor
- fit mode（`CONTAIN` / `COVER`；V1 **禁止 STRETCH**）
- crop/window definition
- optional important-content/protected regions with truth/source label
- deterministic `placementHash`

規則：

- 預設保持 aspect ratio。
- 使用者要求覆蓋可 crop，但 crop 要成為 canonical data，不得只存在 preview。
- 同 artwork bytes 若 hash 不同或 metadata 與實際 bytes 不符必須 fail。
- 替換 artwork 後舊 placementHash 必須 stale。

---

# Phase 797–804 — Deterministic mm ↔ UV Transform

建立可測試的 deterministic transform：

- Surface local mm → normalized UV。
- UV → mm round-trip。
- rotation / orientation / mirrored-face policy 要明確，不能靠 Blender GUI 人工修。
- 對 non-square artwork、portrait/landscape、rotated surface 都要有 regression。
- Blender material/texture placement只能讀同一份 transform/placement manifest。

驗收要求：

- mm→UV→mm round-trip tolerance 有明確數值與測試。
- 同 engineeringHash + surfaceHash + artworkHash + placement data 必須產出 deterministic placementHash。
- 任何 NaN/Inf/zero size/out-of-bounds invalid crop 必須 fail-closed。
- 不得以 render screenshot 的「看起來差不多」代替 geometry/UV 數值驗證。

---

# Phase 805–812 — Safe Area / Bleed / Keep-out / DPI

把工程障礙帶進 artwork placement，不讓 IP 圖案只靠肉眼對位。

至少支援：

- edge safe area
- bleed in true mm
- door/panel seam / gap
- handle keep-out
- hinge/drilling/hardware keep-out（從既有 engineering/hardware identity 衍生；缺資料就標 UNKNOWN/PARTIAL）
- caller-supplied protected/important-content regions

規則：

- important region 撞 seam / handle / drill keep-out → `BLOCKED_PLACEMENT` 或明確 HOLD，不可 silently accept。
- DPI/effective DPI 必須由 artwork pixel dimensions ÷ 實際 placement inches 計算；pixel dimensions 不知道時 = UNKNOWN/PARTIAL。
- DPI threshold 是 CONFIG policy，不宣稱為唯一印刷業標準。可提供 preview/print policy levels，但來源要清楚。
- bleed/safe 不得藏 pixel magic numbers，全部由 mm + transform 推導。
- 沒有真正印刷 preflight provider 時，`printPreflight` 仍是 PARTIAL。

---

# Phase 813–820 — Cross-Panel Master Artwork / 四門連圖

這是本輪最重要的 cabinet use case。

建立 Master Artwork Canvas / parent coordinate system：

- 以真實 mm 表示完整裝飾區域。
- 將 master artwork 精準映射到 2/3/4 個 panel surfaces。
- 每片 panel 只取得 master 的對應 crop，不可各自重新 stretch/fit。
- panel gap/seam 是否包含在 master coordinate 必須依 Engineering Definition 明確計算。
- 每片輸出要保存 master placementHash + panel crop lineage。

**必做 golden scenario：**

- 2400 × 1800 mm master canvas
- 4 × 600 mm door nominal surfaces（若實際工程有 gap，必須用工程真值而非硬寫 600）
- 使用帶座標刻度/棋盤格/十字標記的 deterministic artwork fixture
- 驗證跨門邊界 continuity、crop rect、mm→px/UV transform，不依賴 Mock Vision 判定。

另外測：2-door、3-door、4-door；resize 後舊 placement必須 stale或經 explicit recompute policy產生新 placementHash，不得靜默沿用舊 crop。

---

# Phase 821–828 — Production Artwork Package + DAM Lineage

產出可交付下游印刷/貼膜的 **production artwork file package**，但不要假裝已實際印刷。

至少產出 manifest：

- tenant/product/version
- engineeringHash
- surfaceHash
- master artworkHash
- placementHash
- panel/componentId
- crop rect（mm + 能可靠換算時的 px）
- output physical dimensions mm
- bleed/safe/keep-out result
- pixel dimensions / effective DPI
- output SHA-256 + size + MIME
- generatedAt
- source/truth labels

原則：

- 使用現有 DAM 存檔與 lineage；必要時新增清楚的 artwork roles，但不得建立第二 DAM。
- 使用現有 publish/evidence pattern做 atomic/canonical publish，若適用。
- output bytes hash 必須由實際檔案重算，不相信 metadata copy。
- `productionArtworkFileReady` 可代表「檔案邏輯完成/已生成」，**不代表 physical print validated**。
- 沒有真正 RIP/Printer proof 就不得標列印完成。

若 PDF/SVG 會迫使加入大量新 renderer 或假功能，本輪優先可靠 PNG + manifest；不要為了格式數量犧牲 evidence quality。

---

# Phase 829–836 — Blender Preview Parity

整合既有 `scripts/blender_job.py` / `src/fox3d/blender.py` / parametric flow：

- Blender texture/material placement必須吃 canonical surface + placement transform。
- Preview evidence 必須回帶：`engineeringHash`, `surfaceHash`, `artworkHash`, `placementHash`。
- 不得在 Blender side 另外調 x/y/scale 再不回寫 canonical lineage。
- 使用棋盤格/marker artwork 做 deterministic UV/geometry parity test。

REAL/MOCK 規則：

- `Platform(mock_blender=True)` / GitHub Actions = **MOCK render environment**。
- 若執行機可用既有 REAL Blender 5.2.1 + OptiX，至少做：
  1. 4-door cabinet master artwork REAL render
  2. 第二產品家族一個 REAL render（acrylic 或 retail/packaging，選最少重工的既有路徑）
- REAL evidence 必須有 `usedMock=false`、Blender version、device/GPU、output sha/size/job identity，並綁 exact CODE_EVIDENCE_SHA。
- 若本輪執行環境沒有 REAL Blender，可把 `realArtworkPreviewReady=false/BLOCKED_ENVIRONMENT`，**不能為了過關用 Mock 假裝 REAL**；Surface/Placement REAL_LOGIC 仍可獨立驗收。

不要用 MOCK Vision Judge 判斷「貼圖準不準」。真正可驗證的是 mm/UV transform + marker/grid deterministic mapping；REAL render只作額外 rendering evidence。

---

# Phase 837–840 — Hardening / Canonical Acceptance / Re-Gate Evidence

新增 focused tests/runner，例如：

- `tests/test_artwork.py`
- `tests/test_artwork_runner.py`
- `scripts/run_artwork_placement_e2e.py`
- `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md`
- `docs/ARTWORK_PLACEMENT_ACCEPTANCE.json`

檔名可依既有 naming style微調，但必須有一份 canonical acceptance truth set。

必測負向案例：

1. 800×1800 cabinet / 2-door placement基本案例。
2. 2400×1800 master / 4-door連圖，跨 seam continuity exact。
3. handle/drilling keep-out碰撞必須 BLOCK/HOLD。
4. low effective DPI 必須 PARTIAL/BLOCK print-ready policy，但可允許 preview。
5. artwork bytes被 tamper、metadata/hash沒同步 → FAIL。
6. cabinet resize / engineeringHash改變後舊 placement → FAIL STALE。
7. cross-tenant artwork/surface/placement → FAIL。
8. cross-product/candidate/version surface reuse → FAIL。
9. duplicate surface/placement canonical IDs → fail-closed。
10. invalid crop / NaN / Inf / zero dimensions / negative bleed → FAIL。
11. 2/3/4 panel split都不可逐片 stretch。
12. Blender Preview manifest與 production manifest必須共用 exact `engineeringHash + surfaceHash + artworkHash + placementHash`。
13. Mock Blender不得使 `realArtworkPreviewReady=true`。
14. `physicalPrintValidated` 必須維持 false，除非未來真的有人類/設備 evidence。

若 artwork state 被納入 durable store，backup/restore/tenant digest 必須擴充驗證；沿用現有 backup architecture，不建立第二套 backup。

---

# Readiness / Truth Labels

新增或更新 scoped readiness 時，至少保持以下語義：

- `surfaceDecorationLogicReady`: **REAL_LOGIC** only when canonical geometry/transform/lineage tests PASS。
- `productionArtworkFileReady`: **REAL_LOGIC / GENERATED**，只表示 production file package 產出與 hash/lineage成立。
- `realArtworkPreviewReady`: 只有 REAL Blender `usedMock=false` evidence 才可 true；否則 false/BLOCKED/PARTIAL。
- `physicalPrintValidated`: **false**，除非有真正列印/人工 proof evidence。
- `artworkContentAwarePlacementReady`: 沒有 live Vision provider時不得標 REAL；V1 caller-supplied protected regions屬 CONFIG/IMPORTED。
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`
- `liveMachineControl=false`

本 Phase 不得改變 LIVE_CNC/LASER/PLC 與既有 physical pilot 的 BLOCKED/WAITING_HUMAN_EVIDENCE 狀態。

---

# Acceptance / Evidence Discipline

完成後依既有 Re-Gate discipline：

1. 先完成 source + tests，確定 working tree clean。
2. 建立一個明確的 **CODE_EVIDENCE_SHA**，先 push code/test commit。
3. 等 exact CODE SHA GitHub Actions：Ubuntu + Windows SUCCESS。
4. 在 exact CODE_EVIDENCE_SHA clean tree 執行 Artwork canonical runner；不得在 docs commit後才假稱是 code SHA evidence。
5. Canonical output至少包含：
   - `acceptanceGenerationId`
   - `evidenceCodeCommit`
   - `workingTreeClean=true`
   - REAL/MOCK/PARTIAL/BLOCKED matrix
   - selected scenarios + identities/hashes
   - surface/artwork/placement/production output exact lineage
   - negative/tamper test summary
   - REAL Blender evidence（若有）或明確 BLOCKED_ENVIRONMENT
6. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/ARTWORK_PLACEMENT_ACCEPTANCE.md/.json`
7. `docs/CABINET_REAL_ACCEPTANCE.md` **只有在 cabinet 真正新增 artwork truth 且有 evidence時才更新**；若更新，新增 scoped row即可，不重寫歷史內容。
8. Push evidence/docs commit後，再確認 exact docs/head Ubuntu + Windows SUCCESS。
9. Issue #1 留完成摘要：CODE SHA、pytest數、CODE run ID、canonical generation、docs SHA、docs run ID、REAL/MOCK/PARTIAL/BLOCKED摘要。
10. 完成 Phase 781–840 後 **停下等 ChatGPT Re-Gate**，不要自行開始 Phase 841+。

---

# Definition of Done

本輪不是「畫面看得到貼圖」就完成。至少要能證明：

> 同一份 Engineering Definition 決定真實 printable surface；同一份 ArtworkPlacement 以毫米為 Source of Truth；同一個 placementHash 同時驅動 Blender Preview 與 production artwork crop；四門連圖的每片輸出可由 master artwork + engineering geometry deterministic 重建，且錯 tenant、錯 hash、舊 engineering、keep-out碰撞、低 DPI、tampered bytes都不能偷偷通過。

做到這個層級，Phase 781–840 才可送 Re-Gate。
