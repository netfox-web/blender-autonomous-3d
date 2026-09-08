# 下一輪建議

本輪（Phase 71–120 Autonomous Furniture Factory）之後建議依序：

1. **Vision Judge 接真 Provider** — 介面已在；無 live adapter 時保持 MOCK。不得覆蓋 Engineering Rule Engine veto。
2. **AI Video live ProviderAdapter** — 禁止硬編碼 H3/LTX。
3. **空間掃描硬體** — photogrammetry / Gaussian / SLAM 仍 MOCK；有設備再接 adapter。
4. **商品化 / AR / Web3D** — 沿用 TwinStore + ARExporter，不另建平台。
5. **包裝與展示架 Parametric Product** — 同一 millimetre SoT。
6. **零售 / 展場 Scene** — 既有 RetailEngine 加深，不重寫 queue。
7. **Render farm / 多 GPU** — 既有 Scheduler/GpuPolicy ports。
8. **CNC** — 僅 ManufacturingManifest + Human Approval Gate；`liveMachineControl=false`。
