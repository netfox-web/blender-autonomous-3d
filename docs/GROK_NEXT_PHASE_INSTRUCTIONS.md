# Development Agent 修正指令：Event-Driven Supervisor Re-Gate Round 6 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed instruction: `75957548e588a44a9e2f991f60dc79348e257733`
> Reviewed CODE: `b0ad38a82aa7b9676f140221d42623b844083d48`
> Reviewed DOCS/head: `92f1574370102c9feea89839c39a5887f4caf6e9`
> CODE Actions: `34779985884` — Ubuntu `103785109489` SUCCESS / Windows `103785109547` SUCCESS
> DOCS Actions at review time: `34781084245` — **IN_PROGRESS**（尚不可當完成證據）
> Reported regression: **754 passed**; Supervisor-specific: **56 passed**
> REAL Blender generation reported: `4d715131-3eb3-4ed6-8dab-376eb92087ec`
> Re-Gate result: **CHANGES REQUIRED (Round 6)**
> `webhookRealE2e=false`; `eventDrivenSupervisorReady=false`; `liveProviderReady=false` 必須維持。
> **Phase 961+ remains HOLD.**

## 0. 本輪已接受的實質進展 — 保留，不要重寫

以下可保留為 **REAL_LOGIC / TESTED** software evidence：

- `EvidenceSectionCompleteness`、critical truncation fail-closed 架構已加入。
- required pinned evidence 已改成 typed fetch status，主要路徑可在 provider call 前 fail closed。
- changed-file status parser 已支援 A/M/D/R + rename old/new path。
- live external provider 的 `SUPERVISOR_AI_MODEL` 已要求非空並做 provider prefix validation。
- machine contract boolean typo、40-char SHA、CODE CI id 等已有更嚴格 parsing/validation。
- CODE `b0ad38a...` 的 GitHub Actions `34779985884` 已確認 Ubuntu + Windows SUCCESS。
- 回報 `754 passed` / `56 Supervisor tests` 可視為軟體測試證據；GitHub CI 使用 `FOX3D_MOCK_BLENDER=1`，不得視為 REAL Blender / Production Ready。
- REAL Product Truth render generation `4d715131-...` 可保留為既有 Blender evidence，但它不是 live Supervisor webhook/provider E2E。
- readiness truth boundary 正確維持：`webhookRealE2e=false`、`eventDrivenSupervisorReady=false`、`liveProviderReady=false`。

不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth 或既有 Supervisor control-plane。只修以下剩餘 fail-closed / lineage 問題。

---

## 1. Blocker A — Window B1 remote adoption 仍不是「exact lineage」

目前 `engine.py` 的 recovery candidate 仍有過寬條件：

- `has_code` 仍允許 `code {CODE_SHA[:7]}` short-SHA fallback。
- `Reviewed-Docs-Sha` / `Reviewed-Instruction-Sha` / `Supervisor-Decision` 目前只有「若 trailer 存在才比對」；**缺 trailer 仍可能通過**。
- remote blob fetch exception 被 `except: pass` 吞掉後，candidate 仍可能被採用。
- blob 只有在碰巧含 evidence marker 時才檢 CODE，沒有強制要求完整 `DOCS_SHA / INSTRUCTION_SHA / DECISION / REVIEW_ID` marker。
- 尚未把 remote blob 的 exact digest/content 與本輪 intended instruction output 綁定。
- 若 DB 已有 `staged_sha`，目前直接採用，沒有重新確認 remote commit / remote blob identity / digest。

這和目前 Audit / Acceptance 宣稱的「5 trailer + blob exact adoption」不一致。

### Required correction

1. 刪除所有 short-SHA / legacy fuzzy adoption fallback。Window B1 採用 candidate 必須 **無條件同時具備且 exact match**：
   - full `Reviewed-Code-Sha`
   - full `Reviewed-Docs-Sha`
   - full `Reviewed-Instruction-Sha`
   - full `Reviewed-Evidence-Id`
   - `Supervisor-Decision`
   - `Supervisor-Review-Id`
