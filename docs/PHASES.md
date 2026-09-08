# Phase map

| Phase | Module | Notes |
|---|---|---|
| 1 Headless worker | `blender.py`, `scripts/blender_job.py` | `blender -b --factory-startup -P` |
| 2 Node registration | `capabilities.py`, `Platform.register_node` | Heartbeat onto `compute_targets` / Fleet GPUs |
| 3 Job schema | `jobs.py` | JSON-serializable, FoxStudio states |
| 4 Scene DSL | `scene.py` | No hand-edited `.blend` |
| 5 Digital Twin | `twin.py` + DAM | GLB/FBX/OBJ/USD slots |
| 6 Product studio | `studio.py` | WHITE_STUDIO … REFLECTIVE |
| 7 Camera recipes | `studio.py` CAMERA_RECIPES | Parameterised |
| 8 Lighting recipes | `studio.py` LIGHTING_RECIPES | Versioned via Recipe Registry |
| 9 Materials | `MaterialEngine` | AI suggests → EXPERIMENTAL version only |
| 10 Packaging | `packaging.py` | BOX…DISPLAY_BOX mock pipeline |
| 11 Parametric | `parametric.py` ParametricProduct | mm SoT is not Blender |
| 12 Cabinet | `CabinetEngine` | WARDROBE…DISPLAY_CABINET |
| 13 Engineering rules | `EngineeringRuleEngine` | LLM proposes, rules validate |
| 14 BOM | `BOMEngine` | Same hash as engineering record |
| 15 Cost | `CostEngine` | Margin / suggested price |
| 16 CAM adapters | `CAMAdapter` / `CNCAdapter` / `NestingAdapter` | Manifest only, no live CNC |
| 17 Space twin | `space.py` | Mock pipeline + future adapters listed |
| 18 AI furniture designer | `parse_design_intent` + RD agent | No direct Blender from LLM |
| 19 Variants | `VariantGenerator` | 10–50, preview only |
| 20 Vision Judge | `VisionJudge` | Heuristic + gateway hook |
| 21 Product R&D | `ProductRDAgent` | Approval gate before production |
| 22 Blender → AI video | `BlenderToVideo` | Existing ProviderAdapter |
| 23 Keyframes | START/MIDDLE/END + AOVs | Blender = control, AI = creative |
| 24 Synthetic data | `SyntheticFactory` | Manifest required |
| 25 AR / Web 3D | `ARExporter` | GLB + LOD, USDZ reserved |
| 26 360 | `Product360Engine` | 36 / 72 / 120 |
| 27 Assembly anim | `AssemblyAnimator` | From component graph |
| 28 Retail | `RetailEngine` | STORE/BOOTH/… |
| 29 Recipe intelligence | `RecipeIntelligence` | Existing Recipe Registry types |
| 30 Recipe research | `BlenderRecipeResearchAgent` | Cannot clobber PRODUCTION |
| 31 GPU scheduler | `GpuPolicy` + `Scheduler` | Video→5090, preview→5080/idle |
| 32 Preemption | `DrainController` | FoxStudio `draining`, no SIGKILL |
| 33 Render cache | `RenderCache` | Deterministic key |
| 34 Lineage | `LineageLog` | Twin / recipe / GPU / Blender |
| 35 QA | `RenderQA` | AUTO_RETRY → OPERATIONS_REVIEW |
| 36 Security | `ScriptRegistry` | Allowlist + signature + sandbox |
| 37 Tenant isolation | DAM / Twin / Job getters | Cross-tenant raises |
| 38 API | `api.py` | Spec paths |
| 39 Admin UI | `admin.py` `/admin` | No Blender UI |
| 40 Acceptance | `tests/test_acceptance.py` | 30 checks |
| 71 FurnitureProductType registry | `furniture.py` | 8 types; no second SoT |
| 72–78 Cabinet modules | `CabinetSpec.modules` | partitions, open/closed, doors, toe-kick, fillers |
| 79–80 MultiCabinetAssembly | `furniture.py` | assembly engineering hash |
| 81–85 Space twin schema | `space.py` | walls origin/direction, keep-outs; photogrammetry MOCK |
| 86–89 Constraint + WallFitSolver | `space.py` | door/window/column reject; 3–10 layouts |
| 90 Space preview | `blender_job.build_space_preview` | space vs furniture lineage split |
| 91–95 Rules + hardware registry | `parametric.py` + `manufacturing.py` | sweep/extension/span placeholder; vendor-neutral HW |
| 96–100 Edge/drill/cut/gate | `manufacturing.py` | WAITING_APPROVAL; never LIVE_CNC |
| 101–107 Sheet + guillotine nest | `NestingEngine` | deterministic, grain, kerf, SVG/DXF interface |
| 108–110 Cost/quote hashes | `QuoteEngine` | stale if engineering/BOM/nesting change |
| 111–114 NL + variants | `parse_design_intent` + factory | UNKNOWN/NEEDS_INPUT; engineering-first |
| 115–116 Vision Provider | `rd.py` | MOCK heuristic; engineering veto |
| 117–119 Factory pipeline + API | `factory.py` + `/api/factory/*` | existing Admin |
| 120 Factory REAL acceptance | `docs/FURNITURE_FACTORY_REAL_ACCEPTANCE.md` | 3600mm wall E2E |
