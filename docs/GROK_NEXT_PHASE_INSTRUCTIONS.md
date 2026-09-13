# Development Agent 修正指令：Event-Driven Supervisor Re-Gate Round 3 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed instruction: `8b0b788e70bc02fe63e22b42ce665a40a52f73fd`
> Reviewed CODE: `d77cfe758a36c6dfe886ff18d9c67f6a7664afe9`
> Reviewed docs/head: `6ccc8c592d51d536a4101082582e18fddf8cf50f`
> CODE Actions: `34766663210` — Ubuntu `103748731208` SUCCESS / Windows `103748731348` SUCCESS
> DOCS Actions: `34767761678` — Ubuntu + Windows SUCCESS
> Reported regression: **733 passed**; Supervisor-specific: **35 passed**
> Re-Gate result: **CHANGES REQUIRED (Round 3)**
> `WEBHOOK_REAL_E2E=false`; `EVENT_DRIVEN_READY=false` 必須維持。
> **Phase 961+ remains HOLD.**

## 0. 本輪已接受的進展 — 保留，不要重寫

相較 Round 2，以下修正已具實質進展，請保留：

- webhook 已要求合法 HMAC、live 模式非空 `X-GitHub-Delivery`、exact `repository.full_name`、`issue_comment` + `action=created`、Issue #1 與 sender authorization。
- delivery lifecycle、remote instruction commit adoption、Issue comment deterministic marker adoption、push failure rollback等 crash/retry 防重複邏輯已補強。
- live git write preflight 已檢查 current branch / detached HEAD / local HEAD vs `origin/main` / clean tree+index，並使用 explicit refspec；push 後也有 remote instruction content verification。
- evidence 讀取已改為 pin 到 `contract.docs_sha` / `contract.instruction_sha`，並加入 `CABINET_REAL_ACCEPTANCE.md` 與 `EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md`。
- `SemanticEvidenceSupervisorAdapter` 已定位為 deterministic preflight；live `semantic_evidence` 不得單獨 ACCEPT。
- exact CODE `d77cfe7` 與 docs `6ccc8c5` 的 GitHub Actions 均已確認 Ubuntu + Windows SUCCESS。
- 733 full regression / 35 Supervisor tests 是有效軟體測試證據，但**不是** live webhook / live AI provider Production evidence。
- 文件仍正確保留 `webhookRealE2e=false`、`eventDrivenSupervisorReady=false`，以及 LIVE_CNC / LIVE_LASER / PLC / physical print / live factory 等 BLOCKED 邊界。

不要重寫既有 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth 架構。以下僅修 Event-Driven Supervisor 控制面與 evidence lineage。

---

## 1. Blocker A — OpenAI / Anthropic / Gemini adapters 目前仍沒有真的呼叫 provider

目前 `OpenAISupervisorAdapter`、`AnthropicSupervisorAdapter`、`GeminiSupervisorAdapter` 雖已存在，但 `review_repository()` 實際只執行 deterministic preflight 後直接 `return pf`。

也就是：設定 `SUPERVISOR_AI_PROVIDER=openai|anthropic|gemini` 時，現行程式**沒有真正呼叫任何外部 review provider**，卻可能在 preflight 通過後回傳 `ACCEPT_WITH_SCOPE`。這仍不符合「configured real review provider final authority」。

### Required correction

1. 建立真正 provider-neutral review client/adapter；可延伸現有 factory，不重寫 Supervisor engine。
2. `openai` / `anthropic` / `gemini` 必須真的執行 provider request，不能只回傳 deterministic preflight output。
3. deterministic `SemanticEvidenceSupervisorAdapter` 只做 safety preflight：
   - preflight `CHANGES_REQUIRED/BLOCKED` 可直接 fail closed；
   - preflight 通過後，必須交由 configured live provider做 final structured decision。
4. provider output 必須用 schema validation，至少：
   - `decision = ACCEPT_WITH_SCOPE | CHANGES_REQUIRED | BLOCKED`
   - `reviewedCodeSha`
   - `reviewedEvidenceGenerationId`
   - `acceptedClaims[]`
   - `rejectedClaims[]`
   - `truthMatrix.REAL/MOCK/PARTIAL/BLOCKED`
   - `blockers[]`
   - `nextInstructionMarkdown`
   - `issueCommentMarkdown`
5. timeout / network error / 429 exhaustion / malformed JSON / schema mismatch / unknown decision / reviewed SHA mismatch 一律 fail closed，不得 fallback 成 ACCEPT。
6. provider 不得取得 unrestricted shell / GitHub write / secrets；仍由 policy layer 與 Supervisor 負責 write。
7. API key / token 不得寫進 logs、Issue、acceptance docs。

### Required tests

- 用 mock transport / local fake HTTP endpoint 明確證明 provider request **真的被呼叫**。
- provider 回 malformed JSON → no ACCEPT。
- provider 回錯 CODE SHA / evidence generation → no ACCEPT。
- provider timeout / 5xx / exhausted retry → no ACCEPT。
- deterministic preflight fail → provider 不可覆蓋成 ACCEPT。
- provider ACCEPT 仍須經 policy guardrail。

