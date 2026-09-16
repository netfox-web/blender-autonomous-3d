# Development Agent 修正指令：PR #15 Round 7 Re-Gate — Strict Serialized Outer-State Identity Fencing

> Supervisor checkpoint: 2026-09-17
> Reviewed PR: #15 `codex/product-variant-batches` — DRAFT / OPEN / unmerged
> PR base: PR #12 branch `codex/model-category-tree` @ `68f64d604bb750c0c48830c0d50516ef5157d296`
> Reviewed CODE: `eaa4d683937e09a7de2e4b30e7156772a98ca596`
> Reviewed DOCS / PR head: `1b8687e1feb12ff305c3478b675c138d2f7b1666`
> CODE Actions: `35124100743` — Ubuntu + Windows SUCCESS
> DOCS Actions: `35126724135` — Ubuntu + Windows SUCCESS
> Decision: **CHANGES REQUIRED — Round 7 cleanup accepted in scope, but retained mutable-state identity fencing is still fail-open; Round 8 HOLD**
> Merge authorization: **false**
> Global Production Ready: **false**

## 0. Re-Gate result

Round 7 的 scoped hard-kill temp scavenging 本身方向正確，以下證據可保留：

- `scavenge_state_temps()` 只匹配 direct-child `state.json.[0-9a-f]{8}.tmp`；
- 只有持有相同 workspace 的 live `PreviewOwnership` 才可清理；
- live competitor 無法取得 ownership，因此不會清掉 live writer temp；
- unknown/nested temp、`owner.lock`、request/receipt/publication/authority sentinel 都保持不動；
- cleanup failure 在 fresh state write 前 fail-closed；
- 六組 real child-process hard-kill / fresh-process recovery case 有實質 OS/process evidence；
- Windows delete-sharing handle 與 Ubuntu 對應 kill/permission case 都有實際 OS 行為；
- Exact CODE `eaa4d683...` 與 DOCS `1b8687e1...` 的 GitHub Actions 都已雙平台 SUCCESS；
- clean REAL acceptance `61493611-302a-4503-a6a0-0a93e374e468` 保持 Blender 5.2.1 LTS / OptiX / `usedMock=false`，但輸入仍是 synthetic static fixture；
- generic/global temp cleanup 仍是 PARTIAL / UNCLAIMED；physical geometry / print / manufacturing / global readiness 仍 false / BLOCKED。

但是 Supervisor code review 找到一個 retained prerequisite 的實質 fail-open，因此 **不能把 Round 7 整體標為 ACCEPT，也不得進 Round 8**。

---

## 1. Blocker — `_write_owned()` 不是 exact serialized identity fencing

目前 `src/fox3d/recipe_preview_service.py`：

```python
current = read_json(path)
if not owner.held or any(current.get(k) != state.get(k) for k in ("taskId", "inputHash", "batchVersion")):
    raise ValueError(...)
atomic_json(path, state)
```

這是 Python value equality，不是 serialized identity exactness。

### Fail-open A — `true == 1`

當 in-memory owner state：

```json
{"taskId":"T","inputHash":"H","batchVersion":1}
```

而 persisted `state.json` 被改成：

```json
{"taskId":"T","inputHash":"H","batchVersion":true}
```

Python 中 `True == 1`，所以現有 comparator 會把不同 JSON type 誤判為相同 identity，然後 stale/live writer 可覆寫 persisted state。

這與 PR #15 前面已對 request / manifest / authority 做過的 strict serialized-type closure 原則不一致，也與 Round 6 文件宣稱的「exact `taskId/inputHash/batchVersion` mutable-state fencing」不一致。

### Fail-open B — optional key presence collapse

單一 composition state 可以沒有 `batchVersion`。現有 `.get()` 會把：

- expected：`batchVersion` key **absent**
- persisted：`"batchVersion": null`

都視為 `None`，因此 key-presence 不同仍可能通過 identity fence。

這不是 product/publication authority promotion，但它會讓 mutable-state writer 在 serialized identity 已不再 exact 的情況下繼續寫入，違反既有 fencing contract。

