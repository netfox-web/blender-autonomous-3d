# PILOT_RELIABILITY_ACCEPTANCE

generatedAt: 2026-09-09T04:00:45.075890+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.

| Check | Status | Evidence |
|---|---|---|
| supplier quote business data | IMPORTED | `IMPORTED snapshots, not LIVE_PROVIDER` |
| FX business data | MANUAL | `MANUAL` |
| reliability fixture stress | FIXTURE | `wo=50 ops=652 oversell=False` |
| carrier quote | IMPORTED | `4ba97da5` |
| liveFactoryExecutionReady | BLOCKED | `False` |
| fullAutonomousFactoryReady | BLOCKED | `False` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| reliability gate | FIXTURE | `ok` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`.
