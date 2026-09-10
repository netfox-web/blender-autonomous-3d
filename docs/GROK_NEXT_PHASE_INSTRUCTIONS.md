# Grok 修正指令：Phase 721–780 Re-Gate Round 7 — FINAL EVIDENCE BINDING / CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `12ef5462711604971cb4e5beaad63119376d996d`  
> Previous instruction: `c839fb3465ff2ce018192441517070bbcca94ce4`  
> Review result: **CHANGES REQUIRED — exact CODE SHA CI 已補齊，但 canonical/docs evidence 尚未綁到新 SHA**  
> **Do not enter Phase 781+. Do not start Artwork Placement yet.** 本輪仍是 evidence-only；不得重寫或擴充既有架構。

## 本輪新進度 — 已接受

Grok 已依 Round 6 建立不改變 tree 的 code-evidence trigger commit：

- New exact CODE_EVIDENCE_SHA candidate: `12ef5462711604971cb4e5beaad63119376d996d`
- Parent: `c839fb3465ff2ce018192441517070bbcca94ce4`
- `c839fb3...12ef546` compare：**0 changed files**，是合法的 allow-empty / evidence trigger，不是為了製造 SHA 亂改 source。
- GitHub Actions run: **`34481806339`**
- exact `head_sha=12ef5462711604971cb4e5beaad63119376d996d`
- `unit (ubuntu-latest)` = **SUCCESS**
- `unit (windows-latest)` = **SUCCESS**
- Ubuntu log明確 checkout exact `12ef546...` 並執行 `pytest -q`。
- CI 仍明確設定 `FOX3D_MOCK_BLENDER=1`，因此此 run 只能標示 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，**不是 Production Ready**。

Round 5 implementation logic 保持 ACCEPTED / REAL_LOGIC，不要再改：

- independent BOM canonical authority
- packaging checklist independent authority
- WorkOrder nested owner fail-closed
- material/labor/QC/carton/cost/decision/WorkOrder exact-set
- FINAL QC PASS + pinned qcPlanHash
- execution completeness
- subprocess crash matrix
- tenant isolation
- backup/restore

`docs/CABINET_REAL_ACCEPTANCE.md` 本輪沒有 cabinet truth change，不要為了更新日期修改。

## 尚未完成的唯一 blocker

目前 repo main 已在 exact-CI trigger SHA `12ef546...`，但現有 acceptance/evidence docs 仍描述：

- CODE `d0f5bbd64fddae929a17c75521989281ca8652e9`
- generation `75f9d22c-8b38-4e96-ae73-4d3c66907abe`

也就是 Round 6 要求的「**在新的 exact CODE SHA clean tree 上重新跑 canonical runner，然後把 evidence docs 綁到該 SHA**」尚未完成。不要把先前 `d0f5bbd` 的 canonical generation 直接改字串宣稱成 `12ef546`；必須真正重新執行 runner，讓產出自己寫入新 SHA / generation。

# Required correction — 只做以下步驟

1. **以 `12ef5462711604971cb4e5beaad63119376d996d` 作為新的 CODE_EVIDENCE_SHA。**
   - 不要再建立另一個 code trigger SHA，除非你真的修改 source/tests 修 bug。
   - 開始 runner 前確認 working tree clean。

2. 在 exact `12ef546...` clean tree 上重新執行：
   - `pytest -q`
   - Phase 721–780 canonical acceptance runner
   - existing crash matrix
   - tenant isolation / backup-restore verification（依現有 runner/測試，不建立新系統）

3. 新 canonical evidence 必須由 runner 真正產生，至少證明：
   - `evidenceCodeCommit == 12ef5462711604971cb4e5beaad63119376d996d`
   - `workingTreeClean == true`
   - pre-serialize verifier PASS
   - post-serialize verifier PASS
   - post-publish verifier PASS
   - 4 batches × 5 units / 20 execution units仍成立
   - canonical exact-set authorities仍完整
   - tenant digest restore comparison仍 equal
   - crash matrix仍 PASS

4. Truth/readiness 邊界不得變：
   - `physicalPilotBatchValidated=false`
   - `physicalPrototypeValidated=false`
   - `batchLaunchDecision=WAITING_HUMAN_EVIDENCE`
   - fixture cost仍可/應為 `PARTIAL`（若 packagingQty/hardware truth仍缺）
   - `globalProductionReady=false`
   - `fullAutonomousFactoryReady=false`
   - `liveFactoryExecutionReady=false`
   - `liveProviderReady=false`
   - `liveMachineControl=false`
   - Demand / Vision / AI Video = **MOCK**
   - OS sandbox / AR / preflight / barcode / McKee-BCT = **PARTIAL**
   - LIVE_CNC / LIVE_LASER / PLC / live provider / automatic factory = **BLOCKED**
   - Prior REAL Blender只可引用既有 `7a87ea5` 4/4 Blender 5.2.1 LTS + T1000 OptiX scoped evidence；不要把本輪 CI 當 REAL Blender。

5. 完成 clean runner 後更新 evidence docs：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - `docs/PILOT_BATCH_EXECUTION_ACCEPTANCE.md/.json`
   - `docs/COMMERCIAL_LAUNCH_READINESS_ACCEPTANCE.md/.json`
   - runner 實際會更新的其他 Phase 721–780 canonical evidence files
   - **不要修改 `docs/CABINET_REAL_ACCEPTANCE.md`，除非真的有 cabinet truth change。**

6. Evidence docs 必須明確列出：
   - exact CODE_EVIDENCE_SHA `12ef546...`
   - exact CODE Actions run `34481806339`
   - Ubuntu SUCCESS / Windows SUCCESS
   - 新 pytest pass count
   - 新 canonical generation ID
   - `FIXTURE/REAL_LOGIC ≠ Production Ready`
   - prior REAL Blender scope與 live blockers

7. Push docs/evidence commit後，等待該 **exact docs/head SHA** 的 GitHub Actions：
   - Ubuntu SUCCESS
   - Windows SUCCESS
   - 一樣標成 MOCK/unit/integration + FIXTURE/REAL_LOGIC，不是 Production Ready。

8. Issue #1 留完成摘要，必須包含：
   - CODE_EVIDENCE_SHA `12ef546...`
   - CODE Actions `34481806339`, Ubuntu/Windows SUCCESS
   - EVIDENCE_DOCS_SHA
   - docs/head Actions run ID + Ubuntu/Windows SUCCESS
   - pytest count
   - canonical generation ID
   - REAL/MOCK/PARTIAL/BLOCKED摘要

9. 完成後**停下等 ChatGPT Re-Gate**。不得自行開始 Phase 781+。

---

# 下一主線已排隊，但本輪仍禁止開始

Re-Gate 通過後，下一正式大 Phase 優先做 **Artwork Placement / Surface Decoration Engine**，沿用 Engineering Definition + Blender + DAM，不建立孤立貼圖工具：

`Engineering 3D → Printable Surface → true mm coordinates → UV → Safe Area → Bleed → Artwork Placement → cross-panel split → Blender Preview → Production Artwork`

下一 Phase 要支援櫃門、桌板、展示架、壓克力、包裝等共用 surface decoration；包含跨門連圖、人物/Logo/文字避開門縫/把手/鑽孔、DPI、bleed、禁止拉伸，以及 Blender Preview placement ↔ Production Artwork 的 mm/hash lineage。

**本輪只有 final evidence binding。Phase 781+ / Artwork Placement 不得提前實作。**