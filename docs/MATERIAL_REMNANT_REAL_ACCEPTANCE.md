# MATERIAL_REMNANT_REAL_ACCEPTANCE

generatedAt: 2026-09-08T20:16:05.511188+00:00
pytest mock PASS is **not** production ready.

## Domain evidence (machine-verifiable)

| Check | Status | Evidence |
|---|---|---|
| durable persistence | REAL | `DurableRemnantStore JSON + restart tests` |
| TTL recover | REAL | `recover_expired reservedUntil` |
| tenant isolation | REAL | `cross-tenant get PermissionError` |
| stale version/lease | REAL | `reserve/consume version mismatch` |
| grain+quality block | REAL | `damaged/quarantined nestable=false` |

Human Approval Gate remains. LIVE_CNC / LIVE_LASER BLOCKED.
