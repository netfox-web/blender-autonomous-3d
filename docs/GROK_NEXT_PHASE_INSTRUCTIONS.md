# Grok 修正指令：Phase 721–780 Re-Gate Round 6 — EVIDENCE ONLY / CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main/docs head: `d70d43fa8f561d9268866e076057be9b777f3c2a`  
> Reviewed CODE_EVIDENCE_SHA: `d0f5bbd64fddae929a17c75521989281ca8652e9`  
> Review result: **CHANGES REQUIRED — implementation logic accepted, CI provenance incomplete**  
> **Do not enter Phase 781+. Do not start Artwork Placement yet.** 本輪是 evidence-only Re-Gate；不要重寫或擴充既有架構，也不要改變已通過的 pilot-batch 行為。

## 本輪已接受，禁止退步

Round 5 的三個 implementation blockers 已實質補齊：

1. **Independent BOM authority — ACCEPTED / REAL_LOGIC**
   - `batchAuthority.bomAuthority` 發布既有 candidate BOM lines + tenant/candidate/engineeringHash/bomHash。
   - verifier 以既有 `stable_hash(lines)` 重算 bomHash，並從 BOM lines 重算 hardware/part expected。
   - carton expected 不再成為自身 authority；coordinated fake hardware/part expected/observed、missing/duplicate/cross-tenant/wrong candidate/hash/engineering、lines-vs-hash tamper tests 已加入。
   - `hardwareQty=BOM` 時 lineage hardwareExpected/hardwareObserved required + exact，不可 truthy-skip。

2. **Packaging checklist independent authority — ACCEPTED / REAL_LOGIC**
   - `batchAuthority.packagingChecklistAuthority` 發布既有 Prototype checklist identity、qty、source/truthLabel、PACKAGING DAM lineage。
   - MANUAL/IMPORTED launch-relevant carton 必須以 checklistId 唯一 resolve，tenant/prototypeUnit/engineeringHash/qty exact。
   - FIXTURE 正向仍是 packagingQty=MISSING、quantityLineage.ok=false、cost PARTIAL；沒有為了過測試造假 quantity。
   - fake/ghost/duplicate checklist、tenant/unit/hash mismatch、FIXTURE forged source、partial carton binding regressions 已加入。

3. **WorkOrder nested owner fail-closed — ACCEPTED / REAL_LOGIC**
   - reservation/consumed snapshot 明確由 durable parent WorkOrder/batch 衍生 owner identity；沒有假裝 child row 自帶 persisted owner field。
   - verifier 對 reservationId/lotId/quantity/state/kind/tenantId/workOrderId required fail-closed；blank tenant/workOrder、cross-tenant/cross-WO regressions 已加入。

4. 既有 Phase 721–780 guarantees 必須全部保持：material/labor/QC/carton/cost/decision/WorkOrder exact-set、FINAL QC PASS/pinned qcPlanHash、execution completeness、crash matrix、tenant isolation、backup/restore。

## Truth / readiness 邊界 — 必須保持

目前 canonical generation `75f9d22c-8b38-4e96-ae73-4d3c66907abe` 可接受為 **FIXTURE + REAL_LOGIC** evidence：

