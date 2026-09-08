# PHYSICAL_PRODUCT_OS_REAL_ACCEPTANCE

generatedAt: 2026-09-08T16:38:31.477029+00:00
pytest mock PASS is **not** production ready.

| Check | Status | Evidence |
|---|---|---|
| Blender | REAL | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| OptiX | REAL | `NVIDIA T1000` |
| durable remnant restart+TTL | REAL | `loaded=available recovered=1 persistence=durable-json` |
| material lot | REAL | `ea91f528-03d3-4335-af69-0d5a239d37d3` |
| KD furniture E2E core | REAL | `hash=a3830a264510 sheets=2` |
| nesting V3 benchmark | REAL | `cases=10 wins=2 losses=0` |
| KD optimized 10 | REAL | `n=10 demand=MOCK` |
| retail fixture Blender previews | REAL | `real=6/6` |
| retail planogram pipeline | REAL | `COUNTER_DISPLAY,FLOOR_DISPLAY,PDQ_DISPLAY,RISER_DISPLAY,PEGBOARD_DISPLAY,ENDCAP_MODULE` |
| packaging dieline+nest | REAL | `RSC_CARTON` |
| packaging fold preview | REAL | `status=completed mock=False` |
| acrylic Blender previews | REAL | `real=3/3` |
| WAITING_APPROVAL | REAL | `WAITING_PRODUCT_APPROVAL` |
| Vision Judge | MOCK | `no live provider` |
| Demand | MOCK | `DemandSignalProvider UNAVAILABLE` |
| AI Video | MOCK | `no ProviderAdapter` |
| OS sandbox | PARTIAL | `path guard only` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| structural certification | PARTIAL | `no ECT/BCT model` |
| electrical compliance | BLOCKED | `no electrical rules` |
| fullAutonomousFactoryReady | BLOCKED | `False` |
| three E2E paths | REAL | `KD / retail / packaging-or-acrylic` |

Human Approval Gate remains. LIVE_CNC / LIVE_LASER BLOCKED. Demand/Vision/Video MOCK.