2. 任一 trailer 缺失 = reject candidate，不可視為相容舊格式而 adopt。
3. remote `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` blob 必須成功讀取；404 / timeout / auth / empty / exception 全部 fail closed，不得 `except: pass`。
4. remote blob identity marker 必須 exact 包含：CODE / DOCS / prior INSTRUCTION / EVIDENCE / DECISION / REVIEW_ID。
5. 在 write 前 durably persist intended instruction content digest（建議 full SHA256）與 review identity；crash recovery adoption 必須驗 remote blob SHA256 == intended digest。
6. DB `staged_sha` 也不能直接信任；使用前同樣驗：remote commit 存在、full trailers、remote blob identity、digest。
7. 找到 0 candidates → 正常建立一次；找到 1 exact candidate → adopt；找到 >1 → fail closed。

### Required tests

- 只有 short CODE SHA + evidence id → 不得 adopt
- 缺 DOCS / prior instruction / decision / review-id 任一 trailer → 不得 adopt
- forged commit message但 blob marker不完整 → 不得 adopt
- blob fetch exception / empty → 不得 adopt
- staged SHA 指向錯誤 remote blob → 不得 adopt
- exact 6-field identity + exact intended digest → adopt exactly once
- 同 CODE、不同 evidence id / review id → 不得 cross-adopt
- multiple exact candidate → fail closed

---

## 2. Blocker B — REAL Blender required evidence 不得用 Product Truth acceptance 替代

目前 `_execute_review()`：

`docs/REAL_E2E_ACCEPTANCE.md` 取不到時，會 fallback 成 `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md`，然後把 fallback 成功視為 REAL acceptance gate 已滿足。

Round 5 指令要求的是：若 `REAL_BLENDER=true && USED_MOCK=false`，**`docs/REAL_E2E_ACCEPTANCE.md @ DOCS_SHA` 本身必須成功讀取**。

### Required correction

1. `REAL_BLENDER=true && USED_MOCK=false` 時：
   - `docs/REAL_E2E_ACCEPTANCE.md @ DOCS_SHA` = mandatory。
   - 404 / empty / timeout / auth / fetch error → provider not called + `CHANGES_REQUIRED`。
2. `PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md` 可另外當 supporting evidence，但不得代替 REAL_E2E mandatory source。
3. fetch status / audit trail 要分開記兩份來源，不得把 fallback path 偽裝成 REAL_E2E。

### Required tests

- REAL_E2E 404，但 Product Truth acceptance 存在 → provider **not called**，no ACCEPT
- REAL_E2E empty / timeout → no ACCEPT
- REAL_E2E exact pinned OK → 才可繼續 review

---

## 3. Blocker C — Changed-file completeness 目前不是 independent authority；diff range metadata 也不一致

目前：

- `actual_diff_paths` 與 `context.changed_file_items` 都源自同一個 `parse_diff_changed_files(diffs)`，再拿兩者互相比，實際上不是 independent check。
- `context.diffs` 是 engine 以 `instruction_sha -> docs_sha` 取得；但 provider prompt metadata 卻標成 `instruction_sha..code_sha`。也就是 **metadata 宣稱的 ref range 與實際 supplied diff bytes 不一致**。

這會破壞 evidence provenance。

### Required correction

1. 建立獨立 authoritative changed-file source，優先使用 GitHub compare metadata / `git diff --name-status` 的獨立結果，不得與 prompt manifest 共用同一個 list object 當「自我驗證」。
2. exact compare：status + path；rename 必須 old/new path 都一致。
3. manifest 少檔、增生不存在檔、status spoof、rename path mismatch → no ACCEPT。
4. 明確拆開兩段 evidence：
   - **CODE diff**：`INSTRUCTION_SHA .. CODE_SHA`
   - **DOCS diff**：`CODE_SHA .. DOCS_SHA`
5. 每一段 metadata 的 `ref_sha/range` 必須與真正 supplied bytes 完全一致；不得把 instruction..DOCS 的內容標成 instruction..CODE。
6. completeness / SHA256 對各段獨立記錄。

### Required tests

- DOCS commit 新增文件不得混進「CODE diff」卻仍標 CODE range
- authoritative compare 有檔案而 manifest 漏掉 → no ACCEPT
- manifest status M，但 authoritative status A/D/R → no ACCEPT
- rename old/new path spoof → no ACCEPT
- metadata range 與實際 diff source不一致 → no ACCEPT

---

## 4. Blocker D — live contract parse boundary 與 provider request ID audit 尚未完整

### 4.1 DOCS_CI_RUN_ID 必須在 strict parser boundary 就 fail closed

目前 `validate_strict(is_live=True)` 對 `DOCS_CI_RUN_ID` 是「有值才驗正整數」，缺值時 model-level strict validation本身不 reject；雖然 engine 後段 live mode 會擋，但 machine contract 應在進 GitHub verification 前就拒絕。

