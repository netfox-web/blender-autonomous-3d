# Grok 修正指令：Evidence Lineage Fail-Closed Fix — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Re-review head: `35a7e336f8406a8fbb36c637ff8096e1a01333a0`
> Evidence code commit: `d7a3075a2b0e621d748de949c0b7244bf5825c55`
> ChatGPT review result: **CHANGES REQUIRED**
>
> 這輪已修正大部分 Evidence Lineage：REAL acceptance 重新綁定 clean committed `CODE_EVIDENCE_SHA=d7a3075`，5/5 T1000 OptiX EvidenceBundle 的 `commitSha` / `expectedCommitSha` 一致、`usedMock=false`、artifact hash/size verifier PASS；GitHub Actions code/head 亦 GREEN。這些實質成果保留，不要重做 Phase 1–300。
>
> 但目前 `scripts/run_os_v2_e2e.py` 還有一個 **fail-open blocker**，因此暫不放行 Phase 301+。

---

## Blocker — REAL acceptance runner 最後永遠 exit 0

目前檔尾：

```python
if not real_ok:
    return 3
return 0 if all(p.get("label") == "REAL" for p in previews) or not previews else 0
```

這個 conditional 的兩個分支都是 `0`。因此在 **clean tree** 上，即使某個 REAL preview / EvidenceBundle verifier 失敗、artifact/hash 不符、commit mismatch 導致 preview label 變成 PARTIAL，runner 仍可能：

1. 寫出 canonical `*_REAL_ACCEPTANCE.json/.md`；
2. process exit code 仍為 0；
3. 外層 watcher/CI/操作員誤判 REAL acceptance 成功。

這違反上一輪要求：「commit mismatch / required REAL verifier failure 必須讓整個 REAL acceptance FAIL」。

---

## Fix 1 — runner 必須 fail-closed

修改 `scripts/run_os_v2_e2e.py`，建立單一明確的 `required_real_acceptance_ok`（名稱可不同），至少包含：

- `workingTreeClean == true`
- `realAcceptanceAllowed == true`
- Blender REAL discovery 成功
- OptiX REAL probe 成功
- 5 個 required preview 都存在
- 5/5 `preview.label == REAL`
- 5/5 `verify.ok == true`
- 5/5 `bundle.commitSha == evidenceCodeCommit`
- 5/5 `usedMock == false`
- 5/5 artifact exists + hash/size PASS
- release gate 到 `APPROVED_FOR_EXPORT` 成功
- engineering hash mutation 後 approval stale=true
- `LIVE_CNC` transition 被拒絕
- `LIVE_LASER` transition 被拒絕

只要任一 required REAL check fail：

- runner 必須 non-zero exit；
- 不得把該 run 宣稱 REAL acceptance PASS；
- 不得覆寫 canonical REAL acceptance truth files 為成功版本。

不要用「有 rows 就 exit 0」或「PARTIAL 也算成功」的邏輯。

---

## Fix 2 — canonical acceptance 寫入要 atomic / success-only

目前 `write_acc(...)` 在 required preview 全部驗證完成前就可能寫 canonical files。改成：

1. 先完整執行所有 required checks；
2. 計算 `required_real_acceptance_ok`；
3. 只有 `true` 才更新 canonical：
   - `docs/PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.json/.md`
   - `docs/RELEASE_GATE_REAL_ACCEPTANCE.json/.md`
   - 其他本 runner 定義為 REAL truth source 的 acceptance files
4. 若失敗，可在 stdout / temp diagnostics 提供原因，但**不要覆寫上一份已通過的 canonical REAL evidence**。

若你要保留失敗診斷檔，必須明確命名 `FAILED/UNVERIFIED`，不可被 acceptance loader 當 REAL truth source。

---

## Fix 3 — 補 integration regression tests

至少新增以下 regression；不能只測 `verify_bundle()` 單函式：

