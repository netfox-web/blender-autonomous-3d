# Development Agent 指令：Event-Driven Supervisor Re-Gate Round 9 — LIVE E2E PRODUCTION GATE

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed instruction: `0cb8faa1ff7cf0ac9b6f4f3f3dfd38f766a28872`
> Accepted CODE: `d9402f3a966581aa66d39b0097e518366d87626c`
> Accepted DOCS: `aa12ca3504532830c494cf1edf750dd84a9bd664`
> CODE Actions: `34788079332` — Ubuntu + Windows SUCCESS
> DOCS Actions: `34789286472` — Ubuntu + Windows SUCCESS
> Tests: `72 passed` in `tests/test_supervisor.py`; `770 passed` full regression
> Evidence generation: `1631af33-6946-4ac9-96eb-b844d68892c9`
> Re-Gate result: **ACCEPT WITH SCOPE / GO LIVE E2E GATE**
> **Phase 961+ remains HOLD.**

## 0. Round 8 驗收結論 — 已接受，禁止重寫

Round 8 corrections 已通過 scoped Re-Gate：

- `origin/main` → GitHub compare API ref normalization 已修正，remote fallback 不再用 `origin/main` 造成 404。
- compare 404/409/5xx / transport failure 走 fail-closed，不再偽裝成 0 commits。
- local git unavailable → GitHub API fallback → full commit body / 6 trailers extraction 已有真 `GitHubClient` integration coverage。
- staged SHA + remote fallback candidate adoption exactly-once 已覆蓋。
- REST comment pagination + existing marker → ACCEPT / CHANGES_REQUIRED / BLOCKED 三 decision 不重複 POST 已覆蓋。
- exact CODE/DOCS 雙 CI 已綠；進度報告、Audit、Supervisor Acceptance 已更新。
- Truth boundary 正確維持：`eventDrivenSupervisorReady=false`、`webhookRealE2e=false`、`liveProviderReady=false`。

以上列為 **REAL_LOGIC / TESTED**，不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth，也不要再改 Round 1–8 已通過的邏輯，除非 LIVE E2E 暴露可重現 correctness bug。

MockTransport、pytest、GitHub Actions、fixture webhook 都不能把 readiness flags 改成 true。

---

## 1. 本輪唯一主目標：跑通一次真正 GitHub Webhook → Live Provider → GitHub Write → Watcher Claim 的完整事件鏈

必須使用真實 GitHub delivery 與真實外部 AI provider network request，不接受模擬代替。

目標鏈：

```text
Authorized Issue #1 READY_FOR_RE_GATE comment
  -> GitHub 真 webhook delivery
  -> public/live supervisor endpoint
  -> HMAC-SHA256 verified
  -> repository / issue / action / commenter authorization verified
  -> exact machine-readable contract parsed
  -> CODE_SHA + DOCS_SHA reachable on main
  -> exact CODE_CI_RUN_ID + DOCS_CI_RUN_ID dual-platform SUCCESS verified
  -> pinned evidence / audit / acceptance fetched at exact SHAs
  -> REAL/MOCK/PARTIAL/BLOCKED deterministic preflight
  -> REAL configured AI provider network request
  -> schema-valid response + provider request ID
  -> 4 reviewed identities exact-match
  -> exactly one `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` commit
  -> remote blob exact verification
  -> exactly one Issue #1 handoff comment
  -> Antigravity watcher claims new instruction SHA exactly once
  -> replay same delivery / same READY contract creates no duplicate commit, comment, or claim
```

只有完整鏈條全部有 live evidence 才可完成本輪。

---

## 2. Live prerequisite 必須 fail-closed，不得自行偽造

Live run 前確認實際環境具備：

- 可由 GitHub webhook 訪問的 HTTPS endpoint。
- `GITHUB_WEBHOOK_SECRET` 已設定且與 repo webhook 相同。
- GitHub credential / App token 具備目前已使用的 read/write 權限。
- `SUPERVISOR_AI_PROVIDER` 明確為 `openai` / `anthropic` / `gemini` 之一。
- `SUPERVISOR_AI_MODEL` 與 provider 相容且非空。
- 對應 provider API credential 可做真實 network request。
- Live admin/status auth key 正常。
- `main`、Issue #1、allowed repo/branch policy 必須與目前設定一致。

