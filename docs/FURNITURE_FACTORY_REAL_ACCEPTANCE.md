# FURNITURE_FACTORY_REAL_ACCEPTANCE

generatedAt: 2026-09-08T14:03:24.684937+00:00
productionReady: **True**

3600mm wall → multi-cabinet layout → BOM → nesting → cost/quote → Blender space preview → WAITING_APPROVAL.
pytest mock PASS is **not** production ready.

| Check | Status | Evidence |
|---|---|---|
| Blender | REAL | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| GPU | REAL | `NVIDIA T1000 4.0GB` |
| OptiX | REAL | `[{'name': 'NVIDIA T1000', 'type': 'CUDA', 'kind': 'OPTIX'}, {'name': 'Intel Core i9-14900K', 'type': 'CPU', 'kind': 'OPTIX'}, {'name': 'NVIDIA T1000', 'type': 'OPTIX', 'kind': 'OPT` |
| 3600mm wall space twin | REAL | `wall=3600.0 hash=ec90e1948647` |
| layout candidates | REAL | `legal=3 total=3` |
| multi-cabinet assembly | REAL | `count=2 hash=75770223e3e1` |
| BOM | REAL | `lines=28 bomHash=d0debb681708` |
| nesting | REAL | `sheets=6 util=0.641 wasteM2=6.4123` |
| quote | REAL | `price=12177.13 quoteHash=22cc4f85d158` |
| Blender space preview | REAL | `status=completed error=None job=a48dc1d8-2e5a-4490-a12e-a8627dc1d6a2` |
| WAITING_APPROVAL gate | REAL | `{"status": "WAITING_APPROVAL", "liveMachineControl": false, "HUMAN_APPROVAL_REQUIRED": true, "autoLiveCnc": false}` |
| liveMachineControl | BLOCKED | `liveMachineControl=false` |
| door/window/column rejection | REAL | `["COLUMN_COLLISION", "DOOR_COLLISION", "WINDOW_COLLISION"]` |
| Cycles AOV depth/normal/seg | REAL | `files=['beauty.png', 'beautyHash', 'beautySize', 'depth.png', 'normal.png', 'seg.png', 'assemblyFrames', 'assembly.mp4']` |
| assembly animation MP4 | REAL | `mp4=a89523f7-21fb-434e-9bb0-e567b2705b06 ffmpeg=True` |
| Vision Judge | MOCK | `heuristic provider; no live vision adapter registered` |
| AI Video | MOCK | `no FoxStudio ProviderAdapter registered` |
| OS sandbox | PARTIAL | `path guard + SANDBOX ONLY, not OS jail` |

- runId: `e0c0bb39-4bf9-4f6a-8b18-286602ba50b4`
- spaceHash: `ec90e1948647fd8d72deddafde703fdb12787c913fc14c8653974d1f3660316c`
- assemblyHash: `75770223e3e14690e5eab6d21cb77a4ab8be249020b1d6b546dd6c4efb4fe6b4`
- quoteHash: `22cc4f85d1589fdb049dbe2ff23f7e76953a0a55fe1b42b5629f3b3eaf6617cf`
- gate: `WAITING_APPROVAL` liveMachineControl=`False`

LIVE_CNC remains **BLOCKED**. Human Approval Gate is mandatory.
