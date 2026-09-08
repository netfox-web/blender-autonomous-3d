# Architecture

## Principle

Blender is a **schedulable Capability**, not a dedicated machine and not a GUI
workflow. Formal pipelines never open the Blender UI.

```
Product / NL request
        │
        ▼
 DesignIntent JSON  ──LLM proposes only──► Engineering Rule Engine validates
        │
        ▼
 ParametricProduct (SoT for mm) ──► BOM / Cost / CAM adapter (no live CNC)
        │
        ▼
 Scene JSON DSL + Camera/Lighting/Material Recipes (Recipe Registry)
        │
        ▼
 FoxStudio Queue  ──capability match──► any eligible GPU worker
        │
        ▼
 blender -b --factory-startup -P blender_job.py -- job.json
        │
        ▼
 DAM (twin, PNG/WEBP/EXR, GLB, 360, synthetic, lineage)
        │
        ▼
 Optional: existing AI Video adapters (H3/LTX/…) using Blender keyframes
```

## What this repo owns

- Blender headless worker + Scene DSL
- Product Digital Twin
- Parametric product / cabinet / engineering rules / BOM / cost / CAM **interfaces**
- Product R&D agent (variants, mock vision judge, approval gate)
- Recipe types and research loop (never overwrites PRODUCTION)
- Security allowlist for Blender Python
- HTTP API + admin console that talks to the system, not to Blender UI

## What this repo must not own

- A second scheduler, queue, worker framework, DAM, or recipe registry
- Hard-pinning RTX 5090 to Blender
- LLM-authored manufacturing dimensions
- Live CNC control
- Auto-promotion of AI designs into production without an approval gate

## GPU policy (adapter over Fleet + FoxStudio)

1. AI Video (existing H3/LTX/i2v operations) keeps **high priority** and prefers 5090.
2. Blender Preview prefers 5080 or any **idle** discrete GPU.
3. Blender Final Render is placed by the existing queue (priority, VRAM, fairness).
4. A node may advertise both video and Blender capabilities and switch per job.
5. Preemption uses existing `drain`: finish current frame/tile → checkpoint →
   release reservation → scheduler dispatches the high-priority job.

## Source of truth

| Concern | SoT |
|---|---|
| Millimetres, parts, hardware | `ParametricProduct` engineering data |
| Look / camera / light | Versioned recipes in the existing Recipe Registry |
| Bytes on disk | DAM / MinIO |
| Who ran what, on which GPU, with which Blender | Asset lineage |
| Who may run a `.py` inside Blender | Script Registry allowlist + signature |
