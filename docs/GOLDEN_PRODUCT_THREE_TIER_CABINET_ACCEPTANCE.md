# Golden 三層櫃驗收

Issue #4 的四 SKU／Artwork 工作台已完成 scoped preview 驗收。歷史 Artwork、工程與製造放行仍為 BLOCKED；不宣稱 Fox3D 全系統 Production Ready。

## CODE 與 CI

- CODE：`c9f685854a964d567643cab55f06aceb0c7375d2`。
- [CODE CI 34811888485](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34811888485)：Ubuntu / Windows SUCCESS，各 828 項成功測試標記，已核對 exact SHA 與實際 job log。
- Jobs：Ubuntu 103874724511 / Windows 103874724391。
- CI 使用 FOX3D_MOCK_BLENDER=1，屬 unit/regression；REAL 證據來自下列獨立 Blender 驗收。
- 初版完整本機回歸 817 項通過；後補變更的 63 項針對性測試通過。最終完整 828 項以 exact CODE CI 為準。
- 初版 CODE `1958d1a` 的 CI 34810799070 及中間版本 `5f6dc73` 的 CI 34811020340 均被修正版取代並取消，不計入 PASS。

## clean CODE 真實驗收

- Generation：`b1d53004-3a4c-4f6d-b192-1ebb85877a6d`。
- `evidenceCodeCommit=c9f685854a964d567643cab55f06aceb0c7375d2`、`workingTreeClean=true`、`developmentOnly=false`。
- CODE 雙 OS CI SUCCESS 後才執行 `python scripts/run_golden_product_e2e.py`。
- 真實 Blender / Cycles / OptiX；REAL_BLENDER=true、USED_MOCK=false。每個 job 的版本、裝置、檔案 SHA-256／大小與原始 job ID 見 JSON。
- 四 SKU MASTER_SPLIT 加一個 SINGLE_SURFACE，共五次生成；同一 EngineeringHash、四個獨立 ArtworkHash。

| SKU | Artwork | Generation | 結果 |
|---|---|---|---|
| KU002101 | FIXTURE_MASTER_V1 | 479a7782-530e-4734-98bf-bb0ad441a19e | PASS |
| KT015101 | FIXTURE_MASTER_V1 | 9d2f0c29-385f-4113-8481-6e4b6785ce8b | PASS |
| CN003701 | FIXTURE_MASTER_V1 | ce93d958-27e6-4584-a1b4-c45cd334170a | PASS |
| PN010201 | FIXTURE_MASTER_V1 | 800d4e27-ce48-48ba-9955-b4517e6f1990 | PASS |
| KU002101 | FIXTURE_SINGLE_V1 | 776ff044-71d5-4654-946e-e9dc061409be | PASS |

每次驗收包括：10 個實際板件尺寸與位置、三門 mesh UV 讀回、packed image 原圖雜湊、逐門 crop bounds／像素裁圖、FRONT_CLOSED／HERO_45／DOOR_DETAIL 三張 800×800 PNG、GLB 10 個 mesh、blend 檔在真實 Blender 重開、全部 HTTP 下載雜湊，以及服務重啟後 latest generation 與成果完整性。

Negative tests 包含錯門、UV shift、crop shift、door order swap、工程／圖稿 hash mismatch、master seam／order tamper、cross-SKU、重新計算 package hash 後的裁圖篡改、損壞或缺失檔案、錯誤 readiness 升級、假開門視角、mock 升級、不同 Artwork 不可重用同一 cache，以及取消後不可發布成果。

## Truth Matrix 與限制

| 項目 | 結果 |
|---|---|
| 既有歷史 SKU 原始 Artwork | BLOCKED，沒有原稿，不偽造來源 |
| 診斷 Artwork | FIXTURE，1 px/mm 校驗格網，不是印刷解析度承諾 |
| 宣告外尺寸與層門數 | CONFIG，Issue 提供 |
| 板厚與背板厚度 | ESTIMATED |
| mm / placement / UV / production trim parity | REAL_LOGIC + 真實 Blender worker readback |
| Blender 三視角／模型輸出 | REAL，scoped preview |
| 五金、孔位、接合、articulation | UNKNOWN / BLOCKED；FRONT_OPEN 未生成 |
| BOM / nesting / waste input | CANDIDATE / PARTIAL；無 stock / kerf 時不捏造耗損數值 |
| engineeringReady / productionReady / manufacturingReady | false |
| LIVE CNC / LASER / PLC | BLOCKED，沒有機台控制 |

UI 已實際核對 SKU／Artwork 選擇、原稿 BLOCKED、生成、取消、重試、快取取消後保留上一版、版本過期提示及下載入口。UI 詳細紀錄附於 JSON。

早期 `1014820a-e7b2-48bc-a8b7-ca9225f1debf` 為單款開發 smoke；`3f362932-375d-4862-b887-0fa647307d62` 為開發途中配方 hash 更新而使重啟驗證拒絕舊資料的測試，均不作正式證據。

[操作手冊](GOLDEN_PRODUCT_THREE_TIER_CABINET.md) · [機器可讀證據](GOLDEN_PRODUCT_THREE_TIER_CABINET_ACCEPTANCE.json) · [PR #7](https://github.com/netfox-web/blender-autonomous-3d/pull/7)

本檔為 Phase 2 DOCS 提交內容。DOCS 自身 SHA 與 exact 雙 OS CI 於完成後在 Issue #4 回報，避免未通過先宣稱 PASS 或自我引用導致反覆提交。完成後等待 Re-Gate，不自動進入影片 Issue #5/#6。
