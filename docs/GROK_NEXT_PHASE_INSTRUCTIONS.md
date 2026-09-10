# Grok 修正指令：Phase 781–840 Re-Gate Round 3 — CHANGES REQUIRED / Phase 841+ HOLD

> Repo: `netfox-web/blender-autonomous-3d`  
> Reviewed main head: `e4c01702dd9dc1ce7d1c4a44f40ffa9214bfd372`  
> CODE_EVIDENCE_SHA reviewed: `dfe8eaed32192bcde202dee069f741b5884413ec`  
> Canonical generation reviewed: `01a3f28b-7eb5-4e2b-b17b-64edeff267f2`  
> CODE Actions: `34514913333` Ubuntu + Windows SUCCESS  
> docs/head Actions: `34515625153` Ubuntu + Windows SUCCESS  
> Re-Gate result: **CHANGES REQUIRED — Phase 841+ MUST NOT START.**

本輪只補 Phase 781–840 最後的 preview / production authority 缺口。**不要重寫 Scheduler、Queue、DAM、Recipe、TwinStore、CabinetSpec、WorkOrder、MaterialLot、Journal、ManufacturingRelease、PilotBatch、Backup/Restore。**

## 已接受，不要退步

- `pytest -q`：**595 passed**。
- exact CODE `dfe8eae...` Actions `34514913333`：Ubuntu + Windows **SUCCESS**。
- docs/head `e4c017...` Actions `34515625153`：Ubuntu + Windows **SUCCESS**。
- canonical generation `01a3f28b-...` runner-bound to exact CODE、`workingTreeClean=true`。
- Scheme A 已成立：**mesh FRONT UV 是 final source UV，shader mapping identity**；不再 double-apply crop/rotation。
- artwork material/UV 已限制到唯一 FRONT face；side/back 不再一起吃 artwork。
- `build_and_render()` 已顯式回傳 `artworkApplied` + `appliedPlacements`；missing artworkApplied 已 fail-closed。
- `placementHash` 已擴充綁定 uv/mirror/object/component/relation/master，`require_placement()` 會重算 UV / hash。
- `SINGLE_SURFACE` vs `MASTER_SPLIT` 已分流；單門 artwork 不再被錯切成多門 quarter crop。
- acceptance split count 的 `and` fail-open 已修成 exact/fail-closed；2/3/4 door final UV、duplicate、missing count 等 regression 已加。
- `realArtworkPreviewReady=false`、`physicalPrintValidated=false`、global/full/live readiness=false 維持正確。
- CI 仍 `FOX3D_MOCK_BLENDER=1`：只能算 **MOCK/unit/integration + FIXTURE/REAL_LOGIC**，不是 Production Ready。
- LIVE_CNC / LIVE_LASER / PLC 繼續 **BLOCKED**；Demand / Vision / AI Video 繼續 **MOCK**；print preflight 繼續 **PARTIAL**。

---

# Blocker 1 — `realArtworkPreviewReady` 還缺完整的 REAL artifact / applied-lineage gate

目前 `preview_ready_from_job()` 已要求 `usedMock=false`、`artworkApplied=true`、`realBlender=true`、status、blenderVersion、jobId，這部分接受；但它只拿四個 hash `(engineeringHash, surfaceHash, artworkHash, placementHash)` 做 applied exact-set，**沒有要求 device、實際 render artifact SHA/size，也沒有驗 object/component/face/relation/final UV**。

目前 test 甚至把一個沒有 device、沒有 artifact hash/size、applied row 只有四個 hash 的 synthetic result 判成 `True`。這還不能證明「REAL Blender 成功套用了正確那一片門、正確那個 FRONT face、正確 final UV，且確實產出可驗證圖片」。

Required correction：

- `realArtworkPreviewReady=true` 必須同時要求：
  - `usedMock is False`
  - `realBlender is True`
  - status completed/succeeded
  - non-empty `blenderVersion`
  - non-empty `jobId`
  - non-empty `device`（沿用既有 worker truth，不另造一套 GPU authority）
  - render artifact 存在，且具 **sha256 + size > 0**；若既有 worker output / DAM 已有 artifact metadata，直接重用，不重建 DAM。
  - requested placements 與 `appliedPlacements[]` **exact-set** match：至少 `placementId`、`objectName`、`componentId`、`face`、`relation`、`engineeringHash`、`surfaceHash`、`artworkHash`、`placementHash`、final UV identity/hash。
  - 不可只看四個 lineage hash；wrong object / wrong component / wrong face / wrong relation / wrong final UV 都要 false。
- `build_and_render()` 的 artwork success result 必須帶回上述 applied identity；若 worker wrapper已有 output artifact hash/size，讓 preview gate驗它。
- 若本機沒有跑 REAL artwork render，本輪仍可維持 `realArtworkPreviewReady=false`，不得假造 REAL。

Required tests：

1. 現在 synthetic `ok`（缺 device / artifact / final UV identity）必須改成 **False**。
2. missing device → False。
3. missing artifact / sha256 / size=0 → False。
4. wrong `objectName` / `componentId` / `face` / `relation` → False。
5. wrong final UV / finalUvHash → False。
6. extra / duplicate / missing applied placement → False。
7. 只有全部 evidence 完整且 exact match 才 True。

---

# Blocker 2 — `finalUvHash` 目前不是 hash，也沒有被 authoritative gate 鎖住

目前 Blender applied record 的 `finalUvHash` 是 `str(finalSampling)`。這只是字串表示，不是 deterministic hash authority；preview gate 也沒有拿 authoritative expected final UV 去 exact compare。