### 若任一 prerequisite 缺失

不要用 MockTransport、fixture server、手工 fabricated provider response、curl 偽裝 GitHub delivery 或手工改 DB 代替。

請：

1. 將狀態寫為 `BLOCKED_WAITING_LIVE_E2E`。
2. 明列缺少的 prerequisite 類型，但禁止把 secret/token 值寫入 log/docs/Issue。
3. 維持：
   - `webhookRealE2e=false`
   - `liveProviderReady=false`
   - `eventDrivenSupervisorReady=false`
4. 更新 handoff docs + Issue #1 後 STOP。

這種情況不是程式失敗，是 live infrastructure / credential blocker；不得改用 mock 取得 PASS。

---

## 3. Live E2E 必須留下可獨立驗證的 evidence

新增或更新 `docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md`，至少記錄以下非秘密證據：

### A. GitHub webhook evidence

- GitHub delivery ID（`X-GitHub-Delivery`）
- event/action
- repository full name
- Issue number
- commenter login / authorization result
- HMAC verification result `true`
- received timestamp
- contract fingerprint / review ID
- 不得保存 raw secret / token / Authorization header

### B. Exact contract / CI lineage

- `INSTRUCTION_SHA`
- `CODE_SHA`
- `DOCS_SHA`
- `CODE_CI_RUN_ID`
- `DOCS_CI_RUN_ID`
- `EVIDENCE_GENERATION_ID`
- `REAL_BLENDER`
- `USED_MOCK`
- Ubuntu + Windows job IDs / conclusions

所有 SHA/Run ID 必須從 live run 實際驗證，不可只複製 README 宣告。

### C. Live provider evidence

- provider name
- configured model
- provider request ID / response ID（若 provider 回傳）
- HTTP/network request 確實發生的 audit marker
- response schema validation PASS
- provider 回傳的：
  - `reviewedCodeSha`
  - `reviewedDocsSha`
  - `reviewedInstructionSha`
  - `reviewedEvidenceGenerationId`
- 四項必須 exact-match contract；任一 mismatch → fail closed。
- 不得寫入 API key、完整 Authorization header 或 secret。

### D. GitHub write exactly-once evidence

記錄：

- instruction commit SHA
- commit 的 6 trailers
- intended instruction SHA256 digest
- pushed branch/ref
- remote blob SHA/content digest verification PASS
- Issue #1 handoff comment ID
- deterministic comment marker / review ID

### E. Watcher claim evidence

記錄：

- watcher 看見的 instruction SHA
- claim timestamp
- durable claim/state key
- claim count = 1
- watcher 不得因 Supervisor 自己的 commit/comment loop 再啟動同一 review。

---

## 4. 必做 replay / crash exactly-once 驗收

Live success 一次還不夠。至少再驗證：

1. **Replay same GitHub delivery ID**
   - supervisor 回 deduplicated/ignored status。
   - 不新增 instruction commit。
   - 不新增 Issue comment。
   - watcher claim 不增加。

2. **Replay same READY contract with new delivery**
   - contract identity dedupe 生效。
   - 不新增第二組 GitHub write。

3. **Window B1/B2 live-state reconcile**
   - 如果 live 環境允許安全注入 crash point，只能在 Supervisor 的 instruction/comment control-plane write 上測，不得碰 LIVE_CNC/LASER/PLC。
   - restart 後 existing remote commit/comment 必須 adopt，不得 duplicate。
   - 如果 production endpoint 不允許安全 crash injection，明確標 `LIVE_CRASH_INJECTION_NOT_EXECUTED`，保留既有 integration evidence，不得聲稱 live crash test 已完成。

---

## 5. Readiness flag 升級規則

三個 flag 必須分開判定，不可一起硬改：

### `webhookRealE2e=true`
只有當：
- 真 GitHub webhook delivery 由 GitHub 發出；
- HMAC 通過；
- repo/issue/action/user authorization 通過；
- contract 進入 engine；
才可設 true。

