<!-- 2026-10-23 SSOT RECONCILIATION BANNER (GitHub Truth Sync) -->
> **⚠️ 2026-10-23 SSOT 校正聲明（GitHub 現況已合併，請勿重做已合併 PR）**
> - **GitHub `main` HEAD**：`9c9f2835a35d31eea9066c1ebcafa4385f61fc14`（2026-10-18T15:04:41Z 合併 PR #24 後之最新主線）。
> - **已合併（MERGED）之 17 個 PR 與精確 Merge Commit SHA**：
>   - `#2` (`c53f174`, 2026-09-13) — Sonaqueen recipe library & product admin UI
>   - `#3` (`f43d80e`, 2026-09-14) — Recipe 商品庫中文操作介面與真實 3D 生成
>   - `#14` (`d13d9f9`, 2026-10-10) — Issue #6 Round 3A Articulation Engineering Authority Source V1
>   - `#7` (`b8da4de`, 2026-10-10) — Golden 三層櫃四 SKU Artwork 與真實 3D 工作台
>   - `#8` (`49b7cd2`, 2026-10-10) — Artwork library, 3D print previews & UV PDF workbench
>   - `#9` (`e914cc5`, 2026-10-10) — PrintFox design library & single-run generation
>   - `#10` (`5fa4c92`, 2026-10-10) — Product model workbench with separate templates & materials
>   - `#11` (`978eb58`, 2026-10-10) — Reuse product masters for artwork and scene previews
>   - `#12` (`f3ad3f0`, 2026-10-10) — Organize product masters with a category tree
>   - `#15` (`e6e62dd`, 2026-10-10) — Batch artwork variants & preserve product composition history
>   - `#17` (`1763a5b`, 2026-10-17) — Round 13 hold sync, #13 watchdog RCA, lint gate
>   - `#13` (`7f62a9e`, 2026-10-17) — Issue #6 deterministic Blender video ground truth & candidate QA
>   - `#19` (`7f62a9e`, 2026-10-17) — Issue #18 Product DNA Golden SKU 匯出契約（注意：`#18` 為 Issue 編號，由 PR `#19` 實作並合併）
>   - `#20` (`3010617`, 2026-10-18) — 地端 AI 實景生成（GPU 艦隊 FLUX 3）＋ 工坊 UI 改版
>   - `#22` (`6ba2c03`, 2026-10-18) — 正面平視視角把家具框進畫面、櫃子保證完整
>   - `#23` (`24f33b9`, 2026-10-18) — Blender 光追上 GPU 艦隊（`blender_scene_render`）
>   - `#24` (`9c9f283`, 2026-10-18) — 場景定義以 JSON 字串過中控，避免 `0.0→0` 造成 hash mismatch
> - **已關閉（CLOSED，未合併、由後續 PR 取代）**：PR `#21`（由已合併之 PR `#22` `6ba2c03` 取代）。
> - **程式碼已整合、PR 物件維持 FROZEN**：PR `#16`（`codex/product-scene-library` @ `d03041d`，其程式碼已於 `70a5613` 整合進 `main`，PR #16 物件本身維持 Draft/FROZEN，不需重做）。
> - **下方 2026-10-10 及更早章節中任何寫「PR #7–#15 未合併 / OPEN and unmerged / ACCEPTED_UNMERGED / PR13 remains HOLD and unmerged」之描述均為歷史快照，已被上述 GitHub `main`（`9c9f283`）現況取代。**

---

<!-- Legacy filename. The current-state body is identical to docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md -->
# Current gate: PR #15 Round 13 ACCEPT_WITH_SCOPE / OWNER_DECISION_HOLD

