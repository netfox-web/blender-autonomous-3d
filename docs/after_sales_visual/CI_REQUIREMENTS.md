# CI requirement（design-only）

Owner 已於 2026-10-23 22:02 TPE（Sentinel_d3a954388704819188d785f6030a0d89）直接核准只修改本 repo 測試流程，條件是優先使用已獲授權且隔離的 self-hosted runner，保留 Python 3.12、ruff、mypy、pytest，以及 Windows coverage。禁止新 runner registration、token、permission、Fleet／全域 host 設定與付費 hosted 用量。

GitHub repository runner registry 已唯讀核實為 HTTP 200、`total_count: 0`。`netfox-web` 是 GitHub User，不使用 organization runner groups。Owner 的直接授權涵蓋 `.github/workflows/pytest.yml`；open PR #26、#16 均未修改此檔，沒有實際 writer conflict。

目前 workflow 為 reusable `workflow_call`，沒有 push、pull request 或 manual trigger；Linux 與 Windows 都強制 `self-hosted` 加上待核准的自訂 label，且兩者都是 required job，不能靠 skip 宣告總體成功。現階段 runner label 與 Windows host 仍 UNKNOWN，因此不 push、不開 PR、不執行。Windows gate 不得刪除或用 Linux 結果代替。