### `liveProviderReady=true`
只有當：
- 上述真 webhook chain 內確實做出真 provider network request；
- schema valid；
- provider request ID/audit evidence 可驗證；
- 4 reviewed identities exact-match；
才可設 true。

### `eventDrivenSupervisorReady=true`
只有當完整鏈：

`GitHub delivery -> verified contract -> dual CI/evidence -> live provider -> exactly one instruction commit -> exactly one Issue comment -> watcher claim -> replay no duplicate`

全部 PASS 才可設 true。

若任何一步只跑 fixture / MockTransport / local synthetic webhook，三個 flags 必須保持 false。

---

## 6. REAL / MOCK / PARTIAL / BLOCKED 邊界

本輪起始狀態：

- Supervisor core / GitHub client / policy / state / crash recovery：**REAL_LOGIC / TESTED**
- CODE/DOCS dual CI lineage：**REAL_LOGIC / TESTED**
- external provider adapters：**REAL_LOGIC / ADAPTER**
- Product Truth / existing Blender still evidence：保留既有 scoped **REAL**
- GitHub webhook production chain：**BLOCKED / false**，等待本輪 live delivery
- live provider production invocation：**BLOCKED / false**，等待本輪真 network call
- event-driven supervisor production readiness：**BLOCKED / false**，等待完整鏈
- CI `FOX3D_MOCK_BLENDER=1`：**MOCK test environment**，不是 Production Ready
- Vision / Demand / AI Video：依既有文件維持 **MOCK**
- LIVE_CNC / LIVE_LASER / PLC / machine control：**BLOCKED**
- `commercialAssetProductionReady=false`
- `physicalPrintValidated=false`
- `liveFactoryExecutionReady=false`
- `fullAutonomousFactoryReady=false`
- `globalProductionReady=false`
- **Phase 961+ HOLD**

本輪不得因 Supervisor live E2E 成功而順便宣稱整個 Fox3D / factory Production Ready。

---

## 7. 完成後 handoff

若完整 LIVE E2E PASS：

1. 更新：
   - `docs/GROK_PROGRESS_REPORT.md`
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
   - `docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md`
   - `docs/REAL_E2E_ACCEPTANCE.md`（只更新本輪真正改變的 scoped flags）
   - `docs/CABINET_REAL_ACCEPTANCE.md` 若 cabinet truth 無變化則不要改。
2. 程式碼若無 live bug，不要為了製造 CODE commit 任意改 code；可以用 exact existing CODE lineage + live runtime evidence。
3. 若 live bug 需要修 code：新 CODE SHA -> full pytest -> exact Ubuntu+Windows CODE CI -> live E2E 再跑一次。
4. docs commit 後等 exact Ubuntu+Windows DOCS CI SUCCESS。
5. Issue #1 留 machine-readable `READY_FOR_RE_GATE`，增加：
   - `LIVE_WEBHOOK_DELIVERY_ID`
   - `LIVE_PROVIDER`
   - `LIVE_PROVIDER_MODEL`
   - `LIVE_PROVIDER_REQUEST_ID`（若 provider 有）
   - `INSTRUCTION_COMMIT_SHA`
   - `ISSUE_COMMENT_ID`
   - `WATCHER_CLAIM_COUNT`
   - `WEBHOOK_REAL_E2E`
   - `LIVE_PROVIDER_READY`
   - `EVENT_DRIVEN_SUPERVISOR_READY`
   - 原本 CODE/DOCS/CI/EVIDENCE lineage
6. STOP 等 external ChatGPT Re-Gate。不得自行開始 Phase 961+。

若 BLOCKED_WAITING_LIVE_E2E：同樣更新 docs/Issue，列出缺少 prerequisite 類型，三個 readiness flags 維持 false，然後 STOP。

---

## 8. 禁止事項

- 不要重寫既有 Supervisor 架構。
- 不要改 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth。
- 不要把 mock webhook、MockTransport、pytest、CI fixture 當 live E2E。
- 不要在 docs / Issue / logs 洩漏 webhook secret、GitHub token、provider API key。
- 不要自行建立/啟動 LIVE_CNC、LIVE_LASER、PLC 或其他 physical machine control。
- 不要把 generative provider output 當 Product Truth。
- 不要自行進 Phase 961+。
