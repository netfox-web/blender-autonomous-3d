# Grok 修正指令：Phase 241–300 Evidence Lineage Fix — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Review baseline: `f4748fadff4567e7cbdb8646ee56deee48be5102`
> Reviewed code commit: `f695eef6ea6bab0a359ffe4e3e9dfd2ee241018f`
> ChatGPT review result: **CHANGES REQUIRED**
>
> Phase 241–300 有大量實質完成，GitHub Actions `34256429183` on `f695eef` 與 current-head run `34256546557` on `f4748fa` 都是 SUCCESS（ubuntu + windows）。Local `pytest -q` 回報 101 passed，但仍只是 MOCK-Blender regression suite，不得當 Production Ready。
>
> 本輪主要阻擋不是功能，而是 **REAL EvidenceBundle 的 commit lineage 不正確**：`docs/PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.json` 的 top-level `commitSha` 與 5 個 REAL preview EvidenceBundle 目前都記成舊的指令 commit `b9e7861...`，但 Phase 241–300 的實際 code commit 是 `f695eef...`。這代表 REAL artifacts 是在未提交 working tree 上產生，`git rev-parse HEAD` 指向舊基線，不能證明 committed code `f695eef` 就是被驗收的內容。Phase 242–243 的 Evidence Integrity 目標因此尚未真正達標。
>
> **不要開始 Phase 301+。先只修下面 Evidence Lineage / Acceptance hygiene。不要重寫既有架構。**

---

## Fix 1 — REAL acceptance 必須從 clean committed tree 執行

修改 `scripts/run_os_v2_e2e.py`（或共用 acceptance runner）讓 Production/REAL acceptance 在開跑前檢查：

- `git status --porcelain` 必須為空；若有 tracked/untracked working-tree 變更，REAL acceptance 直接 FAIL。
- 取得 `git rev-parse HEAD` 作為唯一 `evidenceCodeCommit`。
- 禁止把 instruction/base commit 當作新 code evidence commit。
- 若保留 dev-only `--allow-dirty`，該模式產物一律只能標 `PARTIAL/UNVERIFIED`，不得寫入 REAL acceptance。

建議輸出欄位：

- `evidenceCodeCommit`
- `workingTreeClean=true`
- `acceptanceRunnerVersion`
- `generatedAt`

不要因為後續 docs commit 不同就把 evidenceCodeCommit 改成 docs commit；REAL evidence 要綁「實際被執行的 committed code」。

---

## Fix 2 — EvidenceBundle verifier 加 expected commit 驗證

`verify_bundle(...)` 增加可選但 REAL acceptance 必填的 `expected_commit_sha`（或等價機制）。

REAL bundle 必須同時滿足：

- `bundle.commitSha == evidenceCodeCommit`
- `usedMock == false`
- `realBlender == true`
- job completed/succeeded
- artifact exists
- artifact hash/size matches
- engineering/BOM lineage 可追

若 commit mismatch，至少回傳明確錯誤，例如 `commit_sha_mismatch`，整個 REAL acceptance FAIL。

新增 regression tests：

1. correct commit → PASS
2. stale/base/instruction commit → FAIL
3. dirty-tree REAL run → FAIL
4. `--allow-dirty`（若存在）不得產 REAL label

---

## Fix 3 — 重新產生 Phase 241–300 REAL evidence

正確流程必須是兩階段：

1. 先把 code/evidence-runner 修正 commit 到 main（記為 **CODE_EVIDENCE_SHA**）。
2. 在該 commit 的 **clean checkout** 上重新執行 `scripts/run_os_v2_e2e.py`。
3. 重新產生：
   - `docs/PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.json/.md`
   - `docs/RELEASE_GATE_REAL_ACCEPTANCE.json/.md`
   - `docs/COMMERCIAL_COST_ACCEPTANCE.json/.md`
   - `docs/PACKAGING_V2_ACCEPTANCE.json/.md`
   - 其他被本 script 更新的 domain acceptance
4. 產生後再另做 docs/evidence commit（記為 **EVIDENCE_DOCS_SHA**）。

驗收 JSON 必須明確留下：

- `evidenceCodeCommit = CODE_EVIDENCE_SHA`
- top-level commit lineage 不再是 `b9e7861`
- 每一個 REAL preview EvidenceBundle 的 `commitSha = CODE_EVIDENCE_SHA`
- `workingTreeClean=true`

