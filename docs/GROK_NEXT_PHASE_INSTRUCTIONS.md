<!-- Legacy filename. The current-state body is identical to docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md -->
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
- PRs #7–#16 are OPEN and unmerged. #7–#15 have scoped Supervisor acceptance. #13 counts only accepted Round 2; Issue #6 Round 3B stays `BLOCKED_DEPENDENCY` until accepted #14 is actually on main under a separate Owner authorization. PR #16 is **FROZEN** at `d03041dedd9002c74e65dd3e5a0cbd096d9575ca` with no acceptance and no GO.
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
