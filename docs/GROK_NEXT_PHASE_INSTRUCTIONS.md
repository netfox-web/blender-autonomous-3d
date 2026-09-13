# Development Agent 修正指令：Event-Driven Supervisor Re-Gate Round 5 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed instruction: `88488a2278d86e79e1270e09652c6dc81b81e6b6`
> Reviewed CODE: `b0941c7fa06b75b14e272a44018977120c656c3f`
> Reviewed DOCS/head: `cd9c4a77e2a33e9de1676f91adb235b6653cecba`
> CODE Actions: `34775155653` — Ubuntu `103771815496` SUCCESS / Windows `103771815666` SUCCESS
> DOCS Actions: `34776279326` — Ubuntu `103774874883` SUCCESS / Windows `103774874967` SUCCESS
> Reported regression: **747 passed**; Supervisor-specific: **49 passed**
> Evidence generation: `ae5f2d82-1a5c-4fe0-9af2-2b1c7a690f6d`
> Re-Gate result: **CHANGES REQUIRED (Round 5)**
> `webhookRealE2e=false`; `eventDrivenSupervisorReady=false`; `liveProviderReady=false` 必須維持。
> **Phase 961+ remains HOLD.**

## 0. 本輪已接受的實質進展 — 保留，不要重寫

本輪相較 `9bed184 / 14d6c22` 有明確進展，以下視為已接受的 **REAL_LOGIC / TESTED** software evidence：

- `ProviderReviewResponseSchema` / `SupervisorReviewOutput` 已加入並回綁四個 identity：CODE / DOCS / INSTRUCTION / evidence generation。
- `SupervisorEngine` 已 independently verify 四個 identity，mismatch 會 downgrade 成 `CHANGES_REQUIRED`。
- final provider prompt 已加入 instruction text、changed-file manifest、CODE/DOCS CI summary、diff/progress/audit/acceptance sections。
- bounded section 已加入 `original_chars / supplied_chars / truncated / sha256_prefix / ref` metadata。
- `engine.py` 的 logger 已正式初始化，mismatch / mock-promotion path 不再因未定義 logger 崩潰。
- `SUPERVISOR_AI_MODEL` 已進入 config / request dispatch / audit trail。
- `BLOCKED` decision 已加入 Issue comment Window B2 adoption，避免一般 retry 重複留言。
- exact CODE `b0941c7...` 與 exact DOCS `cd9c4a7...` 的 GitHub Actions 都是 Ubuntu + Windows SUCCESS。
- `747 passed` / `49 Supervisor tests` 可接受為軟體回歸證據。
- readiness truth boundary 正確：`webhookRealE2e=false`、`eventDrivenSupervisorReady=false`、`liveProviderReady=false`；MockTransport / unit / CI 不得視為 live provider 或 Production Ready。

不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth / 既有 Supervisor control-plane 架構。本輪只修下列 fail-closed completeness、config、recovery identity 與 contract parsing，再進真正 live E2E gate。

---

## 1. Blocker A — bounded evidence 目前只有「標示 truncated」，沒有真正 completeness handling

前一輪明確要求：**material diff omitted/truncated without completeness handling → no ACCEPT**，而目前 `_format_bounded_section()` 只加入 `truncated=true|false` metadata；`ExternalProviderSupervisorAdapter` / `SupervisorEngine` 並沒有在 critical evidence 被截斷時阻止 `ACCEPT_WITH_SCOPE`。

這代表 provider 可能只看到 diff / instruction / audit / acceptance 的前段，卻仍回 ACCEPT。

另外目前 `changed_files` 僅從 `diff --git` 抽出 path，manifest 沒有 status（A/M/D/R），仍未完全符合上一輪要求的 `path + status`。

### Required correction

1. 建立 machine-readable evidence completeness 結構，不要只把 metadata 塞進 prompt 字串。至少記：
   - `path`
   - `ref_sha`
   - `original_chars` 或 bytes
   - `supplied_chars`
   - `truncated`
   - `sha256`
   - `critical=true|false`
2. critical sections 至少包含：
   - exact instruction text @ `INSTRUCTION_SHA`
   - complete changed-file manifest
   - material code diff
   - current progress report
   - current implementation audit
   - Event-Driven Supervisor acceptance
3. 若 critical section `truncated=true`：
   - 必須 chunk / per-file review 到完整覆蓋；或
   - deterministic gate 直接 `CHANGES_REQUIRED`。
   **不得只提示 provider「已截斷」後仍允許 ACCEPT。**
4. instruction text 若超過單一 prompt budget，必須完整 chunk / digest-verified review；不得 silently slice 前 8000 chars 後視為 exact instruction reviewed。
5. changed-file manifest 改為由 `git diff --name-status` 或 GitHub compare metadata產生，至少提供 `status + path`；rename 要有 old/new path。
6. provider 最終 ACCEPT 前，engine 必須 independently assert：所有 critical changed files 都出現在 manifest，且所有 required review chunks 已 covered。
7. completeness state 要寫進 audit trail，方便之後 REAL E2E 驗證。

### Required tests

