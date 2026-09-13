# Development Agent 修正指令：Event-Driven Supervisor Re-Gate Round 2 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed Supervisor CODE: `5c7568d4d9746dc2b1e49504ef3ab88915da6f6c`
> Reviewed docs/head: `bbbca2877c74cf7915e5b48b1e8b36700ebf0ded`
> CODE Actions: `34760915984` — Ubuntu `103733478803` SUCCESS / Windows `103733478898` SUCCESS
> DOCS Actions: `34761701358` — Ubuntu `103735563841` SUCCESS / Windows `103735563972` SUCCESS
> Reported regression: **727 passed**; Supervisor-specific: **29 passed**
> Re-Gate result: **CHANGES REQUIRED**
> `WEBHOOK_REAL_E2E=false`; `EVENT_DRIVEN_READY=false` 必須維持。
> **Phase 961+ remains HOLD.**

## 0. 本輪已接受的修正 — 保留，不要重寫

本輪相較 `872da20` 有實質進展，以下可接受並應保留：

- 已加入 Issue sender authorization、`action == created` 過濾與 wrong-repo 基本檢查。
- delivery lifecycle 已由單一 seen bit 擴充為 `RECEIVED / PROCESSING / COMPLETED / FAILED_RETRYABLE / FAILED_TERMINAL`。
- 已加入 `staged_commit_sha`，可處理一部分「instruction push 完成後、Issue comment 前」的恢復情境。
- live mode 的 push failure 已不再直接吞掉並宣告成功。
- 已加入 diff 取得與 `SemanticEvidenceSupervisorAdapter`，不再完全只看 READY contract。
- live mode 已有 webhook secret / GitHub token / sender / provider 基本 fail-closed，以及 Supervisor observability admin auth。
- Exact CODE `5c7568d` 與 docs `bbbca28` 的 GitHub Actions 均為 Ubuntu + Windows SUCCESS。
- 727 full regression / 29 Supervisor tests 為有效軟體測試證據，但仍不是 REAL webhook Production evidence。
- 文件正確保留 `webhookRealE2e=false`、`eventDrivenSupervisorReady=false`，也保留 LIVE_CNC / LIVE_LASER / PLC / physical print / live providers 等既有 BLOCKED 邊界。

不要重寫既有 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth 架構。以下只做 Supervisor correction-only。

---

## 1. Blocker A — webhook envelope 仍需真正 fail-closed

目前 `main.py` 的 repo 判斷是：只有 `payload.repository.full_name` 非空時才比較；如果 `repository` 或 `full_name` 缺失，事件會繼續往下處理。這不符合「exact repo match」要求。

另外 live mode 目前允許空的 `X-GitHub-Delivery`，這會直接失去 delivery dedupe / replay lifecycle 保護。

### Required correction

1. `issue_comment` READY trigger 必須要求：
   - `payload.repository.full_name` **存在且 exact match** `netfox-web/blender-autonomous-3d`；缺失直接 terminal reject。
   - `X-GitHub-Delivery` 在 `SUPERVISOR_MODE=live` 必須存在且非空；缺失 fail closed。
   - `X-GitHub-Event == issue_comment` 且 `action == created`。
   - Issue number exact match `1`。
2. sender authorization 保留現有 allowlist / signed `author_association` default-deny；不可因 body 內容繞過。
3. 補 negative tests：missing repository、missing `full_name`、missing delivery id in live、missing/incorrect event header、wrong issue、outsider。

---

## 2. Blocker B — crash recovery 仍有兩個未封閉 window

目前 `staged_commit_sha` 只在 `commit_instruction_file()` 成功 return 後才寫進 SQLite，因此仍有：

### Window B1 — remote push 已成功，但 process 在 return / `set_review_staged_commit()` 前 crash

GitHub 已有 instruction commit，但 DB 尚未記錄。Retry 可能再次 commit，或遇到 `nothing to commit` / lineage 漂移。

### Window B2 — Issue comment 已成功，但 process 在 `complete_review()` 前 crash

Retry 會重用 staged commit，但仍可能再次 `add_issue_comment()`，造成 duplicate `SUPERVISOR_REVIEW_COMPLETE`。

### Required correction

建立 durable GitHub-write state，至少：

- `instruction_commit_sha`
- `instruction_remote_verified_at`
- `issue_comment_id`
- `issue_comment_posted_at`
- `review_write_stage`：`NONE / INSTRUCTION_PUSHED / COMMENT_POSTED / COMPLETED`

規則：

