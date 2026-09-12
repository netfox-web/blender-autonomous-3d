# Blender Autonomous 3D — Autonomous Agent Rules

## Autonomous Execution Policy (免問即行)
- 只要 GitHub `main` 出現新的 `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` instruction commit 或 Issue #1 出現新指令，一律視為已授權。
- 自動開始分析、實作、測試、commit、push、回報 Issue #1；完成後等待下一個 Re-Gate。
- **絕對不需要** 在開始前或過程中向使用者詢問「要不要開始」、「是否授權實作」。
- 僅在遇到以下情況時，才必須暫停並向使用者確認：
  1. LIVE CNC / LASER / PLC 或真實工廠實體機台控制操作
  2. 破壞性正式環境操作
  3. 涉及敏感密鑰憑證（credentials / secrets）
  4. 指令內明確標記需「Human Approval」之項目

## Execution Protocol
- 嚴格遵守兩階段流程：
  1. Phase 1: CODE + tests commit -> push -> 等待 GitHub Actions (Ubuntu + Windows) 綠燈 PASS。
  2. 在 clean working tree 上執行真實環境驗收腳本（如 `scripts/run_product_truth_render_e2e.py`）。
  3. Phase 2: 更新 DOCS + 狀態檔 commit -> push -> 等待 GitHub Actions (Ubuntu + Windows) 綠燈 PASS。
  4. 回報 GitHub Issue #1 並附上 CI run ID、commit SHA 與摘要。
- 絕不在 GitHub Actions 未成功前宣稱 CI 綠燈。
- 絕不可超越當前 Phase 範圍（例如未獲 Re-Gate 許可不可跨入 Phase 901+）。