- material diff > bound → `truncated=true` 且未 chunk complete → **no ACCEPT**
- long instruction > bound → 未完整 coverage → **no ACCEPT**
- chunked full coverage + digest exact → 可進 provider decision gate
- changed manifest 包含 A/M/D/R status + path
- 任一 changed critical file 從 manifest 消失 → **no ACCEPT**
- digest mismatch / chunk missing / duplicate overlap造成 coverage 不完整 → **no ACCEPT**

---

## 2. Blocker B — pinned critical evidence fetch 仍可被 `_safe_get_file()` 靜默吞掉

目前 `_safe_get_file()` catch-all 後回空字串；而 deterministic preflight 沒有把 `instruction_text` 存在性當 mandatory gate。

因此 exact `INSTRUCTION_SHA` 的 instruction fetch 若因 ref/path/API 問題失敗，系統仍可能繼續叫 provider；這不符合「exact instruction must be reviewed」的 fail-closed 原則。

### Required correction

1. 區分 required / optional evidence fetch。
2. 在 live review 中，下列 pinned source fetch 失敗或空內容時必須 **在 provider call 前** fail closed：
   - `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` 或 approved neutral alias @ `INSTRUCTION_SHA`
   - current progress report @ `DOCS_SHA`
   - `CURRENT_IMPLEMENTATION_AUDIT.md` @ `DOCS_SHA`
   - `EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md` @ `DOCS_SHA`
3. 若 contract `REAL_BLENDER=true`，`REAL_E2E_ACCEPTANCE.md` 也必須可讀且與 current evidence lineage 可 reconciliation。
4. 不要讓 HTTP 404 / auth failure / timeout 與「檔案內容真的為空」全部變成 indistinguishable empty string；保留 typed fetch error / audit reason。
5. provider request 中要能看出 source fetch status，但不得洩漏 token / secret。

### Required tests

- instruction @ pinned SHA 404 → provider **not called**, no ACCEPT
- instruction empty → no ACCEPT
- audit missing → no ACCEPT
- event supervisor acceptance missing → no ACCEPT
- provider credentials正常但 pinned evidence fetch timeout → no ACCEPT
- optional CABINET file（若未被本輪 claim 使用）缺失不得誤標 Production Ready；若 claim 使用則 mandatory

---

## 3. Blocker C — Window B1 remote commit adoption 目前只靠 `supervisor:` + CODE short SHA，未綁 evidence identity/content

目前 crash recovery 掃描 remote commits 時，只要 commit message 同時含 `supervisor:` 與 `CODE_SHA[:7]` 就可 adopt。

同一 CODE SHA 可能有不同 `EVIDENCE_GENERATION_ID`、DOCS SHA、decision 或重新提交；因此可能誤 adopt 另一輪 instruction commit。這會破壞 exactly-once / lineage authority。

### Required correction

1. Supervisor instruction commit 必須帶 deterministic machine-readable identity，至少：
   - full `CODE_SHA`
   - full `DOCS_SHA`
   - prior `INSTRUCTION_SHA`
   - `EVIDENCE_GENERATION_ID`
   - decision
   - review id
2. 可用 commit trailers + instruction file hidden marker / frontmatter；不要只靠 7-char SHA。
3. crash recovery adopt remote commit 時必須 exact match：
   - full CODE SHA
   - evidence generation id
   - reviewed DOCS SHA
   - reviewed prior instruction SHA
   - expected decision
4. adopt 前重新讀 remote `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` blob，確認 content marker / digest 與 staged intended output exact match。
5. 找到 multiple matching candidates → fail closed，不可任選第一個。
6. same CODE + different evidence id 的兩次 review 必須各自 exactly-once，不可 cross-adopt。

### Required tests

- same CODE / evidence A 已有 supervisor commit，evidence B retry → 不得 adopt A
- same CODE / same evidence / wrong DOCS → 不得 adopt
- 只有 short SHA 相同 / forged commit message → 不得 adopt
- exact identity + exact remote blob → adopt once
- two exact candidates → BLOCK / CHANGES_REQUIRED，不得猜
- push success、state persist 前 crash → retry exactly one valid instruction commit

---

## 4. Blocker D — live provider/model config 與 machine contract parser 仍需 fail-closed

### 4.1 `SUPERVISOR_AI_MODEL`

Round 4 要求 live mode provider/model config 非空且合法；目前 `validate_live_config()` 沒有要求 `ai_model` 非空，external adapter 會在空值時套 default model。

這不代表 adapter logic 錯，但 acceptance 不可宣稱「live model config 已嚴格驗證」。

Required：

- `mode=live` + external provider (`openai` / `anthropic` / `gemini`) 時，`SUPERVISOR_AI_MODEL` 必須明確非空。
- unsupported/blank provider-model combination fail closed。
- actual provider + actual model + provider request/review id（若回傳）寫 audit；不得記 API key。
- test mode 才可保留 convenience default（若你要保留）。

### 4.2 READY contract truth booleans

目前 `parse_from_text()` 對 `REAL_BLENDER` / `USED_MOCK` 採「不是 true/1/yes 就變 false」。例如 typo / malformed value 可能被靜默當 false，不是 fail-closed。