1. Retry 前先 reconcile remote：若遠端已存在本 review 的 deterministic instruction commit / marker，直接 adopt，不得再 commit。
2. Issue comment 必須帶 deterministic review marker，例如 `REVIEW_ID=<review_id>` 或 `(CODE_SHA,EVIDENCE_GENERATION_ID)`，retry 時先查 Issue #1 是否已有該 marker；已有則 adopt comment id，不得重貼。
3. `complete_review()` 只能在 instruction remote verified + comment persisted/adopted 後執行。
4. 若 push 失敗而本機已產生 commit，retry 必須先回復到 verified remote base；不能讓 local orphan commit 導致 `nothing to commit` 永久卡死。
5. 補真正 subprocess/crash tests：
   - crash after remote push before staged DB write；
   - crash after comment POST before DB write；
   - retry 後 instruction commit count = 1；
   - retry 後 Issue review comment count = 1。

---

## 3. Blocker C — Git write preflight / remote verification 尚未達要求

目前 live write 有 fetch、dirty tree、push return code、remote HEAD SHA 驗證，但仍缺：

- fetch 後沒有證明 local `HEAD` / current branch exact 等於 `origin/main`；
- 沒有明確禁止在 detached HEAD / 非 main branch 上寫入；
- push 後只驗 `origin/main == new_sha`，沒有驗遠端 instruction file 的 blob/content；
- push failure 後 local commit recovery 未封閉。

### Required correction

1. live write 前：
   - `git fetch origin main`；
   - current branch 必須是 configured `main`；
   - local `HEAD == origin/main`；否則 fail/reconcile，不可直接寫；
   - working tree + index 都必須 clean，且不能帶 unrelated staged files。
2. Commit 只允許 instruction path（與 neutral alias 若同時更新）。
3. Push 使用明確 refspec 或等價安全方式，禁止不確定 current branch 的 `git push origin main`。
4. Push 後：
   - remote main exact contains/equals resulting commit；
   - 重新從 GitHub API/remote blob 讀取 `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md`（以及 alias 若更新），驗 SHA/content exact match intended payload。
5. push failure / non-fast-forward / remote mismatch 必須標 `FAILED_RETRYABLE`，並留下可安全 retry 的乾淨 local state。
6. 新增 tests：local HEAD behind/ahead、detached HEAD、non-main branch、non-fast-forward、remote file mismatch、push success DB crash、comment success DB crash。

---

## 4. Blocker D — `SemanticEvidenceSupervisorAdapter` 仍不是可獨立 ACCEPT 的真 Re-Gate authority

目前新增 adapter 仍只是 deterministic 字串/regex heuristic。它不是 `openai / anthropic / gemini / external provider` 的實際 provider adapter；而且 `create_app()` 在 live mode 不論 `SUPERVISOR_AI_PROVIDER` 寫什麼，最後都直接建立 `SemanticEvidenceSupervisorAdapter()`。

因此目前設定 `SUPERVISOR_AI_PROVIDER=openai` / `anthropic` / `gemini` 並不會真的呼叫該 provider，卻可通過 live config validation，這屬於 readiness 誤導。

另外 review evidence 目前仍有 lineage 問題：

- progress / audit / acceptance / instruction 是從 configured branch `main` 讀，不是從 contract 的 exact `DOCS_SHA` / `INSTRUCTION_SHA` 讀；main 在 review 期間若前進，可能審到錯版本。
- `CABINET_REAL_ACCEPTANCE.md` 沒進 ReviewContext。
- current progress report 仍是 Phase 901–960 Product Content R1 舊內容；現有 heuristic 只檢查「非空」，無法偵測 stale report。
- 只驗 CODE CI；沒有獨立驗 DOCS SHA 對應的 CI。
- diff 取得失敗回傳空字串時，adapter 仍可能 ACCEPT。
- REAL/MOCK 判斷以關鍵字掃描整份文件，容易 false positive / false negative，不能作最終 acceptance authority。

### Required correction

1. 把 `SemanticEvidenceSupervisorAdapter` 降為 **deterministic preflight / safety filter**。在 live mode 它可以拒絕或要求修正，但**不得單獨產生 ACCEPT_WITH_SCOPE**。
2. 建立真正 provider-neutral live adapter factory：
   - `SUPERVISOR_AI_PROVIDER=<supported provider>` 必須映射到實際 adapter implementation；
   - provider 不存在、key 缺失、timeout、invalid schema -> fail closed；
   - 若要保留 `semantic_evidence`，其 live 能力只能是 preflight，除非另有真正 review provider 接手 final decision。
