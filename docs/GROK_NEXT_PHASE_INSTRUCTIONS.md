# Grok 修正指令：Phase 781–840 Re-Gate Round 2 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `3662964d4b807a2a43ce548d729d42cbbcb9d43a`  
> CODE_EVIDENCE_SHA reviewed: `81496b5cf8f63345183bdf69a6f4d1fe972a6ee6`  
> Canonical generation reviewed: `6ae08726-2ec8-43ab-b9da-c0fc76974574`  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪只修 Phase 781–840 的 artwork render/authority 缺口。**不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore。**

## 已接受，不要退步

- `pytest -q`：**584 passed**。
- exact CODE Actions `34503006687` on `81496b5…`：Ubuntu + Windows **SUCCESS**。
- exact docs/head Actions `34503474163` on `3662964…`：Ubuntu + Windows **SUCCESS**。
- canonical generation `6ae08726-…` runner-bound to `81496b5…`，`workingTreeClean=true`。
- Engineering door face 與 Blender door mesh 已移除 hidden `-0.002m`；此修正接受。
- production path 已改由 `placementId` re-resolve surface/artwork/master，forged caller crop/hash 基本 negative 已有。
- 2/3/4 door fixtures、limiting-axis DPI、keep-out/stale/cross-tenant/cross-product/version/tamper/stretch/NaN/duplicate negatives 有實質進步。
- `realArtworkPreviewReady=false`、`physicalPrintValidated=false`、global/full/live readiness=false 維持正確。
- CI 仍 `FOX3D_MOCK_BLENDER=1`：只能算 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不是 Production Ready。
- LIVE_CNC / LIVE_LASER / PLC 繼續 **BLOCKED**；Demand / Vision / AI Video 繼續 **MOCK**；print preflight 繼續 **PARTIAL**。

---

# Blocker 1 — Canonical crop 在 Blender 被套了兩次

目前 `scripts/blender_job.py::apply_canonical_artwork()` 同時：

1. 把 mesh UV layer 寫成 canonical crop corners；又
2. 把同一個 `uvRect` 寫進 Mapping node `Location/Scale`；rotation 也同時進 corners 與 Mapping rotation。

這不是「同一份 SOT」，而是**同一 transform 疊兩次**。例如第一片 `u=0..0.25` 若 UV 已是 `0..0.25`，再乘 `scale=.25`，實際可能只採樣到 `0..0.0625`。目前 pytest 只在無 `bpy` 的 dict path 比 `corners`，沒有驗證 Blender shader 最終採樣結果，因此 584 PASS 不能證明畫面 crop 正確。

Required correction：

- 選 **一種** canonical mapping authority：
  - A. mesh UV 就是 final source UV，Mapping node保持 identity；或
  - B. mesh face UV 固定 0..1，全部 canonical crop/rotation/mirror 只由單一 Mapping transform完成。
- 禁止 UV layer + Mapping 對同一 crop/rotation 重複套用。
- 4-door master 的最終 source sampling 必須精確為：`0..0.25 / 0.25..0.5 / 0.5..0.75 / 0.75..1.0`，不是只檢查 payload 裡的數字。
- 90/180/270 rotation 與 mirror 各只能生效一次。
- 增加可計算的 final UV sampling verifier；若本機 Blender 5.2.1 + T1000 可用，再跑至少一個 REAL diagnostic color-grid render，證明四片門實際畫面取到正確象限/色塊。無 REAL 環境時可保持 `realArtworkPreviewReady=false`，不得假造。

---

# Blocker 2 — Artwork 目前套到整個 cube，不是 exact FRONT printable face

目前 code `materials.clear(); append(mat)` 後，整個 door object 共用 artwork material；UV 又用 `loop.index % 4` 寫所有 loops。這無法證明 artwork 只作用在 `PrintableSurface.face=FRONT`，側邊/背面也可能吃到同一圖。

Required correction：

- 依 existing engineering object + `PrintableSurface.face` 找到**唯一可驗證的 front polygon set**；只對該 printable face 套 artwork material/UV。
- 其他 non-printable faces 保持原本 base material，不可一起貼圖。
- 不可用「第 N 個 polygon」硬猜；要用 deterministic local normal / face identity，且 orientation 必須與 canonical FRONT 定義一致。
- 找不到唯一 target face、normal/orientation 不一致、object geometry 不符 engineering dimensions時 → fail closed。
- 加 test 驗證 front face material index/UV 被改、side/back 未被 artwork material 污染。

---

# Blocker 3 — REAL preview proof 仍然 fail-open

`build_and_render()` 成功結果目前沒有輸出 `artworkApplied=true` 或 exact applied placement lineage；但 `preview()` 使用：

`done.get("artworkApplied") is not False`

也就是 success result **缺少 `artworkApplied` 欄位時仍被視為 applied**。未來只要 REAL Blender generic render 成功，就可能錯把「有 render」當成「artwork 已正確套用」。

Required correction：

- `build_and_render()` 在 artwork job 成功時必須明確輸出：
  - `artworkApplied: true`
  - exact `appliedPlacements[]`（object/component identity + engineeringHash + surfaceHash + artworkHash + placementHash + final UV transform/hash）
  - output artifact path/sha256/size（若 worker wrapper已有 canonical artifact metadata就重用，不要第二套 DAM）。
- `preview()` 只能在 `done["artworkApplied"] is True` 時視為 applied；missing/null/false 一律 fail closed。
- requested placements 與 `appliedPlacements` 必須 exact-set match，不可只驗第一筆或只看 job success。
- `realArtworkPreviewReady=true` 至少還需：`usedMock=false`、realBlender、blenderVersion、device、render artifact SHA/size、exact lineage match。
- 加 negative：REAL-shaped succeeded response 但缺 `artworkApplied` / 缺 applied lineage / wrong placementHash → `realArtworkPreviewReady=false`。