---

## 2. First reproduce on exact reviewed CODE

先在 exact CODE `eaa4d683937e09a7de2e4b30e7156772a98ca596` 上建立 focused regression，證明舊版真的 fail-open。不要先修改 production code。

至少保留以下 baseline：

### Case S1 — bool/int identity confusion

1. 建立 held `PreviewOwnership`；
2. in-memory state `batchVersion=1`；
3. persisted `state.json` 改成 `batchVersion=true`；
4. 呼叫現有 `_write_owned()`；
5. baseline 必須記錄舊 CODE 未拒絕／會覆寫的行為。

### Case S2 — absent/null presence confusion

1. in-memory single-composition state **不含** `batchVersion`；
2. persisted state 額外含 `"batchVersion": null`；
3. baseline 記錄現有 `.get()` comparator 未視為 identity mismatch。

若任一 baseline 無法重現，先停止並在 Issue #1 回報實際結果；不要臆測修正。

---

## 3. Minimal correction only

只修 `RecipePreviewService` outer mutable-state identity comparator。不要重寫 Queue / Renderer / DAM / Product Master / model batch request / receipt / publication / authority。

要求：

1. `taskId` 必須 key 存在、persisted 與 expected 都是 exact `str`，並 exact equality；
2. `inputHash` 必須 key 存在、persisted 與 expected 都是 exact `str`，並 exact equality；
3. `batchVersion` 的 **key presence 必須 exact match**；
4. 若 `batchVersion` 存在，兩邊都必須 `type(value) is int`，拒絕 `bool` / string / float / null；
5. 若 expected 不含 `batchVersion`，persisted 也不得偷偷多一個 null/false/0/1；
6. owner 必須仍 `held` 且 stream open；保留既有 ownership gate；
7. mismatch 時不得修復／normalize persisted state，不得寫回；原 bytes 必須保持不變；
8. 不要用 `int(...)`、`bool(...)`、truthiness 或其他 coercion；
9. 不需建立第二套 canonical state store；一個小型 helper / exact comparator 即可；
10. 不改 `scavenge_state_temps()` 已接受的 Round 7 scope，除非新 regression 證明它被此修正直接影響。

如要抽 helper，名稱應清楚表示 serialized mutable-state identity，例如 `_same_state_identity(current, expected)`；不要把它擴張成通用 schema framework。

---

## 4. Required regressions

至少新增：

- `batchVersion: true` vs expected `1` → BLOCK；
- `batchVersion: false` vs expected integer → BLOCK；
- `batchVersion: "1"` → BLOCK；
- `batchVersion: 1.0` → BLOCK；
- expected absent vs persisted `null` → BLOCK；
- expected absent vs persisted extra integer → BLOCK；
- exact absent/absent → PASS；
- exact integer/integer → PASS；
- wrong `taskId` → BLOCK（保留既有）；
- wrong `inputHash` → BLOCK（保留既有）；
- released ownership → BLOCK（保留既有）；
- mismatch 時 persisted `state.json` bytes 完全不變；
- `_run()` 的 `on_job` / `finally` 路徑遇到 serialized identity tamper 時不得覆寫 tampered/newer state；
- Round 6 stale callback/finally fencing regression 保持 PASS；
- Round 7 cleanup 35 focus 保持 PASS；
- Round 5 persistence 30 與 Round 6 ownership 21 保持 PASS。

Classification：

- pure comparator tests = **MOCK / unit regression**；
- serialized tamper blocking logic = **REAL_LOGIC**；
- existing subprocess ownership/recovery tests = **REAL_PROCESS_CONCURRENCY / REAL_PROCESS_RECOVERY / REAL_OS_IO** only where actual OS/process behavior is exercised；
- GitHub pytest 仍不是 REAL_RENDER / Production Ready。

---

## 5. Exact CODE gate

修正後：

