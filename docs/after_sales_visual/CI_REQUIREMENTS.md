# CI requirement（design-only）

Owner 已核准只修改本 repo 測試流程，條件是優先使用已獲授權且隔離的 self-hosted runner，保留 Python 3.12、ruff、mypy、pytest，以及 Windows coverage。禁止新 runner registration、token、permission、Fleet／全域 host 設定與付費 hosted 用量。

目前沒有可核實的 repo registration、host allowlist 或 runner labels；connector 也不提供 runner registry。Commander lease 的 owned paths 尚未含 `.github/workflows`。因此本文件只記需求，不建立或修改 workflow，不 push、不觸發 CI。可執行路徑與 path ownership 都確認後，最小 workflow 才能把現有 gate 等價搬到獲准 labels；Windows gate 不得刪除或用 Linux 結果代替。
