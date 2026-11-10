# Rollback

本功能完全位於 Issue #25 owned paths，沒有 shared migration、API router 掛載、正式資料或 feature flag。

在未 merge 前，停止使用本地 branch 即可。若未來經核准 merge，使用一般 reviewed revert PR，依 `git log --reverse main..feature` 的反序逐一 `git revert <sha>`；禁止 reset/force-push。移除新 namespace 後，既有 Fox3D、Product DNA、KD、render/Fleet 行為不變。

CLI state 只存在操作者指定的隔離目錄；清理前須確認不是稽核證據。正式 ERP／照片／補件資料從未由本功能建立，因此沒有 production rollback 或資料修復步驟。
