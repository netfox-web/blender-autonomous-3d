# Development Agent 指令：Event-Driven Supervisor Re-Gate Round 10 — BLOCKED HOLD / LIVE E2E LINEAGE CORRECTION

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed instruction: `2c7463b26f26361e3c94991f259a413da56a7057`
> Accepted implementation CODE: `d9402f3a966581aa66d39b0097e518366d87626c`
> Round 9 DOCS/Handoff: `475ab6fe641da0caa79deefe951a4c42a2f04398`
> CODE Actions: `34788079332` — Ubuntu + Windows SUCCESS
> Round 9 DOCS Actions: `34792513276` — Ubuntu + Windows SUCCESS
> Tests retained: `72 passed` supervisor / `770 passed` full regression
> Re-Gate result: **BLOCKED_WAITING_LIVE_E2E / CORRECTION-ONLY**
> **Phase 961+ remains HOLD.**

## 0. 審核結論

Round 9 的 fail-closed 行為是正確的：目前缺少真正 live E2E 所需的 public HTTPS webhook ingress、`GITHUB_WEBHOOK_SECRET`、`SUPERVISOR_AI_PROVIDER` / `SUPERVISOR_AI_MODEL`、live provider credential 與 `SUPERVISOR_ADMIN_KEY`。因此以下三個 flag 必須繼續為 false：

- `webhookRealE2e=false`
- `liveProviderReady=false`
- `eventDrivenSupervisorReady=false`

這不是程式失敗；不要重寫既有 Supervisor 架構，也不要用 MockTransport / fixture / curl synthetic webhook 取代真正 GitHub delivery。

Supervisor core / GitHub client / state / policy / crash recovery 維持 **REAL_LOGIC / TESTED**；Product Truth 既有 Blender evidence 維持 scoped REAL；LIVE_CNC / LIVE_LASER / PLC、physical print、full autonomous factory 仍為 BLOCKED。

---

## 1. 必修正：Round 9 evidence lineage 不可混用

Round 9 READY contract 目前宣告：

- `code_sha=d9402f3a966581aa66d39b0097e518366d87626c`
- `evidence_generation_id=66af98fb-5e5f-4d03-850a-d37726e59451`

但 Round 9 report 同時記錄該 generation 的 `evidenceCodeCommit=2c7463b26f26361e3c94991f259a413da56a7057`。這是 instruction/docs commit，不是 accepted implementation CODE `d9402f3...`，因此此 generation 不可再被當成 `d9402f3...` 的 exact CODE-bound REAL acceptance identity。

先前已接受且 exact 綁定 `d9402f3...` 的 clean-tree REAL evidence 為：

- `evidence_generation_id=1631af33-6946-4ac9-96eb-b844d68892c9`
- `evidenceCodeCommit=d9402f3a966581aa66d39b0097e518366d87626c`
- `workingTreeClean=true`
- `usedMock=false`

### 修正規則

1. 若 Supervisor READY contract 需要 CODE-bound Blender evidence，恢復使用上面已接受的 `1631af33-...`，並在 Progress / Audit / Supervisor Acceptance / Issue contract 中保持一致。
2. `66af98fb-...` 若要保留，只能標成「post-instruction runtime/doc-side verification」，不得冒充 `d9402f3...` 的 exact CODE-bound evidence。
3. 不要為了修 lineage 製造新的 implementation CODE commit。
4. 不要重新跑 Product Truth 只為了產生新的 generation，除非真的有 code 變更或 external Re-Gate 明確要求。

---

## 2. 現在不要繼續 churn repo

在 live prerequisites 仍缺少、且沒有新 code / 新 live infrastructure / 新 provider credential 狀態變化時：

- 不要再新增 docs-only「BLOCKED_WAITING_LIVE_E2E」commit。
- 不要再重貼相同 READY_FOR_RE_GATE Issue 留言。
- 不要修改 `GROK_PROGRESS_REPORT.md`、`CURRENT_IMPLEMENTATION_AUDIT.md`、acceptance files 只為重述相同 blocker。
- 保持安靜並 STOP；等待 live prerequisite 真正改變。

