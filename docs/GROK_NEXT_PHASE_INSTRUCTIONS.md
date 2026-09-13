# Development Agent 修正指令：Event-Driven Supervisor Re-Gate Round 8 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed prior instruction: `14ccc914f248881bfb810ba8485d46046b401580`
> Reviewed CODE/head before this instruction commit: `d4445058a80c774fdd68d0041ff3e2bf5632a3b8`
> CODE Actions run: `34786792942` — review time: Windows SUCCESS, Ubuntu still IN_PROGRESS
> Re-Gate result: **CHANGES REQUIRED (Round 8)**
> `webhookRealE2e=false`; `eventDrivenSupervisorReady=false`; `liveProviderReady=false` 必須維持。
> **Phase 961+ remains HOLD.**

## 0. 本輪已接受的實質進展 — 保留，不要重寫

`d4445058...` 確實修正了 Round 7 的大部分 live-client 問題，可保留為 **REAL_LOGIC / TESTED-PARTIAL**：

- `get_commits_since()` local git path 已改用 `%B`，完整保留 commit body / 6 trailers，不再只取 `%s` subject。
- local discovery failure 不再 silent `[]`；local + remote 都失敗時會 raise `GitHubVerificationError`，engine 也不再把 discovery failure 當成 0 candidate。
- Window B1 staged / unstaged recovery path 已加入 fail-closed exception handling。
- Issue comments REST fallback 已處理 `Link rel="last"`，可抓最後頁並 fail closed；不再固定只讀第一頁。
- 新增真實 temp-git `GitHubClient` trailer integration test，以及 comment pagination / failure tests。
- 不得把上述測試描述成 live GitHub webhook / live provider Production Ready。

不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth，也不要重做 Supervisor 架構。只修以下剩餘 correctness / evidence blocker。

---

## 1. Blocker A — GitHub API fallback 使用 `origin/main`，實際 GitHub compare endpoint 會 404

目前 engine 的 recovery 呼叫：

```python
get_commits_since(contract.instruction_sha, f"origin/{self.config.allowed_branch}")
```

而 `GitHubClient.get_commits_since()` local git 失敗時直接組：

```python
/repos/{repo}/compare/{base_sha}...{head_sha}
```

因此 fallback URL 會變成：

```text
compare/<base>...origin/main
```

這不是 GitHub repository branch ref。外部 Re-Gate 已用 repo 的 compare API 驗證：`head=origin/main` 回 **404 Not Found**。

所以 Round 7 要求的這條仍未成立：

> local git unavailable，但 GitHub API discovery 成功且找到 exact candidate → adopt exactly once

### Required correction

1. `get_commits_since()` 必須區分 local git ref 與 GitHub API ref。
2. local path 可以使用 `origin/main`；remote API fallback 必須 normalize 成 GitHub 可解析的 ref，例如 `main`，或明確傳入 `remote_head_ref`。
3. 禁止用字串猜測造成任意 ref 改寫；至少只允許安全地把前綴 `origin/` 正規化成 branch name，其他 ref 保留 exact SHA/tag/branch。
4. GitHub compare 404 / 409 / 5xx / timeout 仍必須 fail closed，不得回空列表。
5. API fallback 回傳的 `commit.message` 必須完整保留 6 trailers。

### Required tests — 必須補，不可只測 Fake client

新增真實 `GitHubClient` + mocked HTTP transport / subprocess failure integration cases：

- local `git log` 明確失敗，輸入 `head_sha="origin/main"`；驗證 remote API request 使用 `...main`，不能是 `...origin/main`。
- API compare 回一個含完整 6 trailers 的 exact candidate → engine adopt exactly once，不新增第二個 instruction commit。
- API compare 回 404 → `GitHubVerificationError`，no new commit。
- API compare 200 且真的是 0 commits → 才允許走「0 verified candidates」後續。
- API response commit body 含 newline / `|` / 6 trailers，仍可 exact verify。

請把這條視為 live crash-recovery correctness blocker，不是測試美化。

---

## 2. Blocker B — Round 7 的 required test matrix 尚未完整實作

目前新測試主要覆蓋：

- local temp git trailer preservation
- Fake client discovery failure
- REST last-page comments
- comments fetch failure

但上一輪明確要求的以下案例尚未看到真實 client integration coverage：

- `local git unavailable + GitHub API discovery success + exact candidate adopt exactly once`
- staged SHA + remote fallback success path
- ACCEPT / CHANGES_REQUIRED / BLOCKED 三種 decision 的 Window B2 exactly-once 路徑，在 `gh` unavailable + REST fallback 下都要覆蓋
- pagination marker 不只「能讀到」，還要證明 engine 因 marker 已存在而 **不再 POST**