Required correction：

- `finalUvHash` 改成 deterministic hash，例如沿用既有 `stable_hash` / SHA-256，內容至少綁：
  - placementId
  - objectName / componentId / face
  - relation
  - uvRect
  - rotationDeg
  - mirrored
  - finalSampling
- 不可讓 Blender 自己宣稱一個 hash 就算 PASS；caller/ArtworkFactory 必須從 authoritative placement 重新推導 expected final UV / expected hash，與 worker returned applied record exact compare。
- 若不打算真正 hash，欄位就不要叫 `finalUvHash`；但本 Phase Definition of Done 仍需要一個 deterministic transform identity。

Required tests：tamper finalSampling、rotation、mirror、object/component 後，就算 copied `placementHash` 不變，也不得通過 REAL preview readiness。

---

# Blocker 3 — SINGLE_SURFACE production crop 仍直接吃 stored `rec["crop"]` projection

`produce_panel()` 的 `SINGLE_SURFACE` 現在已不再走 master split，這個方向正確；但 source pixel crop 仍直接從 stored `rec["crop"][sourceXPx/sourceYPx/sourceWPx/sourceHPx]` 取值。

雖然目前 `crop` 被 placementHash 綁住，但**若有人協調修改 stored crop + 重算 copied placementHash**，production path 沒有再從 authoritative Artwork pixel dimensions + surface/placement mm + fit/anchor 重新推導 source crop，因此 authority 還不獨立。

Required correction：

- 抽一個 deterministic canonical source-crop derivation helper，`place()` 與 `produce_panel()` 共用同一算法，不要兩套公式。
- `produce_panel(SINGLE_SURFACE)` 每次從：
  - authoritative artwork pixelWidth/pixelHeight
  - authoritative surface dimensions
  - placement x/y/w/h
  - fit / anchor / rotation（依既有支援範圍）
  重新推導 expected source crop。
- stored `rec["crop"]` 只當 projection；存在時必須 exact compare，缺失/不符 → BLOCK。
- 不可只靠「重新算 placementHash」證明 production crop正確。
- 原有 golden regression「4-door 的 DOOR_2 single-surface = full source，不是第二個 quarter」要保持 PASS。

Required negative：同時改 stored `crop` + copied `placementHash`，production 仍必須 BLOCK。

---

# Blocker 4 — MASTER_SPLIT 的 surface-set authority 仍可被 coordinated tamper 重建

`_authoritative_master()` 現在從 placement 內的 `masterSurfaceIds` 重新抓 surfaces，再重建 master。比上一版好很多，但 `masterSurfaceIds` 本身仍是 placement 的 mutable field；若 coordinated tamper 同時換一組 surface IDs、重算 masterHash、再重算 placementHash，缺少一份**獨立 master relation authority**來判斷原本是哪一組 panel。

Required correction（最小改動，不准重寫）：

- 在現有 `ArtworkFactory` 內增加 lightweight immutable master relation record，或等價的獨立 authority：`masterId/masterHash -> exact tenant/product/version/engineeringHash/surfaceIds + panel order + crop geometry`。
- `place_across_panels()` 建立一次；各 placement 只引用該 master identity。
- `_authoritative_master()` 必須從這份 authority 取 exact surface set/order，再與 placement projection比較；不能只相信 placement 自己帶的 `masterSurfaceIds`。
- master relation 仍要 tenant/product/version/engineeringHash scoped。
- coordinated tamper：換 `masterSurfaceIds + masterHash + placementHash` 必須 BLOCK。

若已有等價 immutable source 可直接重用，請重用，不新增第二套 store。

---

# Re-Gate evidence required

完成以上 correction 後：

1. source + tests commit/push 新 **CODE_EVIDENCE_SHA**。
2. full `pytest -q` PASS。
3. exact CODE SHA GitHub Actions Ubuntu + Windows SUCCESS。
4. 在 exact CODE SHA clean tree 跑 Artwork canonical runner，產生新的 `acceptanceGenerationId`，`evidenceCodeCommit=<exact CODE SHA>`、`workingTreeClean=true`。
5. 更新 `GROK_PROGRESS_REPORT.md`、`CURRENT_IMPLEMENTATION_AUDIT.md`、`REAL_E2E_ACCEPTANCE.md`、`ARTWORK_PLACEMENT_ACCEPTANCE.md/.json`。`CABINET_REAL_ACCEPTANCE.md` 沒有 truth change 就不要硬改。
6. 若有 REAL Blender diagnostic artwork render：證據必須含 actual artifact SHA/size/job/GPU/device、exact applied identity、final UV parity；若沒有，維持 `realArtworkPreviewReady=false`。
7. docs/head Actions Ubuntu + Windows SUCCESS。
8. Issue #1 留短回報：CODE SHA、pytest count、CODE run、canonical generation、docs SHA/run、REAL/MOCK/PARTIAL/BLOCKED。
9. **STOP。Phase 841+ 仍不得開始，等 ChatGPT Re-Gate。**

## Definition of Done

Phase 781–840 只有在以下情況才可放行：

> REAL artwork preview gate 能證明「指定 placement → 指定 component/FRONT face → 指定 final UV → 指定 render artifact」完整一致；final UV 有真正 deterministic identity；SINGLE_SURFACE production source crop 能從 authoritative inputs獨立重算；MASTER_SPLIT 的 exact panel group 有獨立 authority，可抵抗 coordinated tamper；Mock/physical/live truth boundary維持正確。
