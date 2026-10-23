# CI requirement（design-only）

Owner 已於 2026-10-23 22:02 TPE（Sentinel_d3a954388704819188d785f6030a0d89）直接核准只修改本 repo 測試流程，條件是優先使用已獲授權且隔離的 self-hosted runner，保留 Python 3.12、ruff、mypy、pytest，以及 Windows coverage。禁止新 runner registration、token、permission、Fleet／全域 host 設定與付費 hosted 用量。

GitHub repository runner registry 已唯讀核實為 HTTP 200、`total_count: 0`。`netfox-web` 是 GitHub User，不使用 organization runner groups。Owner 的直接授權涵蓋 `.github/workflows/pytest.yml`；open PR #26、#16 均未修改此檔，沒有實際 writer conflict。

既有 `.github/workflows/pytest.yml` 完整保留 `push(main)`／`pull_request`、`unit` matrix、`ubuntu-latest`／`windows-latest` 及原有 Python 3.12、ruff、mypy、pytest gate；不以關閉必要 CI 來避免 hosted 成本。本分支不 push／開 PR，所以不會由本次工作觸發該 hosted workflow。

另以 `.github/workflows/pytest-self-hosted-candidate.yml` 保存 reusable `workflow_call` 候選；目前沒有 caller 或直接 trigger。Linux 與 Windows 都強制 `self-hosted` 加上待核准的自訂 label，兩者都是 required job，不能靠 skip 宣告總體成功。現階段 runner label 與 Windows host 仍 UNKNOWN，因此狀態是「CI 設計待接線／執行 HOLD」，不是 CI 已接入。Windows gate 不得刪除或用 Linux 結果代替。
