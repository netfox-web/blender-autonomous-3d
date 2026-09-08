# CABINET_REAL_ACCEPTANCE

Proof that one Engineering JSON drives geometry, BOM, material, cost, and Blender preview.
No second millimetre source of truth in Blender.

| Step | Status | Evidence |
|---|---|---|
| STORAGE_CABINET 800×1800×400×18, shelves=4, doors=2 | REAL | `CabinetEngine.create`; left/right/top/bottom/back/shelves/doors from params |
| Engineering hash SoT | REAL | `CabinetSpec.engineering_hash()`; Blender job receives `engineering` JSON only |
| BOM dimensions == part dimensions | REAL | BOM lines copy `length/width/thickness` from the same components |
| partType on BOM | REAL | `partType` = role (left/right/top/…) |
| Resize 800 → 1200 | REAL | TOP length 800.0 → 1200.0; BOM hash changes; preview re-rendered Cycles OptiX |
| Materials WOOD_WHITE…WOOD_CREAM | REAL | catalog in `CABINET_MATERIALS`; NL 白色木紋 → `WOOD_WHITE` |
| Cost from BOM | REAL | Material/Hardware/Processing/Assembly/Packaging/Shipping; no payment |
| Door / drawer / hinge / handle | REAL | components + hardware list; collision via Rule Engine |
| Exploded preview | REAL | `render_parametric(..., explode=True)` completed on Blender 5.2.1 OptiX |
| NL 120×180×40cm 雙門 4層 | REAL | DesignIntent mm 1200/1800/400; `llmMayNotSetMillimetresDirectly=true` |
| CNC live control | BLOCKED | CAD/CAM/CNC/Nesting adapters emit ManufacturingManifest only; `liveMachineControl=false` |
| Vision Judge live model | MOCK | heuristic scores; Rule Engine remains engineering authority |

Same product version path:

`params → Engineering Definition → geometry components → BOM → cost → blender_job.build_cabinet(engineering)`
