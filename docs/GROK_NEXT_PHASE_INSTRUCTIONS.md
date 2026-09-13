# Development Agent 修正指令：Event-Driven Supervisor Re-Gate Round 4 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed instruction: `5a6f5581cb4474c21b72b5db61cecd4ee952e90d`
> Reviewed CODE: `9bed18436f5d2775685415c13913a85ab5e91740`
> Reviewed docs/head: `14d6c22aa450af67940b399d426b2babc3ea52a3`
> CODE Actions: `34770001180` — Ubuntu `103757730292` SUCCESS / Windows `103757730112` SUCCESS
> DOCS Actions: `34771130885` — Ubuntu `103760809566` SUCCESS / Windows `103760809660` SUCCESS
> Reported regression: **742 passed**; Supervisor-specific: **44 passed**
> Re-Gate result: **CHANGES REQUIRED (Round 4)**
> `webhookRealE2e=false`; `eventDrivenSupervisorReady=false`; `liveProviderReady=false` 必須維持。
> **Phase 961+ remains HOLD.**

## 0. 本輪已接受的實質進展 — 保留，不要重寫

本輪相較前次有明確進展，以下視為已接受的 REAL_LOGIC / TESTED software evidence：

- `OpenAI` / `Anthropic` / `Gemini` adapter 已不再只 `return preflight`，已有 provider-neutral HTTP dispatch、response parsing、schema validation 與 fail-closed 路徑。
- `CODE_CI_RUN_ID` / `DOCS_CI_RUN_ID` 已拆開，engine 會各自驗 exact SHA、completed/success、Ubuntu + Windows。
- `GROK_PROGRESS_REPORT.md` / `CURRENT_IMPLEMENTATION_AUDIT.md` 已更新到本輪 exact instruction / CODE lineage。
- provider response 目前已有 CODE SHA + evidence generation 的 independent check，並有 mock promotion prevention。
- exact CODE `9bed184...` 的 Actions `34770001180` 與 exact DOCS `14d6c22...` 的 Actions `34771130885` 都是 Ubuntu + Windows SUCCESS。
- 742 full regression / 44 Supervisor tests 可接受為軟體測試證據。
- readiness truth boundary 正確：`webhookRealE2e=false`、`eventDrivenSupervisorReady=false`、`liveProviderReady=false`；MockTransport / unit test 不得視為 live provider / Production Ready。

不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth / 既有 Supervisor control-plane 架構。本輪只修下面的 fail-closed lineage、provider context、crash/idempotency 與 live E2E gate。

---

## 1. Blocker A — final provider output 尚未回綁 DOCS_SHA / INSTRUCTION_SHA

前一輪要求 final provider 回綁 reviewed CODE / DOCS / INSTRUCTION / evidence identity；目前 schema 仍只有：

- `reviewedCodeSha`
- `reviewedEvidenceGenerationId`

缺少 reviewed DOCS 與 INSTRUCTION identity，因此 provider 可能實際審到錯的 docs/instruction，但只要 CODE/evidence id 正確仍可能通過。

### Required correction

1. 擴充 `ProviderReviewResponseSchema`：
   - `reviewedCodeSha`
   - `reviewedDocsSha`
   - `reviewedInstructionSha`
   - `reviewedEvidenceGenerationId`
2. `SupervisorReviewOutput` 同樣保留上述四個 reviewed identity。
3. provider prompt schema 必須要求四個欄位全部回傳 exact full SHA / generation id。
4. `SupervisorEngine` 必須 independently verify：
   - provider `reviewedCodeSha == contract.code_sha`
   - provider `reviewedDocsSha == contract.docs_sha`
   - provider `reviewedInstructionSha == contract.instruction_sha`
   - provider `reviewedEvidenceGenerationId == contract.evidence_generation_id`
5. 任一 mismatch / missing / malformed → `CHANGES_REQUIRED`，不得 ACCEPT。
6. 不得只靠 provider 自述；engine verification 為最終 safety gate。

### Required tests

- wrong reviewed CODE SHA → no ACCEPT
- wrong reviewed DOCS SHA → no ACCEPT
- wrong reviewed INSTRUCTION SHA → no ACCEPT
- wrong evidence generation id → no ACCEPT
- missing reviewed identity → schema reject
- provider all identities exact → 才能進下一 policy gate

---

## 2. Blocker B — final provider prompt 目前沒有 exact instruction text，且 bounded evidence 無 completeness signal

