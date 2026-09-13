# Development Agent 修正指令：Event-Driven Supervisor Re-Gate Round 7 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed instruction: `5d9dd9b3b765206ef1fd959ba6f899f5e4ccebbd`
> Reviewed CODE: `2bc44acdd985b5d29ac3a1a3a40fa63d21fc244f`
> Reviewed DOCS/head: `85bbf9b6a141f2727852726a850d622284da13c5`
> CODE Actions: `34783581901` — Ubuntu + Windows SUCCESS
> DOCS Actions at review time: `34784713920` — **IN_PROGRESS**，不可當 exact DOCS green evidence
> Reported regression: **762 passed**; Supervisor-specific: **64 passed**
> REAL Blender generation reported: `50a84d04-85c2-429d-8c12-641006ac95f1`
> Re-Gate result: **CHANGES REQUIRED (Round 7)**
> `webhookRealE2e=false`; `eventDrivenSupervisorReady=false`; `liveProviderReady=false` 必須維持。
> **Phase 961+ remains HOLD.**

## 0. 本輪已接受的實質進展 — 保留，不要重寫

Round 6 的大部分修正可保留為 **REAL_LOGIC / TESTED**：

- provider schema 與 4 reviewed identities 綁定保留。
- `docs/REAL_E2E_ACCEPTANCE.md` 已與 Product Truth auxiliary acceptance 分離；REAL Blender claim 不得 fallback。
- CODE diff / DOCS diff 已拆成不同 range，changed-file manifest 已加入 independent authority 比對。
- strict `DOCS_CI_RUN_ID` parser boundary 與 provider request ID audit 已加入。
- intended instruction SHA256、6 trailers、6 identity markers、review-id continuity 的設計方向正確。
- CODE `2bc44ac...` Actions `34783581901` 已確認 Ubuntu + Windows SUCCESS。
- `762 passed` / `64 Supervisor tests` 可作軟體 regression 證據；CI 仍使用 `FOX3D_MOCK_BLENDER=1`，不得描述為 REAL Blender / Production Ready。
- REAL Blender generation `50a84d04-...` 可保留為 scoped Product Truth render evidence；它不是 live Supervisor webhook/provider E2E。
- readiness truth boundary 正確：`webhookRealE2e=false`、`eventDrivenSupervisorReady=false`、`liveProviderReady=false`。

不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth，也不要重做 Supervisor 架構。只修下列 live-client / crash-recovery correctness 問題。

---

## 1. Blocker A — 真實 `GitHubClient.get_commits_since()` 會丟掉 commit trailers，Window B1 recovery 在 live client 實際上無法成立

目前 `services/supervisor/github_client.py` 的 local-git fast path 使用：

```text
git log <base>..<head> --pretty=format:%H|%an|%s
```

`%s` 只回 commit **subject**，不包含 body / trailers。

但 `SupervisorEngine._verify_instruction_candidate()` 要求從 `commit_msg` 解析：

- `Reviewed-Code-Sha`
- `Reviewed-Docs-Sha`
- `Reviewed-Instruction-Sha`
- `Reviewed-Evidence-Id`
- `Supervisor-Decision`
- `Supervisor-Review-Id`

因此在真實 `GitHubClient` local path 下，remote/staged candidate 即使 commit 本身有完整 6 trailers，`get_commits_since()` 回給 engine 的 message 仍只有 subject，candidate 會被錯誤 reject。這代表目前文件宣稱的「Window B1 exact recovery」尚未在真實 client path 成立；mock `FakeGitHubClient` 直接給完整 message 的測試不能證明這一點。

### Required correction

1. `get_commits_since()` 必須回傳 **完整 commit message body**，不能只取 `%s`。
2. 建議使用不會被 commit message 中 `|` / newline 破壞的 framing，例如 NUL / record separator：
   - `%H%x00%an%x00%B%x00...`
   - 或逐 commit `git show -s --format=%B <sha>`。
