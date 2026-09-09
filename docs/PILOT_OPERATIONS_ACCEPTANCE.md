# PILOT_OPERATIONS_ACCEPTANCE

generatedAt: 2026-09-09T00:15:59.959099+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.

| Check | Status | Evidence |
|---|---|---|
| Blender | REAL | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| OptiX | REAL | `NVIDIA T1000` |
| workingTreeClean | REAL | `True` |
| four-family manual E2E | REAL | `ok=True n=4` |
| KD_FURNITURE packet checksum | REAL | `30fbb25f2e3b` |
| KD_FURNITURE WO COMPLETED | REAL | `COMPLETED` |
| RETAIL_FIXTURE packet checksum | REAL | `8db1896e98d9` |
| RETAIL_FIXTURE WO COMPLETED | REAL | `COMPLETED` |
| PACKAGING_STRUCTURE packet checksum | REAL | `e92ac8780ffb` |
| PACKAGING_STRUCTURE WO COMPLETED | REAL | `COMPLETED` |
| ACRYLIC_SHEET packet checksum | REAL | `8052ef5f1b5b` |
| ACRYLIC_SHEET WO COMPLETED | REAL | `COMPLETED` |
| supplier quote import/compare logic | REAL | `n=3 parser=REAL` |
| supplier quote business data | IMPORTED | `IMPORTED snapshots, not LIVE_PROVIDER` |
| supplier compare stale | REAL | `True` |
| FX business data | MANUAL | `MANUAL` |
| reliability fixture stress | FIXTURE | `wo=50 ops=652 oversell=False` |
| carrier quote | IMPORTED | `e3a38272` |
| pilot 4-family Blender EvidenceBundle | REAL | `real=4/4 clean=True` |
| liveFactoryExecutionReady | BLOCKED | `False` |
| fullAutonomousFactoryReady | BLOCKED | `False` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| canonical six-file reader | REAL | `ok` |
| reliability gate | FIXTURE | `ok` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`.