這條是為避免每次 watcher/輪詢造成無意義 commit/comment loop。

---

## 3. 只有 prerequisites 真正到位後才執行 LIVE E2E

實際確認以下項目已存在後才開始：

- GitHub 可訪問的 public HTTPS supervisor endpoint
- repo webhook 與 runtime 一致的 `GITHUB_WEBHOOK_SECRET`
- 可用 GitHub write credential / App token
- `SUPERVISOR_AI_PROVIDER` = `openai` / `anthropic` / `gemini`
- 非空且 provider-compatible 的 `SUPERVISOR_AI_MODEL`
- 對應 live provider API credential
- `SUPERVISOR_ADMIN_KEY`
- repo=`netfox-web/blender-autonomous-3d`, branch=`main`, Issue #1 policy 正確

任何一項缺失：維持 `BLOCKED_WAITING_LIVE_E2E`，不修改 readiness flags，不用 mock 代替。

---

## 4. LIVE E2E 完整成功條件

必須由真 GitHub delivery 跑通：

`READY_FOR_RE_GATE comment -> GitHub webhook -> HMAC/auth -> exact contract -> exact CODE/DOCS dual CI -> pinned evidence -> live AI provider network call -> schema/4 identities exact match -> exactly one instruction commit -> remote blob verify -> exactly one Issue comment -> Antigravity watcher claim exactly once -> replay no duplicate`

必留非秘密 evidence：

- GitHub delivery ID / event / action / repo / Issue / commenter / HMAC=true
- instruction/code/docs SHA
- CODE/DOCS CI run IDs + Ubuntu/Windows job IDs/conclusions
- exact CODE-bound evidence generation ID
- provider/model/request ID（若 provider 提供）
- response schema PASS + 4 reviewed identities exact-match
- instruction commit SHA + 6 trailers + intended SHA256 + remote blob verification
- Issue comment ID + deterministic marker
- watcher claim key/timestamp/count=1
- replay same delivery / same contract 不新增 commit/comment/claim

不得寫入 secret、token、API key 或 Authorization header。

---

## 5. Readiness 升級規則

### `webhookRealE2e=true`
只有真 GitHub delivery + HMAC + repo/issue/action/user authorization + contract 已進 engine 才能升級。

### `liveProviderReady=true`
只有在上述真 webhook chain 內完成真 provider network request、schema valid、request/audit evidence 可驗證、4 identities exact-match 才能升級。

### `eventDrivenSupervisorReady=true`
只有完整鏈 + exactly-once + replay no duplicate 全 PASS 才能升級。

其中任一步是 fixture / MockTransport / synthetic webhook，三個 flags 都必須保持 false。

---

## 6. 若 LIVE E2E 暴露真正 bug

只做 correction-only：

1. 修最小範圍 bug；不要重寫架構。
2. 新 CODE SHA。
3. `pytest -v tests/test_supervisor.py` + `pytest -q` 全綠。
4. exact CODE SHA Ubuntu + Windows Actions SUCCESS。
5. 再跑完整 live E2E。
6. 更新 docs 後 exact DOCS SHA Ubuntu + Windows Actions SUCCESS。
7. Issue #1 留一次 machine-readable READY_FOR_RE_GATE，STOP 等 external Re-Gate。

---

## 7. 禁止事項

- 不要重寫 Supervisor / Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth。
- 不要把 MockTransport、pytest、GitHub Actions fixture、curl synthetic webhook 當 live E2E。
- 不要把 `66af98fb-...` 冒充 `d9402f3...` 的 exact CODE-bound evidence。
- 不要為了產生新 SHA 任意改 code。
- 不要在 prerequisites 無變化時重複 commit/comment。
- 不要啟動 LIVE_CNC / LIVE_LASER / PLC / physical machine control。
- 不要把 generative output 當 Product Truth。
- 不要自行進 Phase 961+。
