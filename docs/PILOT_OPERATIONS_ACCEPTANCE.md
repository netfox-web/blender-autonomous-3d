# PILOT_OPERATIONS_ACCEPTANCE

generatedAt: 2026-09-08T21:24:50.238262+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.

| Check | Status | Evidence |
|---|---|---|
| Blender | REAL | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| OptiX | REAL | `NVIDIA T1000` |
| workingTreeClean | REAL | `True` |
| four-family manual E2E | REAL | `ok=True n=4` |
| KD_FURNITURE packet checksum | REAL | `a8d13b92f876` |
| KD_FURNITURE WO COMPLETED | REAL | `COMPLETED` |
| RETAIL_FIXTURE packet checksum | REAL | `64bb353713f2` |
| RETAIL_FIXTURE WO COMPLETED | REAL | `COMPLETED` |
| PACKAGING_STRUCTURE packet checksum | REAL | `d3d74d2596b0` |
| PACKAGING_STRUCTURE WO COMPLETED | REAL | `COMPLETED` |
| ACRYLIC_SHEET packet checksum | REAL | `c1772eff69b4` |
| ACRYLIC_SHEET WO COMPLETED | REAL | `COMPLETED` |
| supplier quotes imported | REAL | `n=3 source=IMPORTED` |
| supplier compare stale | REAL | `True` |
| FX source | MANUAL | `MANUAL` |
| carrier quote | IMPORTED | `54cd3e6e` |
| pilot 4-family Blender EvidenceBundle | REAL | `real=4/4 clean=True` |
| liveFactoryExecutionReady | BLOCKED | `False` |
| fullAutonomousFactoryReady | BLOCKED | `False` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| canonical six-file reader | REAL | `ok` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`.
