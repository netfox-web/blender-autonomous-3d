# PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE

generatedAt: 2026-09-08T19:13:15.155745+00:00
pytest mock PASS is **not** production ready.

## Domain evidence (machine-verifiable)

| Check | Status | Evidence |
|---|---|---|
| Blender | REAL | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| OptiX | REAL | `NVIDIA T1000` |
| publication 5-family Blender+EvidenceBundle | REAL | `real=5/5 clean=True` |
| release gate APPROVED_FOR_EXPORT | REAL | `APPROVED_FOR_EXPORT` |
| forbidden LIVE_CNC transition | REAL | `blocked` |
| forbidden LIVE_LASER transition | REAL | `blocked` |
| approval stale on hash change | REAL | `True` |
| mixed landed cost | REAL | `MIXED` |
| liveProviderReady | BLOCKED | `false` |
| packaging fit 20 cases | REAL | `20/20` |
| carton optimize | REAL | `SLEEVE` |
| safety notCertified | REAL | `True` |
| publication packages | REAL | `n=5` |
| fullAutonomousFactoryReady | BLOCKED | `False` |
| Vision | MOCK | `no live provider` |
| Demand | MOCK | `MARKET_UNVERIFIED` |
| OS sandbox | PARTIAL | `PATH_GUARD_ONLY` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |

Human Approval Gate remains. LIVE_CNC / LIVE_LASER BLOCKED.
