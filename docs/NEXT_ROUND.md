# 下一輪建議

本輪（Phase 41–70 gap-fill）之後建議依序：

1. **Vision Judge 接真模型** — 現況是啟發式 MOCK。接既有 FoxStudio quality-gate / AI Gateway，不得讓 vision 覆蓋 Engineering Rule Engine。
2. **Blender AOV 一次出圖** — depth / normal / segmentation 目前 synthetic 只保證 RGB + mask；用 Cycles compositor File Output 一次出齊。
3. **AI Video live adapter** — H3 / LTX 走 FoxStudio `ProviderAdapter`，仍禁止硬編碼單一模型。現況 generative 段是 MOCK。
4. **Assembly animation MP4** — exploded PNG 已 REAL；組裝動畫影片尚未穩定產出。
5. **5090 節點上線** — discovery 已按 nvidia-smi 命名；有 5090 會自動 `local-5090`。
6. **Admin ops 表單** — `feature/admin-console` worktree 的互動表單尚未合入 main（見 `docs/dispatch/README.md`）。
7. **CNC** — 僅 ManufacturingManifest；真機必須 Human Approval Gate。