1. 5/5 valid REAL bundles → runner success / exit 0。
2. 任一 bundle `commitSha` stale/mismatch → runner non-zero，canonical REAL acceptance 不更新。
3. 任一 artifact hash/size mismatch → runner non-zero，canonical REAL acceptance 不更新。
4. 任一 preview `usedMock=true` 或 `realBlender=false` → runner non-zero。
5. 只有 4/5 required previews → runner non-zero。
6. dirty tree without override → non-zero（保留既有 test）。
7. dirty tree `--allow-dirty` → UNVERIFIED + non-zero + 不寫 canonical REAL acceptance。
8. forbidden LIVE_CNC 或 LIVE_LASER 若意外可通過 → runner non-zero。

測試可用 dependency injection / monkeypatch / temp docs root，避免真的啟 Blender；這些 regression 本身仍是 MOCK/unit evidence，不得標 Production Ready。

---

## Fix 4 — 重新跑 clean committed REAL evidence

修完 code/tests 後：

1. 先 commit/push code，記為新的 **CODE_EVIDENCE_SHA**。
2. 確認該 SHA GitHub Actions ubuntu + windows GREEN。
3. 在該 SHA 的 clean checkout 執行 REAL OS V2 E2E。
4. 必須再次得到 5/5 T1000 OptiX / Blender 5.2.1：
   - `usedMock=false`
   - artifact exists
   - hash/size verifier PASS
   - `bundle.commitSha == CODE_EVIDENCE_SHA`
   - `expectedCommitSha == CODE_EVIDENCE_SHA`
   - `workingTreeClean=true`
5. REAL acceptance 成功後再 commit docs/evidence，記為 **EVIDENCE_DOCS_SHA**。
6. EVIDENCE_DOCS_SHA / current head 的 GitHub Actions ubuntu + windows 也要 GREEN。

---

## Fix 5 — 文件同步

更新：

- `docs/GROK_PROGRESS_REPORT.md`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`（若本修正影響 Evidence Integrity 描述）
- `docs/REAL_E2E_ACCEPTANCE.md` 的 Phase 241–300 pointer（只需 SHA/runner lineage 更新）

Issue #1 回報：

- CODE_EVIDENCE_SHA
- EVIDENCE_DOCS_SHA
- local pytest 新總數（仍標 MOCK suite）
- code/head GitHub Actions run IDs
- 5/5 REAL evidence summary
- fail-closed regression 結果

---

## Truth labels 不變

- REAL：clean committed code 上的實際 Blender/OptiX + verified artifact/hash + deterministic release gate
- MANUAL/IMPORTED：supplier/material/hardware/logistics/FX snapshots；不是 LIVE_PROVIDER
- CONFIG_ESTIMATE / ENGINEERING_ESTIMATE：成本、McKee、未 lab certified 的工程估算
- MOCK：Vision / AI Video / Demand（MARKET_UNVERIFIED）
- PARTIAL：OS sandbox `PATH_GUARD_ONLY`、AR USDZ、print preflight/barcode、未認證 packaging strength
- BLOCKED：LIVE_CNC / LIVE_LASER / electrical compliance / liveProviderReady
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`

不要開 LIVE machine control，不要新增假 provider，不要把 MOCK CI 當 REAL Blender evidence。

---

## Exit criteria — 全部達成後再交回 ChatGPT

1. 修掉 `... else 0` fail-open bug。
2. 任一 required REAL evidence failure 都使 runner non-zero。
3. failed/unverified run 不覆寫 canonical REAL acceptance。
4. integration regressions 覆蓋 commit mismatch / hash mismatch / mock preview / 4-of-5 / dirty / LIVE_CNC-LASER。
5. 新 CODE_EVIDENCE_SHA clean-tree REAL run 5/5 PASS。
6. 5/5 bundles 綁新 CODE_EVIDENCE_SHA 且 verifier PASS。
7. local pytest PASS（MOCK suite, not Production Ready）。
8. CODE_EVIDENCE_SHA GitHub Actions ubuntu+windows GREEN。
9. EVIDENCE_DOCS_SHA/current head GitHub Actions ubuntu+windows GREEN。
10. Truth labels 保持原樣，`fullAutonomousFactoryReady=false`。
11. **不要進 Phase 301+，直到 ChatGPT re-review ACCEPT WITH SCOPE。**

只做這個 Evidence Integrity fail-closed 修正；不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Physical Product OS。