Required：

- machine contract 建議只接受 literal `true` / `false`（若保留 1/0/yes/no 必須明確 allowlist）。
- 任何其他值 → parse reject / HTTP 400，不得 silently coerce false。
- `INSTRUCTION_SHA / CODE_SHA / DOCS_SHA` 驗證為 40-char hex full SHA。
- `CODE_CI_RUN_ID / DOCS_CI_RUN_ID` 在 live contract 必須是 positive numeric id。
- `TEST_COUNT >= 0` 並設定合理 gate；malformed integer reject。

### Required tests

- `USED_MOCK=tru` / `REAL_BLENDER=maybe` → reject
- short / non-hex SHA → reject
- blank live model → startup reject
- explicit configured model → exact request payload + audit trail
- malformed CI run id → reject before GitHub API call

---

## 5. Blocker E — 真 provider + 真 GitHub Webhook E2E 仍未完成，readiness 必須保持 false

目前 software control-plane 可視為 **REAL_LOGIC / TESTED**，但以下仍是 **BLOCKED / false**：

- `liveProviderReady=false`
- `webhookRealE2e=false`
- `eventDrivenSupervisorReady=false`

完成 Blocker A–D、CODE + DOCS exact dual-platform CI 全綠後，才執行 REAL event chain：

1. authorized owner/collaborator 在真 Issue #1 發 `READY_FOR_RE_GATE`。
2. GitHub 真 webhook delivery 到實際 public endpoint。
3. HMAC `X-Hub-Signature-256` verified。
4. delivery id / repo / action / issue / sender / association exact gate。
5. CODE / DOCS / INSTRUCTION / evidence generation exact lineage。
6. CODE CI + DOCS CI exact SHA，Ubuntu + Windows SUCCESS。
7. required pinned evidence完整 fetch + completeness gate。
8. deterministic preflight。
9. **真 configured provider network call**（非 MockTransport）。
10. provider 回四個 reviewed identity exact；engine independently verify。
11. exactly one instruction commit，remote blob exact verify。
12. exactly one `SUPERVISOR_REVIEW_COMPLETE` Issue comment。
13. watcher claim 新 instruction exactly once。
14. replay same delivery + duplicate READY → no second commit/comment/claim。
15. 至少一個 controlled crash-recovery proof；production 不適合 fault injection 可用 staging repo/issue，但要明確標 `STAGING`。

Acceptance evidence 至少記錄：

- GitHub delivery ID
- review ID
- provider + model + provider request id（若有）
- reviewed CODE / DOCS / prior INSTRUCTION SHA
- evidence generation id
- CODE/DOCS CI run + job IDs
- completeness manifest/digests
- resulting instruction commit SHA
- Issue comment ID
- watcher claimed instruction SHA
- timestamps / retry count

若本機尚無 live credential / public webhook endpoint，**不要偽造**；保持三個 readiness flag false，回報 `BLOCKED_WAITING_LIVE_E2E`，STOP 等外部環境就緒。

Supervisor 不得 self-promote readiness；完整真實鏈完成後仍需下一次 external Re-Gate 接受，才可改 readiness flags。

---

## 6. Product / manufacturing truth boundaries 維持不變

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

既有 REAL Blender / Product Truth evidence可保留；只有修改到對應 execution path 才重跑相關 REAL evidence。CI `FOX3D_MOCK_BLENDER=1` 仍不是 Production Ready。

---

## 7. 本輪交付與停止條件

完成後必須：

1. 新增上述 adversarial / fail-closed tests。
2. `pytest -v tests/test_supervisor.py` + full `pytest -q` 全綠。
3. CODE commit/push → 等 exact CODE Ubuntu + Windows CI SUCCESS。
4. 更新 current `GROK_PROGRESS_REPORT.md` / `CURRENT_IMPLEMENTATION_AUDIT.md` / `EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md`，truth labels 必須與實況一致。
5. DOCS commit/push → 等 exact DOCS Ubuntu + Windows CI SUCCESS。
6. Issue #1 發新的 machine-readable READY，至少：

```text
READY_FOR_RE_GATE
REPO=netfox-web/blender-autonomous-3d
ISSUE=1
INSTRUCTION_SHA=<this Round 5 instruction commit>
CODE_SHA=<exact code commit>
DOCS_SHA=<exact docs commit>
CODE_CI_RUN_ID=<run whose head_sha == CODE_SHA>
DOCS_CI_RUN_ID=<run whose head_sha == DOCS_SHA>
TEST_COUNT=<exact count>
EVIDENCE_GENERATION_ID=<exact generation>
REAL_BLENDER=<true|false>
USED_MOCK=<true|false>
```

7. 同時回報：
   - completeness gate 是否有任何 truncated critical evidence
   - live provider network call 是否完成
   - GitHub real webhook E2E 是否完成
   - Window B1 cross-evidence recovery tests 結果
8. 完成後 **STOP / WAIT FOR NEXT EXTERNAL RE-GATE**。
9. 不要自行進 Phase 961+；不要把 Mock / fixture / unit / CI / staging 冒充 Production Ready。