### Required correction

補最小必要 integration tests，不要為了數量重寫測試框架。測試要走真正 `GitHubClient` 方法；可以 mock network/subprocess，但不能只餵 `MockGitHubClient` 已整理好的結果。

---

## 3. Blocker C — 尚未形成可驗收的 Round 7 完整 handoff / exact evidence lineage

目前 main 上：

- `docs/GROK_PROGRESS_REPORT.md` 仍停在 Round 6，`CODE_EVIDENCE_SHA=2bc44ac...` / `762 passed / 64 Supervisor tests`。
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md` 仍停在 Round 6 / 64 scenarios。
- Issue #1 最新 READY 回報仍是舊 Round 6 lineage，沒有 `d4445058...` 的 machine-readable READY contract。
- `d4445058...` 的 CODE Actions `34786792942` 在本次 Re-Gate 時尚未雙平台完成；Windows 已 SUCCESS，Ubuntu仍在 regression tests。

因此 `d4445058...` 現在只能列：

- code correction：**REAL_LOGIC / PARTIAL**
- tests：**LOCAL/CI-IN-PROGRESS，尚不能作 exact dual-platform green evidence**
- webhook real E2E：**BLOCKED / false**
- live provider production invocation：**BLOCKED / false**
- event-driven production readiness：**BLOCKED / false**

### Required completion sequence

修完 Blocker A+B 後：

1. 新 CODE commit。
2. `pytest -v tests/test_supervisor.py` + `pytest -q` 全綠。
3. 新 CODE SHA 的 Ubuntu + Windows Actions SUCCESS。
4. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md`（若存在）
   - `docs/REAL_E2E_ACCEPTANCE.md` 只有 truth/status 真有變時才更新；不得為了讓文件變新而偽造 REAL evidence。
   - `docs/CABINET_REAL_ACCEPTANCE.md` 若本輪 cabinet truth 沒變，保持原內容即可。
5. 新 DOCS SHA 的 Ubuntu + Windows Actions SUCCESS。
6. Issue #1 留 machine-readable `READY_FOR_RE_GATE`：
   - `INSTRUCTION_SHA`
   - `CODE_SHA`
   - `DOCS_SHA`
   - `CODE_CI_RUN_ID`
   - `DOCS_CI_RUN_ID`
   - `TEST_COUNT`
   - `EVIDENCE_GENERATION_ID`
   - `REAL_BLENDER`
   - `USED_MOCK`
7. STOP，等 external Re-Gate。不得自行把 readiness flags 改成 true。

---

## 4. REAL / MOCK / PARTIAL / BLOCKED 邊界

本輪維持：

- Supervisor core logic：**REAL_LOGIC / TESTED**
- Round 7 local trailer preservation：**REAL_LOGIC / TESTED**
- discovery fail-closed：**REAL_LOGIC / TESTED**
- REST latest-page comments fetch：**REAL_LOGIC / TESTED**
- remote GitHub compare fallback for `origin/main`：**BLOCKED / BUG CONFIRMED**
- Window B1 full live recovery：**PARTIAL / NOT LIVE-VERIFIED**
- Window B2 exactly-once：**PARTIAL / NOT LIVE-VERIFIED**
- external provider adapters：**REAL_LOGIC / ADAPTER**；live configured provider production invocation尚未證實
- GitHub Actions：**TESTED / MOCK_BLENDER CI**，不是 REAL Blender production evidence
- Product Truth existing Blender evidence：可保留原 scoped **REAL Blender evidence**；本輪沒有新的 Blender truth claim
- Webhook real E2E：**BLOCKED / false**
- `liveProviderReady=false`
- `eventDrivenSupervisorReady=false`
- `commercialAssetProductionReady=false`
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`
- LIVE_CNC / LIVE_LASER / PLC / machine control：**BLOCKED**
- **Phase 961+ HOLD**

Mock / fixture / MockTransport / local HTTP test 一律不得描述成 Production Ready。

---

## 5. Round 8 完成後才可進真正 live E2E gate

只有上述 corrections + 新 CODE/DOCS exact dual-platform green 都完成，才可進最後 live gate：

`authorized Issue READY -> real GitHub webhook delivery -> HMAC verified -> exact contract/CI/evidence -> real configured provider network call -> 4 identities exact -> exactly one instruction commit -> exactly one Issue comment -> watcher claim exactly once -> replay no duplicate`

如果環境仍缺真 webhook endpoint / GitHub webhook secret / live provider credential，明確標 `BLOCKED_WAITING_LIVE_E2E`，三個 readiness flags保持 false；禁止用 MockTransport / fixture 代替。
