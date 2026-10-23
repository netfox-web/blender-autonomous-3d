# CI requirement（design-only）

Owner 已於 2026-10-23 22:02 TPE（Sentinel_d3a954388704819188d785f6030a0d89）直接核准只修改本 repo 測試流程，條件是優先使用已獲授權且隔離的 self-hosted runner，保留 Python 3.12、ruff、mypy、pytest，以及 Windows coverage。禁止新 runner registration、token、permission、Fleet／全域 host 設定與付費 hosted 用量。

GitHub repository runner registry 已唯讀核實為 HTTP 200、`total_count: 1`：`netfox03-blender-autonomous-3d`（ID 21）online、busy=false，labels=`self-hosted, Linux, X64, cpu, netfox-ci`。`netfox-web` 是 GitHub User。Owner 已另行明確核准推送指定分支、建立 Draft PR 與只執行已核實的自架 CI；不包含 Windows runner、host／credential／registration／permission 變更。

`.github/workflows/pytest.yml` 保留既有 `push(main)`／`pull_request` 事件與 Python 3.12、ruff、mypy、pytest 檢查，但不再含 hosted labels。`linux-required` 精確使用已核實 labels。`windows-required` 是獨立必敗 blocker job，輸出 `Windows required gate is BLOCKED` 後 exit 1；它不把 Linux 結果冒充 Windows，也確保 workflow 整體不可宣告 PASS。Windows runner 仍 offline/未授權，禁止自行新增。
