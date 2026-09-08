# Grok 修正指令：Runner-Level Atomic REAL Acceptance — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Re-review head: `2968a8bdb56207ea4bc0abca79019ae43e1650a6`
> Evidence code commit: `6d9de7e4c57085054f373c63efe51eaccdf59f04`
> ChatGPT review result: **CHANGES REQUIRED**
>
> 本輪已實質修掉先前 `... else 0` 的 fail-open bug：`scripts/run_os_v2_e2e.py` 現在會計算 `requiredRealAcceptanceOk`，任一 required check 失敗時 return 4；5/5 REAL Blender evidence 已重新綁 `CODE_EVIDENCE_SHA=6d9de7e`，`usedMock=false`、Blender 5.2.1 + T1000 OptiX、commit/hash verifier PASS；CODE CI run `34267625716` 與 docs/head run `34267760938` 的 ubuntu+windows 都 GREEN。這些成果保留，不要重做 Phase 1–300。
>
> 但上一輪 exit criteria 還有兩個 Evidence Integrity 缺口，因此**仍不要進 Phase 301+**。

---

## Gap 1 — 目前 regression 沒有真正測 runner `main()` / process exit

`tests/test_acceptance_gate.py` 現在主要直接測：

- `required_real_acceptance_ok(...)`
- `write_canonical_if_ok(...)`

它證明 gate helper 的判斷，但**沒有直接呼叫 `scripts/run_os_v2_e2e.py::main()` 或 subprocess 執行 runner**。上一輪真正的 bug 就是在 runner 最後 return；只測 helper 無法防止未來再次出現「gate=False 但 runner exit 0」或「runner 先寫 canonical 再 fail」的整合回歸。

### 必修

新增 runner-level integration regressions，可用 dependency injection / monkeypatch，不需要真的啟 Blender。至少直接驗證：

1. 5/5 valid required evidence → `main(...) == 0`。
2. commit mismatch → `main(...) != 0`，canonical files 完全不變。
3. artifact hash mismatch → non-zero，canonical 不變。
4. artifact **size mismatch** → non-zero，canonical 不變。
5. `usedMock=true` 或 `realBlender=false` → non-zero。
6. 4/5 preview → non-zero。
7. dirty tree without override → non-zero。
8. `--allow-dirty` → UNVERIFIED + non-zero + canonical 不變。
9. LIVE_CNC 或 LIVE_LASER 如果沒有被拒絕 → non-zero。

測試名稱/結構不限，但必須測到 runner 的 return code，而不是只測 gate helper。

---

## Gap 2 — canonical truth files 目前 success-only，但不是真正 atomic batch

目前 `write_acc(...)` 雖然有：

```python
if not required_ok:
    return
```

這已避免 required gate FAIL 時覆寫 canonical，這點合格。

但通過 gate 後，runner 仍以多次 `Path.write_text(...)` 逐一寫 JSON / MD / 多個 acceptance files。若第 2、3、4 個檔案寫入期間發生 exception、磁碟錯誤或 process 中止，可能留下「一半是新 evidence、一半是舊 evidence」的 canonical truth set。這不符合上一輪要求的 **atomic / success-only**。

### 必修

不要改既有 acceptance schema，只把輸出機制 harden：

1. 先把本次所有 canonical JSON + MD 完整產生成記憶體 payload。
2. 全部寫到同一 docs root 下的 temporary/staging files。
3. staging 全部成功後才用 `os.replace()`（或同等 atomic replace）發布 canonical files。
4. 若 staging/replace 前 validation 失敗，不得改任何 canonical。
5. 若 publish 中途 exception，至少要能保證 canonical set 不被當成本輪完整 PASS；建議使用 manifest/generation id 或 backup+rollback，讓 reader 不會混讀不同 generation。
6. canonical acceptance 加入一致的 `acceptanceGenerationId`（或等價欄位）並在 aggregate acceptance 驗證所有本輪 truth files 同 generation / 同 `evidenceCodeCommit`。

不要新增第二套 Acceptance 系統；沿用現在 `write_acc` / EvidenceBundle / existing docs。

---

## Gap 3 — 補 atomic publish failure regression