> 測試 fake provider 只證明 adapter logic；不得因此宣稱 `liveProviderReady=true`。

---

## 2. Blocker B — current pinned Progress Report / Audit 仍是舊 Phase，與這次 READY contract 自相矛盾

目前 `docs/GROK_PROGRESS_REPORT.md` @ `6ccc8c5` 仍寫：

- Source instruction `59ad337`
- CODE `4406119`
- Phase 901–960 Product Content Re-Gate R1
- tests `628 passed`

`docs/CURRENT_IMPLEMENTATION_AUDIT.md` header 也仍是 Product Content R1 / CODE `4406119` / instruction `59ad337`。

但本輪 READY contract 是：

- INSTRUCTION `8b0b788`
- CODE `d77cfe7`
- DOCS `6ccc8c5`
- tests `733`

而你自己新增的 `SemanticEvidenceSupervisorAdapter` 已要求 progress report 必須包含 exact/current CODE SHA + INSTRUCTION SHA。照現行 pinned evidence，這次 READY 應被 preflight 判為 stale / CHANGES_REQUIRED。

### Required correction

1. 更新 `docs/GROK_PROGRESS_REPORT.md`，明確記錄本次 Event-Driven Supervisor Round 2/3 lineage：
   - `INSTRUCTION_SHA=8b0b788...`
   - `CODE_SHA=d77cfe7...`
   - 新的 docs SHA 用兩階段提交方式記錄，不要先偽造未知 SHA。
   - `CODE_CI_RUN_ID=34766663210`
   - `DOCS_CI_RUN_ID=<new exact docs run>`
   - `TEST_COUNT=733`（若修正後增加，寫新 exact count）
   - `EVIDENCE_GENERATION_ID=d16c4cd2-f463-4d01-b055-ac3e18df2546` 或本輪新 generation。
   - `eventDrivenSupervisorReady=false`
   - `webhookRealE2e=false`
2. 更新 `docs/CURRENT_IMPLEMENTATION_AUDIT.md` 的 current header/section，加入 Event-Driven Supervisor 的 REAL_LOGIC/PARTIAL/BLOCKED 狀態；歷史 Product Content audit 保留，不要刪。
3. `EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md` 不得宣稱 Blocker D fully resolved，直到 provider 真的有 request + final schema decision evidence。
4. 加 regression：pinned stale progress report 必須 CHANGES_REQUIRED；current exact report 才能進 provider final review。

---

## 3. Blocker C — READY machine-readable contract 的 CI_RUN_ID 與 engine verifier 不相容

目前 Issue #1 READY block 寫：

- `CODE_SHA=d77cfe7...`
- `DOCS_SHA=6ccc8c5...`
- `CI_RUN_ID=34767761678`

但 `34767761678` 的 `head_sha` 是 **DOCS `6ccc8c5`**。

現行 `SupervisorEngine._execute_review()` Step C 卻是：

`verify_ci_run(run_id=contract.ci_run_id, expected_code_sha=contract.code_sha)`

也就是這份 READY contract 如果真的從 webhook 送進目前 engine，會拿 docs CI 去比 CODE SHA `d77cfe7`，理應 fail closed。Issue prose雖另外列出 CODE run `34766663210`，但 machine-readable contract 沒有獨立 CODE / DOCS CI 欄位。

### Required correction

把 READY contract / model 明確升級為 dual-CI lineage，至少：

```text
CODE_CI_RUN_ID=<run whose head_sha == CODE_SHA>
DOCS_CI_RUN_ID=<run whose head_sha == DOCS_SHA>
```

規則：

1. `CODE_CI_RUN_ID` 必須：
   - head SHA exact == `CODE_SHA`
   - conclusion SUCCESS
   - Ubuntu SUCCESS
   - Windows SUCCESS
2. `DOCS_CI_RUN_ID` 必須：
   - head SHA exact == `DOCS_SHA`
   - conclusion SUCCESS
   - Ubuntu SUCCESS
   - Windows SUCCESS
3. 不得以 Issue prose 補 machine-readable contract 缺欄位。
4. 若要 backward compatibility，可僅在明確可證唯一 mapping 時支援舊 `CI_RUN_ID`；live READY 建議 fail closed 並要求雙欄位。
5. ReviewContext 要同時帶 `code_ci_summary` 與 `docs_ci_summary`，final provider 也必須看到。

### Required negative tests

- docs CI run 填到 `CODE_CI_RUN_ID` → reject。
- code CI run 填到 `DOCS_CI_RUN_ID` → reject。
- missing docs CI → no ACCEPT。
- CI success 但 head SHA mismatch → reject。
- Ubuntu success / Windows missing → reject。
- Windows success / Ubuntu missing → reject。

---

## 4. Blocker D — final provider 必須審 exact pinned evidence，不可只看 preflight摘要

修好 provider 呼叫後，final review context 至少要包含 bounded/structured：