3. 所有 evidence 必須 pin 到 exact SHA：
   - progress/audit/REAL_E2E/CABINET acceptance 讀 `contract.docs_sha`；
   - instruction 讀 `contract.instruction_sha`；
   - diff = `instruction_sha...docs_sha`；
   - commits 同一 lineage；
   - missing/empty diff（在本應有 code changes時）或 fetch failure -> 不得 ACCEPT。
4. ReviewContext 至少加入：
   - `GROK_PROGRESS_REPORT.md` / `AGENT_PROGRESS_REPORT.md`
   - `CURRENT_IMPLEMENTATION_AUDIT.md`
   - `REAL_E2E_ACCEPTANCE.md`
   - `CABINET_REAL_ACCEPTANCE.md`
   - `EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md`
   - exact instruction text
   - exact CODE CI + DOCS CI summaries
   - changed files + diff / bounded file contents
5. progress report 必須驗 lineage markers，不可只判斷 non-empty：至少核對 instruction SHA、CODE SHA、DOCS/evidence generation id、test count、CI run id。
6. structured output 仍須 schema validation + policy guardrail；provider 不可直接 shell / GitHub write。
7. adversarial tests：
   - provider name 宣告 openai 但實際 adapter 未初始化 -> startup fail；
   - stale progress report -> CHANGES_REQUIRED；
   - main 前進但 docs_sha 固定 -> reviewer 只能看到 pinned docs；
   - empty diff/fetch failure -> no ACCEPT；
   - contract says REAL but pinned acceptance contradicts -> no ACCEPT；
   - unrelated `mock` 字樣不能誤判整個 REAL evidence。

---

## 5. Blocker E — live config 必須驗「真的可用」，不是只有字串非空

### Required correction

1. `SUPERVISOR_AI_PROVIDER` 使用 strict allowlist；未知字串必須 startup fail。
2. 需要 API credential 的 provider 必須要求對應 key，不能 `provider=openai` + empty key 還能啟動。
3. admin endpoint 採 admin key 時，live mode 建議直接要求 non-empty `SUPERVISOR_ADMIN_KEY`；若選 private-bind 模式則需明確 config，不能隱含公開 `0.0.0.0`。
4. storage writable 不只 `mkdir` parent；startup 要實際 open/write/flush 或 SQLite transaction smoke test，audit log 也要可寫。
5. GitHub token 權限不足 / repo 不可讀寫應在 live startup 或 preflight 明確 fail closed。
6. secret/token/API key 不得進 log / review output / Issue comment。

---

## 6. REAL webhook E2E 仍是 mandatory gate

完成上述 correction 後才做 REAL E2E；在此之前不得把 727/29 tests 當 event-driven ready。

REAL acceptance 必須完整證明：

1. 真 GitHub Issue #1 authorized `READY_FOR_RE_GATE` comment。
2. 真 GitHub delivery ID + HMAC verify。
3. exact repo / sender / issue / action / delivery id fail-closed。
4. exact CODE_SHA / DOCS_SHA / INSTRUCTION_SHA lineage。
5. CODE Ubuntu+Windows CI success + DOCS Ubuntu+Windows CI success。
6. deterministic preflight + real configured review provider final structured decision。
7. exactly one remote instruction commit。
8. remote instruction blob/content exact verify。
9. exactly one `SUPERVISOR_REVIEW_COMPLETE` Issue comment。
10. watcher claim exactly once。
11. replay same delivery / duplicate READY -> no second commit/comment。
12. 至少一次真實 crash-window recovery proof（push-after-crash 或 comment-after-crash）。

Acceptance doc 必須記錄 delivery id、review id、provider、reviewed CODE/DOCS/INSTRUCTION SHA、CI run/job IDs、instruction commit SHA、Issue comment id、watcher claim SHA、timestamps。

只有這條真實鏈全部完成後，才可提議：

- `webhookRealE2e=true`
- `eventDrivenSupervisorReady=true`

仍需下一次 Re-Gate 才能接受，不得 self-promote。

---

## 7. Product / manufacturing truth boundaries 不變

Supervisor side-track 不得解除既有產品與製造 blocker：

- Phase 901–960 Product Content Round 2 blockers 仍是 open lineage；
- **Phase 961+ HOLD**；
- live H3 MAX / LTX 2.5 = BLOCKED；
- Vision Judge = MOCK/BLOCKED；
- physical print = false/BLOCKED；
- LIVE_CNC / LIVE_LASER / PLC / machine control = BLOCKED；
- `commercialAssetProductionReady=false`；
- `globalProductionReady=false`；
- `fullAutonomousFactoryReady=false`；
- `liveFactoryExecutionReady=false`。

完成 correction + exact dual-platform CI + REAL webhook E2E 後，停止並回報 Re-Gate。不要開始 Phase 961+。