Required：

- live strict contract：`CODE_CI_RUN_ID` 與 `DOCS_CI_RUN_ID` 都 mandatory、positive numeric。
- `parse_from_text(..., strict=True)` 缺 DOCS CI → reject before GitHub API。
- legacy `CI_RUN_ID` 不得在 live contract 悄悄代替 DOCS CI。

### 4.2 Provider request/review ID 要進 audit

目前 external HTTP call 只回傳 provider text，OpenAI / Anthropic 等 response 的 request/message id 沒被保留；audit 只有 provider + model。

Required：

- provider call 回傳 structured result：至少 `text` + `provider_request_id`（provider 有回 id 時）。
- Audit 記：provider、model、provider_request_id、review id、4 reviewed identities、timestamp。
- provider 無 id 時明確 `null/unavailable`，不可偽造。
- 不得記 API key / Authorization header。

### Required tests

- strict READY 缺 `DOCS_CI_RUN_ID` → parser reject，GitHub client 0 calls
- malformed DOCS CI id → reject
- OpenAI/Anthropic fixture response含 id → audit exact capture id
- provider response無 id → audit explicit unavailable/null

---

## 5. Exact DOCS CI 尚未完成

本次 external Re-Gate 時，DOCS SHA `92f1574370102c9feea89839c39a5887f4caf6e9` 的 Actions `34781084245` 仍是 **IN_PROGRESS**。

因此即使 A–D 沒有上述問題，本輪仍不能 ACCEPT。

完成 Round 6 修正後，必須重新形成新的 exact lineage：

1. CODE commit → Ubuntu + Windows SUCCESS。
2. DOCS commit（Progress/Audit/Event Supervisor Acceptance 等）→ Ubuntu + Windows SUCCESS。
3. machine-readable READY 必須帶 exact：
   - INSTRUCTION_SHA
   - CODE_SHA
   - DOCS_SHA
   - CODE_CI_RUN_ID
   - DOCS_CI_RUN_ID
   - TEST_COUNT
   - EVIDENCE_GENERATION_ID
   - REAL_BLENDER
   - USED_MOCK
4. Progress/Audit/Acceptance 不得再宣稱「strict B1 exact adoption」除非上述缺 trailer / blob error / digest cases確實全部測過。
5. 發 READY 後 STOP，等待 external Re-Gate；不得自行改 readiness flags。

---

## 6. REAL / MOCK / PARTIAL / BLOCKED 邊界

目前維持：

- Supervisor software control plane：**REAL_LOGIC / TESTED**
- external provider adapters：**REAL_LOGIC / ADAPTER**；live production invocation 尚未證實
- CODE GitHub CI：**TESTED / MOCK_BLENDER CI**，不是 REAL Blender production evidence
- reported Product Truth Blender generation：可保留 **REAL Blender scoped evidence**，不是 Supervisor live E2E
- Webhook real E2E：**BLOCKED / false**
- Live provider production ready：**BLOCKED / false**
- Event-driven Supervisor production ready：**BLOCKED / false**
- Vision Judge / Demand / AI Video：維持 MOCK/BLOCKED 既有標籤
- Physical print：**BLOCKED / false**
- LIVE_CNC / LIVE_LASER / PLC / machine control：**BLOCKED**
- `commercialAssetProductionReady=false`
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`
- `liveFactoryExecutionReady=false`
- **Phase 961+ HOLD**

---

## 7. 真正 live E2E gate 仍是最後一步

只有 A–D 全修、new CODE + DOCS exact CI 雙平台全綠後，才進：

authorized Issue READY → real GitHub webhook delivery → HMAC verified → exact contract/CI/evidence → **real configured provider network call** → 4 identities exact → exactly one instruction commit → exactly one Issue comment → watcher claim exactly once → replay no duplicate。

Acceptance 必須保留 GitHub delivery ID、review ID、provider/model/request id、CODE/DOCS/prior INSTRUCTION、evidence id、CI run/job ids、completeness digests、result instruction SHA、Issue comment ID、watcher claim、timestamps/retry count。

沒有真 public webhook / credential 就明確回 `BLOCKED_WAITING_LIVE_E2E`，保持三個 readiness=false；禁止 Mock 冒充。

完成後 push CODE → 等 CODE CI → 更新 DOCS → 等 DOCS CI → Issue #1 machine-readable READY → STOP。