至少加入一個 regression：

- 先建立一組 OLD canonical sentinel files。
- 模擬本輪 required evidence 全 PASS。
- monkeypatch 第 N 個 staging/publish write/replace 故意拋 exception。
- runner 必須 non-zero。
- 驗證 canonical reader 不會看到「部分 NEW + 部分 OLD」被當成有效同一輪 REAL acceptance。

再加入 successful publish regression：所有 canonical truth files 都有相同 `acceptanceGenerationId`、相同 `evidenceCodeCommit`。

這些仍是 MOCK/unit integration evidence，不得標 Production Ready。

---

## 重新驗收流程

修完後：

1. commit/push code + tests，記為新的 **CODE_EVIDENCE_SHA**。
2. CODE_EVIDENCE_SHA GitHub Actions ubuntu + windows 必須 GREEN。
3. local pytest PASS，清楚標示 MOCK suite。
4. 在新 CODE_EVIDENCE_SHA 的 clean checkout 執行 REAL OS V2 E2E。
5. 5/5 T1000 OptiX / Blender 5.2.1：
   - `usedMock=false`
   - artifact exists
   - hash + size verifier PASS
   - `bundle.commitSha == CODE_EVIDENCE_SHA`
   - `expectedCommitSha == CODE_EVIDENCE_SHA`
   - `workingTreeClean=true`
6. `requiredRealAcceptanceOk=true` 且 runner exit 0。
7. 所有 canonical truth files 同 `acceptanceGenerationId` / 同 evidence commit。
8. 再 commit docs/evidence，記為 **EVIDENCE_DOCS_SHA**。
9. EVIDENCE_DOCS_SHA/current head GitHub Actions ubuntu + windows GREEN。

---

## 文件同步

更新：

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/REAL_E2E_ACCEPTANCE.md` 的 evidence pointer

並修正措辭：目前 `tests/test_acceptance_gate.py` 在 runner-level tests 補上前，只能稱 **gate/unit regressions**，不要稱完整 runner integration regression。

Issue #1 回報：

- 新 CODE_EVIDENCE_SHA
- EVIDENCE_DOCS_SHA
- local pytest 總數（MOCK suite）
- code/head CI run IDs
- runner-level fail cases 實測摘要
- atomic publish rollback/failure regression
- 5/5 clean-tree REAL evidence summary

---

## Truth labels 維持不變

- REAL：clean committed code 上的實際 Blender/OptiX + verified artifact/hash/size + deterministic release gate
- MANUAL/IMPORTED：supplier/material/hardware/logistics/FX snapshots；不是 LIVE_PROVIDER
- CONFIG_ESTIMATE / ENGINEERING_ESTIMATE：成本、McKee、未 lab certified 工程估算
- MOCK：Vision / AI Video / Demand（MARKET_UNVERIFIED）
- PARTIAL：OS sandbox `PATH_GUARD_ONLY`、AR USDZ、print preflight/barcode、未認證 packaging strength
- BLOCKED：LIVE_CNC / LIVE_LASER / electrical compliance / liveProviderReady
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`

不要開 LIVE machine control，不要新增假 provider，不要把 CI MOCK suite 當 REAL Blender evidence。

---

## Exit criteria — 全部達成後再交回 ChatGPT

1. runner-level tests 直接驗證 `main()` / exit code。
2. commit/hash/size/mock/4-of-5/dirty/LIVE_CNC-LASER failure 都 runner non-zero。
3. canonical truth set 使用 atomic/staged publish，不留下可被誤認為同一輪 PASS 的混合 generation。
4. publish failure regression PASS。
5. successful publish 的 canonical truth files generation/commit 一致。
6. 新 CODE_EVIDENCE_SHA clean-tree REAL run 5/5 PASS。
7. local pytest PASS（MOCK suite, not Production Ready）。
8. code/head GitHub Actions ubuntu+windows GREEN。
9. Truth labels 保持原樣，`fullAutonomousFactoryReady=false`。
10. **不要進 Phase 301+，直到 ChatGPT re-review ACCEPT WITH SCOPE。**

只做這個 Evidence Integrity hardening；不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Physical Product OS。