1. freeze 一個新的 CODE SHA on PR #15；
2. exact CODE GitHub Actions Ubuntu + Windows 都必須 SUCCESS；
3. actual checkout SHA 必須等於新 CODE SHA；
4. 回報完整 test totals；
5. 回報 focused strict-identity regression count；
6. 保留 S1/S2 舊 CODE baseline fail-open 證據；
7. 若 CI 失敗，只修本 blocker，不要擴 scope。

Superseded / cancelled run 不得當 PASS evidence。

---

## 6. Retained Round 7 evidence gate

新 CODE 雙平台綠燈後，再確認：

- Round 7 A–F hard-kill cleanup cases仍 PASS；
- live owner competitor 仍 zero cleanup / zero write；
- unknown/nested/sentinel preservation 仍 byte-identical；
- cleanup failure 仍在 new state write 前 fail-closed；
- generic/global temp cleanup 仍 UNCLAIMED / PARTIAL；
- retained Round 5 recovery與 Round 6 process ownership/fencing 全部 PASS。

若 production code 只改 comparator，無需重新設計 cleanup harness；只需證明沒有 regression。

---

## 7. Clean REAL acceptance

因 production service code 有變更，exact CODE CI PASS 後重新跑既有 clean product-variant REAL acceptance：

- Blender 5.2.1 LTS；
- OptiX / `realOptix=true`；
- `usedMock=false`；
- 至少兩個 synthetic/reference variants；
- artifact SHA/size、finite pixels、`.blend` reopen；
- restart/history/download verification；
- retained 30 + 21 + 35 matrices PASS；
- retained cleanup cases PASS。

仍必須明確標示：

- `inputTruth=SYNTHETIC_STATIC_FIXTURE`；
- `physicalProductGeometryTruth=false`；
- `physicalPrintValidated=false`；
- `manufacturingReady=false`；
- `globalProductionReady=false`。

REAL Blender visual evidence ≠ physical product truth / print proof / manufacturing readiness。

---

## 8. DOCS closure

全部通過後只更新必要 acceptance docs：

- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.md`
- `docs/PRODUCT_VARIANT_BATCH_ACCEPTANCE.json`

新增：

- S1/S2 baseline fail-open；
- strict type + exact key-presence correction；
- focused regression results；
- new exact CODE SHA + CODE CI run；
- retained Round 7 cleanup evidence；
- new clean REAL acceptance generation；
- truth classification 不變。

然後 commit DOCS，跑 exact DOCS SHA Ubuntu + Windows CI；兩邊都 SUCCESS 才可 `READY_FOR_RE_GATE`。

不要為了「看起來最新」而重寫 `GROK_PROGRESS_REPORT.md`、`CURRENT_IMPLEMENTATION_AUDIT.md`、`REAL_E2E_ACCEPTANCE.md`、`CABINET_REAL_ACCEPTANCE.md`。只有它們宣告的 truth 真正改變才更新。

---

## 9. Existing gates remain frozen

- PR #15 remains **DRAFT / OPEN / unmerged**；
- **Round 8 HOLD** until this correction is Re-Gated；
- PR #16 remains **FROZEN DRAFT**；
- PR #13 / #14 unchanged；
- Issue #6 remains `BLOCKED_PR14_NOT_ON_MAIN`；
- no merge / retarget / rebase-to-main / cherry-pick；
- no live H3 / LTX / Vision / CNC / LASER / PLC work；
- `MERGE_AUTHORIZED=false`。

---

## 10. Final handoff

完成後在 Issue #1 留 **一則** `READY_FOR_RE_GATE`：

- baseline CODE `eaa4d683...` S1/S2 fail-open reproduction；
- new exact CODE SHA；
- CODE Actions run ID + Ubuntu/Windows totals；
- strict identity regression totals；
- retained Round 7 cleanup A–F result；
- clean REAL acceptance generation；
- DOCS SHA + DOCS Actions run ID + dual-platform result；
- REAL / MOCK / PARTIAL / BLOCKED truth matrix；
- `MERGE_AUTHORIZED=false`。

完成後 STOP。**不得自動進 Round 8。**
