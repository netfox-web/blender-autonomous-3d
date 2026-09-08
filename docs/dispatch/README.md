# 多 AI 協作分工說明（2026-09-08 建立）

`fox3d` 目前 40 個 phase 全部實作完成，mock 測試（38/38）與真機驗收
（見 [`../REAL_E2E_ACCEPTANCE.md`](../REAL_E2E_ACCEPTANCE.md)，跑在真的
Blender 5.2.1 + NVIDIA T1000 GPU 上，13 項檢查全部 `REAL`）都是綠的。
接下來要把它「完善」，拆成三個互不重疊檔案範圍的工作包，分給三個不同的
AI 工具並行處理，由這個 Claude Code session 負責整合。

## 三個工作包

| 工作包 | 負責工具 | git branch | worktree 路徑 | 任務簡報 |
|---|---|---|---|---|
| Admin / Ops Console 完善 | Grok | `feature/admin-console` | `../開發 Blender Autonomous 3D - grok-admin` | 該資料夾內的 `TASK_BRIEF.md` |
| 測試覆蓋率 / 可靠性強化 | ChatGPT / GPT | `feature/test-hardening` | `../開發 Blender Autonomous 3D - gpt-tests` | 該資料夾內的 `TASK_BRIEF.md` |
| 模擬子系統引擎深度 | Antigravity | `feature/engine-depth` | `../開發 Blender Autonomous 3D - antigravity-engine` | 該資料夾內的 `TASK_BRIEF.md` |

三個都是獨立的 **git worktree**（同一個 repo 的三個不同工作目錄，各自簽出
不同 branch），檔案實體上是分開的，所以三個工具可以真的同時動工，不會互相
覆蓋彼此的修改。

## 怎麼派工

把對應資料夾整個路徑（或 `TASK_BRIEF.md` 的內容）交給每個工具，讓它在
**那個資料夾底下**工作（不是主目錄）。每份簡報都已經寫清楚：
- 現況與背景
- 具體任務範圍
- 明確的「不要碰哪些檔案」「不要做哪些事」邊界（尤其 Antigravity 那份，
  刻意排除了驅動真實 CNC 機台、真實攝影測量掃描硬體這類有實體世界風險的項目）
- 完工前必須跑 `pytest -q` 全過的檢查點

## 完工後怎麼整合回來

每個工具做完後，在自己的 worktree 裡 commit（不需要 push，本地 branch 就夠）。
回來這個 session 跟我說「Grok/GPT/Antigravity 做完了」，我會：

1. 分別檢視三個 branch 的 diff
2. 依序 merge 回 `master`（三個工作包檔案範圍幾乎不重疊，衝突風險低）
3. 每次 merge 後跑一次 `pytest -q`，最後視需要再跑一次
   `python scripts/run_real_e2e.py` 做真機驗收
4. 有任何行為變更或發現的 bug，會跟你確認過再定案

## 目前已知：有另一個並行的 session/工具也在動這個 repo

今天稍早發現 `src/fox3d/e2e.py` 的 `productionReady` 判斷邏輯被外部改得更嚴格
（要求所有 row 都不能是 `FAIL`，不只是必要項目），且多了一個
`scripts/run_remaining_real.py`（內容幾乎跟 `run_real_e2e.py` 重複）。這代表
可能還有其他工具/session 也在直接動主目錄。**建議之後所有「完善」工作都走
worktree + branch 的模式**，包括你自己或其他工具接下來想做的事，避免大家在
同一個工作目錄互相覆蓋。