3. 回傳的 `message` 必須包含 trailers 原文，供 `_verify_instruction_candidate()` exact parse。
4. 不得用 subject 補猜 trailers，也不得重新從 short SHA 推導。
5. GitHub API fallback 若使用 commits endpoint，也必須取 `commit.message` 完整內容。

### Required tests

新增 **real `GitHubClient` integration test**，不要只測 Fake client：

- temp git repo 建立一個 instruction commit，subject + 6 trailers 位於 body。
- `get_commits_since()` 回傳的 message 必須包含完整 6 trailers。
- engine 用真實 client path 可 adopt exact candidate exactly once。
- 缺任一 trailer仍 fail closed。
- commit message body 含 newline / `|` 不得破壞 parser/framing。

---

## 2. Blocker B — Recovery candidate enumeration 失敗目前會被當成「0 candidates」，可能反而新增第二個 instruction commit

目前 `get_commits_since()` local `git log` 發生 exception / non-success /解析失敗時，最終可能直接 `return []`。Engine 的 Window B1 邏輯把：

```text
0 matching candidates => create a new instruction commit
```

視為正常情況。

但「真的沒有 candidate」與「candidate enumeration 自己壞掉」不能等價。若 crash 已經發生在 push 成功後、DB 尚未記錄之前，此時 enumeration transient failure 被轉成 `[]`，就可能建立第二個 instruction commit，正好違反 Window B1 的核心目的。

### Required correction

1. candidate discovery 必須區分：
   - `SUCCESS_WITH_ZERO_COMMITS`
   - `SUCCESS_WITH_COMMITS`
   - `DISCOVERY_FAILURE`
2. live mode 下，`git log` / remote discovery / parse error 不得 silent `[]`；必須 raise typed `GitHubVerificationError` 或等價 fail-closed result。
3. Engine 只有在「成功完成 candidate enumeration，且 verified matching candidate 數量確實為 0」時才可 create new instruction commit。
4. 若 staged SHA 存在，而 remote enumeration failure，必須停住 retry，不能建立新 commit。
5. 若 local git discovery 失敗，可 fallback GitHub compare/commits API；但 API 也失敗時必須 fail closed。

### Required tests

- crash-after-push + DB 無 staged record + `git log` failure → **不得**建立第二個 commit。
- staged SHA exists + enumeration timeout → no new commit。
- local git unavailable但 GitHub API discovery成功且找到 exact candidate → adopt exactly once。
- local + API 都失敗 → CHANGES_REQUIRED / retryable failure，不新增 instruction commit。

---

## 3. Blocker C — Window B2 REST fallback 目前不保證拿到「最新」Issue comments

`GitHubClient.get_latest_issue_comments()` 的 `gh` CLI path 會取 `.comments[-count:]`，但 CLI 失敗後 REST fallback 使用：

```text
/issues/{issue_number}/comments?per_page={count}
```

GitHub Issue comments API 預設分頁從第一頁開始；當 Issue #1 已有大量留言時，這不等於 latest comments。若 `gh` 不存在/失敗，Window B2 recovery 可能看不到剛剛已 POST 的 deterministic marker，接著再 POST 一次，造成 duplicate comment。Issue #1 現在留言數已很多，這已是實際風險，不是理論問題。

### Required correction

1. REST fallback 必須真的取 latest `count` comments：
   - 正確處理 pagination / `Link` last page；或
   - 可靠取得總頁數後抓最後頁，再 slice newest `count`。
2. 回傳順序要固定且明確（建議 oldest→newest 的 latest window，或 newest→oldest，但 engine/tests 必須一致）。
3. Window B2 deterministic marker search 不可依賴 `gh` CLI 存在。
4. API transient failure 必須 fail closed/retry，不可把「讀不到 comment」視為「comment 不存在」。

### Required tests

- 模擬 Issue 有 >100 comments，marker 在最後 5 筆；REST fallback 必須找到。
- `gh` command unavailable + REST fallback → 不重複 POST。
- REST pagination/API error → no duplicate comment；retryable failure。
- ACCEPT / CHANGES_REQUIRED / BLOCKED 三條 B2 路徑都驗證 exactly-once。