`ReviewContext` 已讀取 `instruction_text` @ exact `INSTRUCTION_SHA`，但目前 provider `_build_prompt()` 沒有把它放進 prompt。

另外目前 diff / progress / audit / acceptance 採固定字元截斷；bounded context 可以接受，但不能「靜默截斷後仍讓 provider 以為已看完全部 evidence」。

### Required correction

1. provider context 必須加入：
   - exact instruction text @ `INSTRUCTION_SHA`
   - contract full identities
   - CODE/DOCS CI summaries + job identifiers
   - changed-file manifest
   - bounded diff
   - progress / audit / acceptance docs
2. exact instruction text不得完全缺席。
3. 對所有 bounded / truncated sections加入明確 metadata，例如：
   - source path
   - ref SHA
   - original byte/char length
   - supplied length
   - `truncated=true|false`
   - sha256 / digest（可對原文）
4. 若關鍵 instruction / changed-file evidence 被截到不足以審查，不得無條件 ACCEPT；可採 chunking、per-file bounded review、deterministic manifest gate，或 fail closed。
5. changed-file manifest 至少列出 path + status；不得讓 critical changed file 完全消失在 provider context。
6. provider 不得獲得 unrestricted shell、GitHub token、secret 或直接 write capability。

### Required tests

- exact instruction text確實出現在 provider request
- instruction ref mismatch → reject
- material diff omitted/truncated without completeness handling → no ACCEPT
- changed-file manifest 包含本輪所有 changed paths
- prompt/log 不含 API key / GitHub token / webhook secret

---

## 3. Blocker C — Engine independent mismatch path 目前可能因 undefined `logger` 崩潰

`services/supervisor/engine.py` 在 provider CODE mismatch / evidence mismatch / mock promotion branch 呼叫 `logger.warning(...)`，但 module 目前沒有建立 `logger`。

這表示真正遇到惡意或錯誤 provider response 時，原本應 fail closed 的 path 可能變成 runtime exception，而不是穩定 `CHANGES_REQUIRED`。

### Required correction

1. 正式建立 module logger，例如：
   - `import logging`
   - `logger = logging.getLogger("supervisor.engine")`
   或改成不依賴未定義 logger 的安全實作。
2. fail-closed 路徑不得因 logging 自己崩潰。
3. engine-level tests 必須真的走到 mismatch branch，不可只測 adapter-level mismatch。

### Required tests

- adapter 回 wrong CODE identity → engine 回 `CHANGES_REQUIRED`，不得 NameError
- wrong DOCS / INSTRUCTION / evidence identity 同樣 fail closed
- provider 嘗試 MOCK→REAL promotion → engine穩定 downgrade，不得 exception

---

## 4. Blocker D — Provider model/config 必須可部署、可追溯；MockTransport 仍不是 live provider evidence

目前 HTTP adapter logic 可接受，但 live readiness 仍未驗證，且 provider/model 應由部署設定管理，而不是把單一 model id 永久寫死為唯一選項。

### Required correction

1. 新增可配置 model，例如 `SUPERVISOR_AI_MODEL`，由 provider + model 組合決定實際 request。
2. live mode 必須驗證 provider/model config 非空且合法；unknown provider/model fail closed。
3. acceptance/audit 記錄實際：
   - provider
   - model
   - request/review id（若 provider 提供）
   - timestamp
   - 不得記 API key/token
4. unit test / `httpx.MockTransport` 僅標 `REAL_LOGIC / TESTED_ADAPTER`，不得設 `liveProviderReady=true`。
5. 若本環境尚無 live provider credential，誠實保持 BLOCKED，先完成其餘修正再做 live E2E。

---

## 5. Blocker E — `BLOCKED` decision 的 Issue comment crash window 也要 idempotent

目前 ACCEPT / CHANGES_REQUIRED 有 remote instruction/comment reconciliation，但 `BLOCKED` path 仍直接 post comment；若 comment 已成功、process 在 state record 前 crash，retry 可能重複留言。

### Required correction

1. `BLOCKED` comment 也使用 deterministic review marker。
2. retry 前先查 state + Issue existing marker。
3. 已存在同一 `CODE_SHA + EVIDENCE_GENERATION_ID` 的 BLOCKED comment 時只 adopt，不重複 post。
4. state record 與 recovery 行為需與 ACCEPT/CHANGES_REQUIRED 一致。

### Required tests

