<!-- 2026-10-23 SSOT RECONCILIATION BANNER (GitHub Truth Sync) -->
> **⚠️ 2026-10-23 SSOT 校正聲明（GitHub 現況已合併，請勿重做已合併 PR）**
> - **GitHub `main` HEAD**：`9c9f2835a35d31eea9066c1ebcafa4385f61fc14`（2026-10-16 已完成產品線與基礎線收斂）。
> - **已合併（MERGED）之 17 個 PR**：`#2, #3, #7, #8, #9, #10, #11, #12, #13, #14, #15, #17, #19, #20, #22, #23, #24` 皆已正式合併入 `main`（最後一筆為 PR #20 `9c9f283` 於 2026-10-16T08:06:16Z 合併）。
> - **已關閉（CLOSED，由後續 PR 取代）**：PR `#21`（由 PR `#22` `0228aa5` 取代並合併）。
> - **已整合但 PR 物件維持 FROZEN**：PR `#16` 之程式碼已於 commit `70a5613`（PR #19 基底）整合進 `main`，PR #16 物件本身維持 Draft/FROZEN，不需重做。
> - **目前唯一待推進之 Open Draft PR**：PR `#18`（`codex/issue6-round3b-articulated-video-truth`，HEAD `7fd38e04e58165bbcf7971ba1793e53f2f3cb049`，對應 Issue #6 Round 3B 雙開門鉸鏈開合動畫 Ground-Truth + ComfyUI H3 橋接，待真 Blender 5.2.1 LTS / OptiX 渲染實證）。
> - **下方 2026-10-10 及更早章節中任何寫「PR #7–#15 未合併 / OPEN and unmerged / ACCEPTED_UNMERGED」之描述均為歷史快照，已被 GitHub `main` 現況取代。**

---

<!-- Neutral alias for docs/GROK_NEXT_PHASE_INSTRUCTIONS.md -->
<!-- Autonomous agents should prioritize reading this AGENT_* entry -->
<!-- The current-state body below is identical to docs/GROK_NEXT_PHASE_INSTRUCTIONS.md -->
# Current gate: PR #15 Round 13 ACCEPT_WITH_SCOPE / OWNER_DECISION_HOLD

> Repo: `netfox-web/blender-autonomous-3d`
> Canonical watcher filename: `docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md`
> Legacy compatibility filename: `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`
> These two files carry the same current gate. Older revisions that say Phase 901–960 Re-Gate Round 2 CHANGES_REQUIRED, or PR #15 Round 13 PARTIAL / EVIDENCE CLOSURE REQUIRED, are superseded and are not work orders.

GitHub is the source of truth. Facts below were re-read from GitHub on 2026-10-10 by worker `bc-6b95bfac-9463-5dfa-9c50-4d18481baad8`. This document does not authorize merge, release, deploy, or a new phase.

## 0. Current facts

- Canonical main: `b8c6fe911e6c8358ed7bcdecafc84cab86630810` (`supervisor: Round 13 evidence closure checkpoint`, committer date 2026-09-24T04:59:19Z).
- Main Actions [35957962415](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35957962415) is SUCCESS on that exact SHA for `unit (ubuntu-latest)` and `unit (windows-latest)`. That run is MOCK regression (`FOX3D_MOCK_BLENDER=1`). It is not REAL Blender evidence and it is not production readiness.
- Independent Supervisor decision [5854068961](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5854068961) (2026-09-27T08:06:33Z): **PR #15 Round 13 = ACCEPT_WITH_SCOPE / Round 14 HOLD**. Reviewed commit `c01f95d95ad21b97a48442c592f0259415a93c99`; CODE `2abcc3d817451d54a4ba6cd7793717745ad9bd43`. This supersedes CHANGES_REQUIRED comment [5853584739](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5853584739) for its two concrete defects. It is not all-project completion, integration acceptance, or Production PASS.
- Commander handoff [5854087167](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5854087167) (2026-09-27T08:09:02Z): **PROJECT_STATUS = SCOPED_CORRECTION_ACCEPTED / OWNER_DECISION_HOLD**. No `COMMANDER_NEXT_TASK` was issued.
- [2026-10-23 Reconciled: PRs #2, #3, #7–#15, #17, #19, #20, #22–#24 are MERGED into `main` (`9c9f283`); PR #16 code is integrated in `70a5613` while PR #16 object remains FROZEN; PR #18 (`7fd38e0`) is the only open active implementation PR.] (Historical 2026-10-10 note: PRs #7–#16 were OPEN and unmerged at that snapshot.) #7–#15 have scoped Supervisor acceptance. #13 counts only accepted Round 2; Issue #6 Round 3B stays `BLOCKED_DEPENDENCY` until accepted #14 is actually on main under a separate Owner authorization. PR #16 is **FROZEN** at `d03041dedd9002c74e65dd3e5a0cbd096d9575ca` with no acceptance and no GO.
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