> Repo: `netfox-web/blender-autonomous-3d`
> Canonical watcher filename: `docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md`
> Legacy compatibility filename: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`
> These two files carry the same current gate. Older revisions that say Phase 901–960 Re-Gate Round 2 CHANGES_REQUIRED, or PR #15 Round 13 PARTIAL / EVIDENCE CLOSURE REQUIRED, are superseded and are not work orders.

GitHub is the source of truth. Facts below were re-read from GitHub on 2026-10-10 by worker `bc-6b95bfac-9463-5dfa-9c50-4d18481baad8`. This document does not authorize merge, release, deploy, or a new phase.

## 0. Current facts

- Canonical main (reconciled 2026-10-23): `9c9f2835a35d31eea9066c1ebcafa4385f61fc14` (PR #24 merged 2026-10-18T15:04:41Z; historical 2026-10-10 snapshot main was `b8c6fe911e6c8358ed7bcdecafc84cab86630810`).
- Main Actions [35957962415](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35957962415) is SUCCESS on that exact SHA for `unit (ubuntu-latest)` and `unit (windows-latest)`. That run is MOCK regression (`FOX3D_MOCK_BLENDER=1`). It is not REAL Blender evidence and it is not production readiness.
- Independent Supervisor decision [5854068961](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5854068961) (2026-09-27T08:06:33Z): **PR #15 Round 13 = ACCEPT_WITH_SCOPE / Round 14 HOLD**. Reviewed commit `c01f95d95ad21b97a48442c592f0259415a93c99`; CODE `2abcc3d817451d54a4ba6cd7793717745ad9bd43`. This supersedes CHANGES_REQUIRED comment [5853584739](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5853584739) for its two concrete defects. It is not all-project completion, integration acceptance, or Production PASS.
- Commander handoff [5854087167](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5854087167) (2026-09-27T08:09:02Z): **PROJECT_STATUS = SCOPED_CORRECTION_ACCEPTED / OWNER_DECISION_HOLD**. No `COMMANDER_NEXT_TASK` was issued.
- [2026-10-23 Reconciled] PRs `#2` (`c53f174`), `#3` (`f43d80e`), `#7` (`b8da4de`), `#8` (`49b7cd2`), `#9` (`e914cc5`), `#10` (`5fa4c92`), `#11` (`978eb58`), `#12` (`f3ad3f0`), `#13` (`7f62a9e`), `#14` (`d13d9f9`), `#15` (`e6e62dd`), `#17` (`1763a5b`), `#19` (`7f62a9e`, for Issue #18), `#20` (`3010617`), `#22` (`6ba2c03`), `#23` (`24f33b9`), and `#24` (`9c9f283`) are all **MERGED** into `main`. PR `#21` is **CLOSED** (superseded by `#22`). PR `#16` code is integrated into `main` at `70a5613` while the PR #16 object remains **FROZEN** at `d03041dedd9002c74e65dd3e5a0cbd096d9575ca`.
- Round 14 is **HOLD**. No next-phase GO exists.
- `MERGE_AUTHORIZED=false`
- `globalProductionReady=false`
- `physicalProductGeometryTruth=false`
- `physicalPrintValidated=false`
- `manufacturingReady=false`

Inventory of that handoff is `docs/PROJECT_COMPLETION_INVENTORY.md`. The copy that previously existed only on PR #15 DOCS SHA `c01f95d95ad21b97a48442c592f0259415a93c99` is a pre-final snapshot: its pending review and 8-of-10 statements are historical. The mainline copy records the final status from comment 5854087167.

**Completion calculation from that handoff:** 9 / 10 of the inventoried PR scopes (#7 through #16) have a scoped Supervisor acceptance. This is an unweighted acceptance count. It is not product completion, implementation effort, merged delivery, or Production readiness. Global completion percentage is not established.

## 1. Do not execute superseded instructions

Do not implement the old Phase 901–960 Round 2 blockers, and do not run the old Round 13 evidence-closure sequence, as if they were still the current order. Those rounds have independent decisions. Preserve accepted architecture. Do not rewrite Scheduler, Queue, DAM, Recipe, TwinStore, CabinetSpec, publication authority, or the database.

Do not:

- merge, Mark Ready, retarget, rebase onto main, cherry-pick, force-push, or reset PRs #7–#16;
- start Round 14, Phase 961+, or any new implementation phase;
- claim that any PR or main is production-ready or merged;
- touch Production, NAS, FoxStudio Fleet, a production GPU, or LIVE CNC / LASER / PLC;
- rebuild DAM, queue, scheduler, recipe, authority, or DB.

## 2. Owner decisions still required

From handoff 5854087167, still waiting on the Owner:

1. Whether and how to authorize integration of the accepted stacks and #14, with exact targets and post-integration validation.
2. Disposition of duplicate Issue #5 while preserving Issue #6 history.
3. Scope and priority of the remaining evidence gaps and any future physical, artwork, or Fleet acceptance.

Release, deploy, and Production require separate explicit authorization. Proposed integration order, only after that separate authorization: product stack #7 → #8 → #9 → #10 → #11 → #12 → #15, then separately #14 before any Supervisor permission for #13 Round 3B. #16 stays FROZEN until dependencies formally pass and the Supervisor explicitly says GO.

## 3. Truth boundaries

- CI pytest with mock Blender is MOCK regression.
- Scoped PR #15 publication and latest-read behavior accepted in comment 5854068961 is REAL_LOGIC inside that scope.
- Local file-byte checks described there are scoped REAL_OS_IO_INTEGRITY.
- The eleven headless outputs described there are REAL_RENDER for synthetic and reference inputs only, on their recorded Blender 5.2.1 LTS / CYCLES / OptiX / `usedMock=false` runs. This file does not re-run them.
- Hard-link, hostile writer, and TOCTOU remain PARTIAL.
- NAS, object storage, hardware power loss, measured CAD, physical print, manufacturing, live H3 / LTX / Vision, and LIVE CNC / LASER / PLC remain BLOCKED.
- The excluded PR #13 attempt `d5d7140b-4b9a-420b-a75d-2c3be56ac3d3` is classified in `docs/evidence/PR13_WATCHDOG_D5D7140B.md`. The stop mechanism is REAL_LOGIC. The in-process reason the frame-0 depth call did not return is BLOCKED. The finding is PARTIAL. It is not a PASS.

STOP. An unchanged OWNER_DECISION_HOLD is not a GO.