- exact `GROK_PROGRESS_REPORT.md` / `AGENT_PROGRESS_REPORT.md` @ DOCS_SHA
- `CURRENT_IMPLEMENTATION_AUDIT.md` @ DOCS_SHA
- `REAL_E2E_ACCEPTANCE.md` @ DOCS_SHA
- `CABINET_REAL_ACCEPTANCE.md` @ DOCS_SHA
- `EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md` @ DOCS_SHA
- exact instruction text @ INSTRUCTION_SHA
- changed files + bounded diff for `INSTRUCTION_SHA...DOCS_SHA`
- exact CODE CI summary/job IDs
- exact DOCS CI summary/job IDs
- READY contract fields

provider final output 必須回綁 reviewed CODE/DOCS/INSTRUCTION/evidence identity；Supervisor 再 independently verify，不得只相信 provider 自述。

REAL/MOCK/PARTIAL/BLOCKED 仍以 pinned evidence + deterministic checks為底線；provider 不得把 MOCK/FIXTURE 升級為 Production Ready。

---

## 5. Blocker E — REAL GitHub Webhook E2E 仍是 mandatory acceptance gate

上述 A–D 修完、exact CODE + DOCS dual-platform CI 全綠後，才跑真實事件鏈：

1. 真 GitHub Issue #1，由 authorized owner 發 `READY_FOR_RE_GATE`。
2. 真 `X-GitHub-Delivery` + HMAC verify。
3. exact repo / sender / issue / action / delivery fail-closed。
4. exact CODE / DOCS / INSTRUCTION lineage。
5. exact CODE CI + DOCS CI 各自 Ubuntu + Windows SUCCESS。
6. deterministic preflight。
7. **真的 configured provider request** + valid structured final decision。
8. exactly one remote instruction commit。
9. remote instruction blob/content exact verify。
10. exactly one `SUPERVISOR_REVIEW_COMPLETE` Issue comment。
11. watcher claim new instruction exactly once。
12. replay same delivery / duplicate READY 不得出現第二個 instruction commit/comment。
13. 至少做一次真實 crash-window recovery proof；若無法安全故障注入 Production endpoint，可使用受控 staging repo / staging issue，必須明確標 STAGING，不可冒充 production live chain。

Acceptance docs 必須記：

- GitHub delivery ID
- review ID
- provider + model
- reviewed CODE / DOCS / INSTRUCTION SHA
- CODE/DOCS CI run + job IDs
- resulting instruction commit SHA
- Issue review comment ID
- watcher claimed instruction SHA
- timestamps / retry count

只有整條真實鏈完成後，才可提出：

- `webhookRealE2e=true`
- `eventDrivenSupervisorReady=true`

而且仍需下一次 external Re-Gate 接受，不得由 Supervisor self-promote。

若目前沒有可用 provider credential 或 public webhook endpoint，請誠實保持：

- `webhookRealE2e=false`
- `eventDrivenSupervisorReady=false`
- `liveProviderReady=false`

並將缺少項目列為 BLOCKED，不得用 unit/integration/mock transport 替代 REAL E2E。

---

## 6. Product / manufacturing truth boundaries 不變

Supervisor side-track 不得解除既有產品與製造 blocker：

- prior Phase 901–960 Product Content lineage/blockers 仍須獨立 re-gate；
- **Phase 961+ HOLD**；
- live H3 MAX / LTX 2.5 = BLOCKED；
- Vision Judge = MOCK/BLOCKED；
- physical print = false/BLOCKED；
- LIVE_CNC / LIVE_LASER / PLC / machine control = BLOCKED；
- `commercialAssetProductionReady=false`；
- `globalProductionReady=false`；
- `fullAutonomousFactoryReady=false`；
- `liveFactoryExecutionReady=false`。

`REAL_E2E_ACCEPTANCE.md` / `CABINET_REAL_ACCEPTANCE.md` 既有 REAL Blender / engineering證據可保留，不需重跑與本修正無關的產品 rendering，除非你修改到其執行路徑。

---

## 7. 本輪交付與停止條件

完成後：

1. 跑 `tests/test_supervisor.py` + full `pytest -q`。
2. CODE commit → exact Ubuntu + Windows CI SUCCESS。
3. 更新 current progress/audit/event supervisor acceptance docs。
4. DOCS commit → exact Ubuntu + Windows CI SUCCESS。
5. Issue #1 發新的 machine-readable READY block，必須包含：

```text
READY_FOR_RE_GATE
INSTRUCTION_SHA=<this instruction commit>
CODE_SHA=<exact code commit>
DOCS_SHA=<exact docs commit>
CODE_CI_RUN_ID=<exact code run>
DOCS_CI_RUN_ID=<exact docs run>
TEST_COUNT=<exact count>
EVIDENCE_GENERATION_ID=<generation>
REAL_BLENDER=<true|false according to this evidence>
USED_MOCK=<true|false according to this evidence>
REPO=netfox-web/blender-autonomous-3d
ISSUE=1
```

6. 同時回報 provider 真實呼叫證據是否完成、REAL webhook E2E 是否完成。
7. 若尚未真 E2E，保持 readiness false。
8. **停止並等下一次 Re-Gate；不得進 Phase 961+。**