---

# Blocker 4 — `placementHash` 沒有綁住所有真正會影響 render 的欄位

目前 `placement_payload()` 未包含 `uv`、`mirrored`、`objectName`、product/candidate/version 等 render/identity 欄位；`require_placement()` 也沒有重新計算 stored `placementHash`。因此若 in-memory/persisted placement 的 `uv` 或 mirror 被改，Blender payload 可以變，但原 `placementHash` 仍不變。

Required correction：

- 不可讓 mutable stored `uv` 成為 Blender authority。
- 兩種可接受方案擇一：
  1. 將所有 render-affecting canonical fields 納入 placement hash，讀取時重新 hash exact compare；或
  2. `uv/mirror/orientation/object target` 每次由 authoritative Surface + Placement mm + MasterCrop 重新推導，stored copy只作 projection，若存在則 exact compare。
- 至少要綁/驗：tenant/product/candidate/version（where applicable）、engineeringHash、surfaceId/surfaceHash、artworkId/artworkHash、x/y/w/h、rotation、fit、mirror/orientation、object/component identity、masterHash/masterCrop（master split時）、final UV transform。
- `blender_job_payload()` 不可直接信任任意 mutable rec；必須從 `require_placement()` + authoritative re-derivation 產生。
- 加 coordinated tamper tests：只改 `uv`、只改 mirror、改 `uv + copied projection fields`、改 objectName/component、改 masterCrop + copied hash field → 全部 BLOCK/STALE，不得進 successful render payload。

---

# Blocker 5 — `produce_panel()` 把所有 door placement 都當成 multi-door master split

目前 production path 不論 placement 是由 `place()` 還是 `place_across_panels()` 產生，最後都呼叫 `_authoritative_master()`，並以同產品所有 `DOOR*` siblings 重算 master/crop。

這會讓**單門 artwork** 出錯：例如只在 4 門櫃 `DOOR_2` 放一張完整單門圖，production 仍可能把原圖當成跨 4 門 master，輸出第二個 1/4 crop。

Required correction：

- Placement 必須有明確、canonical、hash-bound 的 relation/mode，例如 existing schema最小延伸：`SINGLE_SURFACE` vs `MASTER_SPLIT`；不要靠 `componentId.startswith("DOOR")` 猜。
- `SINGLE_SURFACE`：production 使用該 placement 自己的 authoritative source crop/fit/physical rect，**不得**自動聚合同產品其他 door。
- `MASTER_SPLIT`：才允許依 explicit master relation/group + exact surface set 重算 master/split crop。
- `_authoritative_master()` 不可用「所有 door siblings」作隱含 group authority；master surface set 必須被 master hash/relation綁定。
- 加 golden regression：4-door cabinet 對 `DOOR_2` 做一張 single-surface 100% artwork，輸出必須是完整來源圖對該門的 canonical fit，不是第二個 quarter crop。
- 再測真正 4-door master split仍維持四個 exact quarters。

---

# Blocker 6 — Acceptance validator 還有 fail-open 條件

目前 `validate_artwork_acceptance_result()` 對 2/3/4 split 使用：

`if len(crops) != n and len(ids) != n:`

只要其中一個長度正確、另一個錯誤，因為 `and`，validator 仍可能不報錯。

Required correction：

- 此處必須 fail closed：任何 required set/count mismatch 都失敗（邏輯應等價於 OR / exact-set validation）。
- 2/3/4 scenario 除 count 外，逐片驗 surfaceId ↔ crop ↔ placement ↔ component identity exact mapping、順序、尺寸、continuity、master relation。
- `logic_ok` 不得只看 `applied` truthy；要驗 final UV result及完整 applied exact set。
- runner corruption tests至少加入：少一個 crop但 surfaceIds仍正確、少一個 surfaceId但 crops仍正確、duplicate placement、wrong final UV、preview success但缺 artworkApplied。都必須 non-zero 且不得 publish successful canonical generation。

---

# Re-Gate evidence required

完成以上 correction 後：

1. source + tests commit/push 新 **CODE_EVIDENCE_SHA**。
2. full `pytest -q` PASS。
3. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS。
4. 在 exact CODE SHA clean tree 跑 Artwork canonical runner，產生新的 `acceptanceGenerationId`，`evidenceCodeCommit=<exact CODE SHA>`、`workingTreeClean=true`。
5. 更新 `GROK_PROGRESS_REPORT.md`、`CURRENT_IMPLEMENTATION_AUDIT.md`、`REAL_E2E_ACCEPTANCE.md`、`ARTWORK_PLACEMENT_ACCEPTANCE.md/.json`。`CABINET_REAL_ACCEPTANCE.md` 只做必要的小幅 scoped truth 更新。
6. 若有 REAL Blender diagnostic artwork render：證據要含 actual artifact SHA/size/job/GPU/device、exact applied lineage、final UV parity；若沒有，維持 `realArtworkPreviewReady=false`。
7. docs/head Actions Ubuntu + Windows SUCCESS。
8. Issue #1 留短回報：CODE SHA、pytest count、CODE run、canonical generation、docs SHA/run、REAL/MOCK/PARTIAL/BLOCKED。
9. **STOP。Phase 841+ 仍不得開始，等 ChatGPT Re-Gate。**

## Definition of Done

Phase 781–840 只有在以下情況才可放行：

> Placement hash/authority 能鎖住所有真正影響 render 的 transform；Blender 對 exact FRONT face 只套一次 canonical UV/crop/rotation/mirror；REAL preview path 對缺失 applied evidence fail closed；single-surface 與 master-split production 不互相混淆；runner 對 count/lineage/final UV corruption 全部 fail closed；Mock/physical/live truth boundary維持正確。