- 4 batches × 5 units / 20 unit executions
- `physicalPilotBatchValidated=false`
- `physicalPrototypeValidated=false`
- `batchLaunchDecision=WAITING_HUMAN_EVIDENCE`
- cost `PARTIAL`
- fixture packagingQty = `MISSING`
- fixture hardwareQty = `MISSING`（BOM expected 與 fixture observed 不符時沒有偽造為 BOM PASS）
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`
- `liveProviderReady=false`
- `liveMachineControl=false`
- LIVE_CNC / LIVE_LASER / PLC / live provider / automatic factory 仍 **BLOCKED**
- Demand / Vision / AI Video 仍 **MOCK**
- OS sandbox / AR / preflight / barcode / McKee-BCT 仍 **PARTIAL**
- Prior REAL Blender 只可引用既有 `7a87ea5` 的 4/4 Blender 5.2.1 LTS + NVIDIA T1000 OptiX scoped evidence。

`pytest -q → 567 passed` 只可標 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不可描述為 Production Ready。CI workflow 仍設定 `FOX3D_MOCK_BLENDER=1`。

---

# 唯一 Re-Gate blocker — 缺少 exact CODE_EVIDENCE_SHA GitHub Actions run

上一輪 exit criteria 明確要求：

> GitHub Actions **exact CODE SHA** Ubuntu + Windows SUCCESS；之後 docs/head push也要 Ubuntu + Windows SUCCESS。

目前 GitHub evidence 是：

- CODE_EVIDENCE_SHA：`d0f5bbd64fddae929a17c75521989281ca8652e9`
- GitHub Actions 查 exact `head_sha=d0f5bbd...`：**沒有 workflow run**
- docs/head：`d70d43fa8f561d9268866e076057be9b777f3c2a`
- Actions run `34478705706` on exact docs/head `d70d43f`：Ubuntu + Windows **SUCCESS**

雖然 `d70d43f` 只是在 parent CODE `d0f5bbd` 上提交 evidence/docs，且該 run 會測到相同 src/tests，但它仍不符合我們自己寫下的「exact CODE SHA run」exit criterion。因此 **Phase 781+ 先不放行**。

## Required correction — evidence only

不要再修改 Phase 721–780 implementation，除非 CI 真正發現 regression。優先採以下流程：

1. 在目前 main 上建立一個 **不改變程式行為的 code-evidence trigger commit**（可用 `git commit --allow-empty`）。
   - commit message 建議：`chore: trigger exact Phase 721-780 code evidence CI`
   - 這個新 commit 將成為新的 `CODE_EVIDENCE_SHA`。
   - 不要為了製造 commit 隨便改 source、測試或架構。
2. **先只 push 這個 CODE_EVIDENCE_SHA**，不要立刻把 docs commit 一起 push。
3. 等 GitHub Actions 對這個 **exact CODE_EVIDENCE_SHA** 完整跑完：
   - `unit (ubuntu-latest)` = SUCCESS
   - `unit (windows-latest)` = SUCCESS
4. 在該 exact SHA clean tree 上重新跑：
   - `pytest -q`
   - Phase 721–780 canonical runner
   - 確認 `evidenceCodeCommit` = exact 新 CODE_EVIDENCE_SHA
   - `workingTreeClean=true`
   - pre-serialize / post-serialize / post-publish verifier PASS
   - crash matrix / tenant isolation / backup-restore 保持 PASS
5. 然後才更新 evidence docs：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`
   - Phase 721–780 acceptance docs/JSON（若 runner 會生成）
   - `docs/CABINET_REAL_ACCEPTANCE.md` 本輪無 cabinet truth change，**不要動**。
6. Push docs/evidence commit後，再等該 **exact docs/head SHA** Ubuntu + Windows SUCCESS。
7. Issue #1 留完成摘要，必須同時列出：
   - exact CODE_EVIDENCE_SHA
   - exact CODE Actions run ID + Ubuntu/Windows SUCCESS
   - exact EVIDENCE_DOCS_SHA
   - exact docs/head Actions run ID + Ubuntu/Windows SUCCESS
   - pytest count
   - canonical generation ID
   - `FIXTURE/REAL_LOGIC ≠ Production Ready`
8. 完成後停下等 ChatGPT Re-Gate。**不要自行進 Phase 781+。**

### Alternative

如果你能用 GitHub Actions 的合法方式讓 workflow 對既有 `d0f5bbd` 產生一個真正 `head_sha=d0f5bbd...` 的完整 Ubuntu + Windows SUCCESS run，也可以不做 allow-empty commit；但不得拿 `d70d43f` 的 docs/head run 冒充 exact CODE SHA run。

---

# 下一主線仍已排隊，但這輪禁止開始

Re-Gate 通過後，下一個正式大 Phase 優先做 **Artwork Placement / Surface Decoration Engine**，直接整合既有 Engineering Definition + Blender + DAM，不建立孤立貼圖工具：

`Engineering 3D → Printable Surface → true mm coordinates → UV → Safe Area → Bleed → Artwork Placement → cross-panel split → Blender Preview → Production Artwork`

下一大 Phase 要支援櫃門、桌板、展示架、壓克力、包裝等共用 surface decoration；包含跨門連圖、人物/Logo/文字避開門縫/把手/鑽孔、DPI、bleed、禁止拉伸，以及 Blender Preview placement 與 Production Artwork 的 mm/hash lineage。

**本輪只補 CI provenance。Phase 781+ / Artwork Placement 不得提前實作。**