至少重新驗證 5-family REAL previews：KD / Retail / Packaging / Acrylic / 第二個 KD family；仍需 T1000 OptiX、Blender 5.2.1、`usedMock=false`、artifact hash/size verifier PASS。

---

## Fix 4 — Release Gate acceptance 不能只靠 Markdown row

`RELEASE_GATE_REAL_ACCEPTANCE.json` 必須保留可機器驗證的：

- EvidenceBundle verifier result
- expected code commit
- approval audit event hash
- stale-on-engineeringHash mutation
- forbidden `LIVE_CNC` / `LIVE_LASER` transition
- `APPROVED_FOR_EXPORT != LIVE_CNC`

Markdown 可以是 summary，但 JSON 才是 truth source。

---

## Fix 5 — CI / test evidence 同步

修正後必須同時提供：

- CODE_EVIDENCE_SHA 的 GitHub Actions GREEN：ubuntu-latest + windows-latest
- EVIDENCE_DOCS_SHA（current head）的 GitHub Actions GREEN：ubuntu-latest + windows-latest
- local pytest 新總數（>=101）；仍標 `MOCK suite, not Production Ready`

CI GREEN 只證明 regression suite，不等於 REAL Blender。REAL Blender 仍以上述 clean-commit EvidenceBundle 為準。

---

## Fix 6 — 文件 truth cleanup

同步：

- `docs/GROK_PROGRESS_REPORT.md`：記錄 CODE_EVIDENCE_SHA / EVIDENCE_DOCS_SHA、兩個 CI run、REAL evidence clean-tree lineage。
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md` 開頭仍寫舊的 `7e1d11c + local gap-fill`，改成 current review/code baseline，避免誤導；歷史內容可保留。
- `docs/REAL_E2E_ACCEPTANCE.md` 加一段 Phase 241–300 evidence pointer，明確指出 `globalProductionReady=false`、`fullAutonomousFactoryReady=false`。
- 不得把 MANUAL/IMPORTED provider snapshot 改稱 LIVE_PROVIDER。
- McKee BCT / print preflight / barcode / AR USDZ / PATH_GUARD_ONLY 仍維持 ENGINEERING_ESTIMATE/PARTIAL。

---

## Truth labels 必須維持

- REAL：clean committed code 上實際執行、可驗 artifact/hash 的 Blender/OptiX、release gate、deterministic validators
- MANUAL/IMPORTED：supplier/material/hardware/logistics/FX snapshots
- CONFIG_ESTIMATE / ENGINEERING_ESTIMATE：沒有 live/lab evidence 的成本、強度與風險估算
- MOCK：Vision / AI Video / Demand（MARKET_UNVERIFIED）
- PARTIAL：OS sandbox PATH_GUARD_ONLY、AR USDZ、print preflight/barcode、未認證 packaging strength
- BLOCKED：LIVE_CNC / LIVE_LASER / electrical compliance / liveProviderReady
- `globalProductionReady=false`
- `fullAutonomousFactoryReady=false`

---

## Exit criteria — 全部達成後才交回 ChatGPT

1. Evidence runner 在 dirty tree 會拒絕 REAL acceptance。
2. `verify_bundle` 可檢查 expected commit SHA 並有 regression tests。
3. 新 REAL acceptance 是在 clean **CODE_EVIDENCE_SHA** 上重新跑出。
4. 所有 5 個 REAL preview bundles 的 `commitSha == CODE_EVIDENCE_SHA`，不再是 `b9e7861`。
5. 5/5 T1000 OptiX artifacts `usedMock=false` 且 hash/size PASS。
6. Local pytest >=101 PASS（仍是 MOCK suite）。
7. CODE_EVIDENCE_SHA GitHub Actions ubuntu+windows GREEN。
8. EVIDENCE_DOCS_SHA / current head GitHub Actions ubuntu+windows GREEN。
9. Progress/Audit/REAL_E2E 文件同步 truth labels。
10. 不進 Phase 301+，直到 ChatGPT re-review **ACCEPT WITH SCOPE**。

不要重寫 Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Physical Product OS 架構；只修 Evidence Integrity 與必要 regression。