---

## 4. Blocker D — exact DOCS CI 尚未完成，本輪不能 ACCEPT

本次 Re-Gate 時 `main` = `85bbf9b6a141f2727852726a850d622284da13c5`，其 Actions run `34784713920` 仍為 **IN_PROGRESS**，Ubuntu / Windows 都仍在 `Unit / regression tests`。

所以就算上述 live-client recovery bugs 不存在，本輪也還沒有 exact DOCS SHA 雙平台 SUCCESS 證據。

Round 7 修正完成後重新形成新的 exact lineage：

1. 新 CODE commit。
2. `pytest -v tests/test_supervisor.py` + `pytest -q` 全綠。
3. CODE SHA 的 Ubuntu + Windows Actions SUCCESS。
4. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`（若 truth/status 有變才改；不得為了數字硬改 REAL evidence）
5. 新 DOCS SHA 的 Ubuntu + Windows Actions SUCCESS。
6. Issue #1 machine-readable READY contract 必須帶 exact：
   - `INSTRUCTION_SHA`
   - `CODE_SHA`
   - `DOCS_SHA`
   - `CODE_CI_RUN_ID`
   - `DOCS_CI_RUN_ID`
   - `TEST_COUNT`
   - `EVIDENCE_GENERATION_ID`
   - `REAL_BLENDER`
   - `USED_MOCK`
7. STOP 等 external Re-Gate；不得自行把 readiness flags改成 true。

---

## 5. REAL / MOCK / PARTIAL / BLOCKED 邊界

本輪維持：

- Supervisor core logic：**REAL_LOGIC / TESTED**
- Round 6 exact identity/digest design：**PARTIAL**，因真實 `GitHubClient` recovery message path 目前會丟 trailers
- Window B1 crash recovery：**PARTIAL / NOT LIVE-VERIFIED**
- Window B2 comment exactly-once：**PARTIAL / NOT LIVE-VERIFIED**，REST fallback latest-page bug 尚未修
- external provider adapters：**REAL_LOGIC / ADAPTER**；live configured provider production invocation 尚未證實
- GitHub Actions：**TESTED / MOCK_BLENDER CI**，不是 REAL Blender production evidence
- Product Truth Blender generation `50a84d04-...`：可保留 **REAL Blender scoped evidence**
- Webhook real E2E：**BLOCKED / false**
- Live provider production ready：**BLOCKED / false**
- Event-driven Supervisor production ready：**BLOCKED / false**
- Physical print：**BLOCKED / false**
- LIVE_CNC / LIVE_LASER / PLC / machine control：**BLOCKED**
- `commercialAssetProductionReady=false`
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`
- **Phase 961+ HOLD**

Mock / fixture / local HTTP transport tests一律不得描述成 Production Ready。

---

## 6. 修完 Round 7 後才進真正 live E2E gate

只有 A–D 全修並取得 new CODE + DOCS exact dual-platform green，才可進最後 live gate：

`authorized Issue READY -> real GitHub webhook delivery -> HMAC verified -> exact contract/CI/evidence -> real configured provider network call -> 4 identities exact -> exactly one instruction commit -> exactly one Issue comment -> watcher claim exactly once -> replay no duplicate`

Acceptance evidence 必須保存：GitHub delivery ID、review ID、provider/model/request id、CODE/DOCS/prior INSTRUCTION、evidence id、CI run/job ids、instruction content digest、result instruction SHA、Issue comment ID、watcher claim、timestamps/retry count。

若環境尚無真 webhook endpoint / credential / live provider credential，明確標 `BLOCKED_WAITING_LIVE_E2E`，三個 readiness flags保持 false；禁止用 MockTransport / local fixture 代替。

完成修正後 push CODE -> 等 CODE CI -> 更新 DOCS -> 等 DOCS CI -> Issue #1 READY -> STOP。