- BLOCKED comment 成功後、state persist 前 crash → retry exactly one comment
- duplicate webhook / duplicate READY → no second BLOCKED comment

---

## 6. Blocker F — REAL GitHub Webhook E2E 仍是 mandatory final acceptance gate

完成 Blocker A–E、CODE + DOCS exact dual-platform CI 全綠後，才執行真實事件鏈：

1. authorized owner 在真 Issue #1 發 `READY_FOR_RE_GATE`。
2. GitHub 真 delivery 到 public webhook endpoint。
3. HMAC `X-Hub-Signature-256` verified。
4. `X-GitHub-Delivery`、repo、sender、association、issue、action 全部 exact gate。
5. CODE / DOCS / INSTRUCTION / evidence lineage exact。
6. CODE CI + DOCS CI 各自 exact SHA + Ubuntu/Windows SUCCESS。
7. deterministic safety preflight。
8. **真的 configured provider network call**，不是 MockTransport。
9. provider structured response四個 reviewed identity exact。
10. engine independent verify + policy gate。
11. exactly one instruction commit。
12. remote blob exact verify。
13. exactly one `SUPERVISOR_REVIEW_COMPLETE` comment。
14. watcher claim新 instruction exactly once。
15. replay same delivery + duplicate READY → 不得新增第二 commit/comment/claim。
16. 至少一個受控 crash-recovery proof；若 production endpoint 不適合 fault injection，可在 staging repo/issue 做並明確標 STAGING。

Acceptance evidence 至少記錄：

- GitHub delivery ID
- review ID
- provider + model
- reviewed CODE / DOCS / INSTRUCTION SHA
- evidence generation ID
- CODE/DOCS CI run + job IDs
- resulting instruction commit SHA
- Issue comment ID
- watcher claimed instruction SHA
- timestamps / retry count

只有完整真實鏈完成，且下一次 external Re-Gate 接受後，才可以改：

- `webhookRealE2e=true`
- `eventDrivenSupervisorReady=true`
- `liveProviderReady=true`（僅在真 provider call evidence 成立時）

Supervisor 不得 self-promote readiness。

---

## 7. Product / manufacturing truth boundaries 維持不變

本輪 Supervisor side-track 不得解除：

- prior Phase 901–960 Product Content blockers / lineage仍獨立處理
- **Phase 961+ HOLD**
- live H3 MAX / LTX 2.5 = BLOCKED
- Vision Judge = MOCK/BLOCKED
- physical print = false/BLOCKED
- LIVE_CNC / LIVE_LASER / PLC / machine control = BLOCKED
- `commercialAssetProductionReady=false`
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`

既有 `REAL_E2E_ACCEPTANCE.md` / `CABINET_REAL_ACCEPTANCE.md` 的 REAL Blender / engineering evidence 可保留；除非修改到其執行路徑，否則不要為本輪 Supervisor 修正重跑無關產品架構。

---

## 8. 本輪交付與停止條件

完成後必須：

1. `pytest -v tests/test_supervisor.py` + full `pytest -q` 全綠。
2. CODE commit/push → 等 exact CODE Ubuntu + Windows CI SUCCESS。
3. 更新 current `GROK_PROGRESS_REPORT.md` / `CURRENT_IMPLEMENTATION_AUDIT.md` / `EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md`。
4. DOCS commit/push → 等 exact DOCS Ubuntu + Windows CI SUCCESS。
5. Issue #1 發新的 machine-readable：

```text
READY_FOR_RE_GATE
REPO=netfox-web/blender-autonomous-3d
ISSUE=1
INSTRUCTION_SHA=<this Round 4 instruction commit>
CODE_SHA=<exact code commit>
DOCS_SHA=<exact docs commit>
CODE_CI_RUN_ID=<run whose head_sha == CODE_SHA>
DOCS_CI_RUN_ID=<run whose head_sha == DOCS_SHA>
TEST_COUNT=<exact count>
EVIDENCE_GENERATION_ID=<exact generation>
REAL_BLENDER=<true|false according to evidence>
USED_MOCK=<true|false according to evidence>
```

6. 同時回報：
   - provider live network call 是否完成
   - GitHub real webhook E2E 是否完成
   - 若未完成，相關 readiness flags必須保持 false
7. 完成後 **STOP / WAIT FOR NEXT EXTERNAL RE-GATE**。
8. 不要自行進 Phase 961+，不要把 mock/unit/integration/staging 冒充 Production Ready。
