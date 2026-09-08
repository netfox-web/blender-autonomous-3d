# Existing infrastructure inventory

This engine is **not** a second compute island. It registers Blender as a
Capability on the systems that already own scheduling, assets, recipes, and
tenancy.

## FoxStudio (`E:\projects\foxstudio`)

| Spec name | Existing module | How this engine reuses it |
|---|---|---|
| Compute Node Registry | `compute_targets` (alembic 0006) + `config/compute-nodes.local.json` | Heartbeat upsert of Blender/GPU/OptiX capabilities. Status already includes `online/offline/draining/degraded`. |
| Capability match | `foxstudio_job_matches_compute_route` (alembic 0040) | Jobs carry `routing_requirements.requiredCapabilities` + `minVramGb`. Scheduler is **not** rewritten. |
| Drain / preemption | `POST /api/v1/settings/compute-targets/{key}/control` action=`drain` (0041) | Blender worker honors `DRAINING`: finish current frame/tile, checkpoint, release GPU. No brutal kill. |
| Queue / Worker / Retry / Cancel / Timeout | `services/worker` 11-state machine + lease + backoff | Blender jobs are additional `jobs.kind` values. Same states, same lease recovery. |
| Recipe Registry | `production_recipes` + `/api/v1/factory/recipes` | New recipe **types** (SCENE/CAMERA/LIGHTING/…) stored as versioned recipes; no second registry. |
| Model Registry | `model_profiles` / `provider_profiles` | Video adapters stay here. Blender is a compute capability, not a model vendor. |
| Asset / DAM | `assets` table + MinIO | Digital Twins and renders are DAM objects with tenant/workspace composite keys. |
| Quality / Vision Judge | `packages/quality-gate` (`foxqc.GateResult`) | Product Vision Judge emits the same verdict shape; cinema gates stay untouched. |
| AI Gateway | `packages/adapters` (`ProviderAdapter`, H3/LTX/ComfyUI) | `BLENDER_TO_VIDEO` calls existing video adapters. No hardcoded model. |
| Tenant | `workspaces` + composite FK (FS-ADR-006) | Every 3D row is tenant-scoped. |
| Operations | compute routing audits, job usage, budget policies | Blender usage writes `job_usage` / fleet usage, not a parallel ops stack. |

Authoritative FoxStudio job states (do not fork):

`blocked → queued → leased → running → uploading → succeeded`
plus `retry_scheduled`, `cancel_requested`, `cancelled`, `failed`, `skipped`, `expired`, `waiting_approval`.

## GPU Fleet Console (`E:\projects\ai-fleet-console`)

| Spec name | Existing module | How this engine reuses it |
|---|---|---|
| GPU pool | `nodes` / `gpus` / `gpu_tasks` | Blender preview/final are extra `taskType`s. VRAM reservation already exists. |
| Scheduler | `src/lib/fleet/scheduler.ts` + `placement.ts` | Policy adapter: AI Video → prefer 5090; Blender Preview → 5080 / idle; Final → queue. **Never** pin a GPU to Blender. |
| Reservation | `vramUsedMb` optimistic reserve/release | Same reservation object for Blender tiles. |
| Retry / offline recovery | heartbeat sweep requeues running tasks (max 3) | Worker crash / node offline recovery is Fleet's, not reimplemented. |
| Tenant quota | `FleetTenant` monthly GPU-seconds / cost | Product R&D jobs consume the same quota. |

## Intentionally not reused as-is

| System | Reason |
|---|---|
| `cabinet-factory` (`E:\projects\cabinet-factory`) | 2D print mockup (PSD/mask). Parametric 3D cabinet is a new engine; print mockups can consume its artwork later. |
| AI-Office-Core | SaaS billing/tenant product, not the GPU/media control plane. Tenant IDs can be mapped, not duplicated. |

## Naming adapter

The spec names (`BLENDER_RENDER`, `ProductDigitalTwin`, `CAMAdapter`) are **domain names**.
On the wire they map to existing shapes:

| Spec | FoxStudio / Fleet |
|---|---|
| `BLENDER_RENDER` | operation `blender.render.final` + capability flag `blender.render` |
| `BLENDER_PREVIEW` | operation `blender.preview.render` |
| `ComputeNode` | `compute_targets.target_key` / `FleetNode` |
| `Recipe Registry` | `production_recipes` with `configuration.recipeType` |
| `DRAINING` | `compute_targets.status = draining` |
| `Vision Judge` | `foxqc.GateResult` + product scoring dimensions |
| `tenantId` | FoxStudio `workspace_id` (mapped, not renamed in FoxStudio) |
