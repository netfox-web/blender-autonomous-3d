# SPDX-License-Identifier: UNLICENSED
"""In-Blender headless worker. Never opens a GUI.

    blender -b --factory-startup -P blender_job.py -- job.json
    blender -b --factory-startup -P blender_job.py -- --probe out.json
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path


def _argv_after_double_dash(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return argv[1:]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")


def _load_job(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_progress(job: dict, progress: float, stage: str) -> None:
    progress_file = job.get("progressFile")
    if not progress_file:
        return
    _write_json(Path(progress_file), {"progress": progress, "stage": stage})


def _cancelled(job: dict) -> bool:
    cancel_file = job.get("cancelFile")
    return bool(cancel_file and Path(cancel_file).exists())


def _blender_version() -> str:
    import bpy

    return bpy.app.version_string


def list_cycles_devices() -> dict:
    import bpy

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons.get("cycles")
    devices: list[dict] = []
    optix = False
    cuda = False
    if prefs:
        cprefs = prefs.preferences
        for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                cprefs.compute_device_type = kind
                cprefs.get_devices()
            except Exception:
                continue
            for dev in getattr(cprefs, "devices", []):
                dtype = str(getattr(dev, "type", "") or "")
                name = str(getattr(dev, "name", "") or "")
                devices.append({"name": name, "type": dtype, "kind": kind})
                if dtype == "OPTIX" or kind == "OPTIX":
                    optix = True
                if dtype == "CUDA" or kind == "CUDA":
                    cuda = True
    return {
        "blenderVersion": _blender_version(),
        "cycles": True,
        "optix": optix,
        "cuda": cuda,
        "devices": devices,
    }


def _configure_cycles_device(device: str, *, require_optix: bool) -> tuple[str, dict]:
    import bpy

    probe = list_cycles_devices()
    if require_optix and not probe["optix"]:
        return "BLOCKED_NO_OPTIX", probe
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons.get("cycles")
    chosen = "CPU"
    order = ["OPTIX", "CUDA"] if device.upper() in {"OPTIX", "GPU"} else ["CUDA", "OPTIX"]
    if device.upper() == "CPU":
        scene.cycles.device = "CPU"
        return "CPU", probe
    if prefs:
        cprefs = prefs.preferences
        for kind in order:
            if require_optix and kind != "OPTIX":
                continue
            try:
                cprefs.compute_device_type = kind
                cprefs.get_devices()
            except Exception:
                continue
            enabled = False
            for dev in getattr(cprefs, "devices", []):
                dtype = str(getattr(dev, "type", "") or "")
                if dtype in {kind, "CUDA", "OPTIX"} and dtype != "CPU":
                    dev.use = True
                    enabled = True
            if enabled:
                scene.cycles.device = "GPU"
                chosen = kind
                break
    if chosen == "CPU":
        scene.cycles.device = "CPU"
        if require_optix:
            return "BLOCKED_NO_OPTIX", probe
    return chosen, probe


def _look_at(obj, target) -> None:
    from mathutils import Vector

    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _bsdf(name: str, mat_name: str):
    import bpy

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    presets = {
        "plastic": (0.0, 0.35, 0.0),
        "glass": (0.0, 0.02, 1.0),
        "metal": (1.0, 0.2, 0.0),
        "wood": (0.0, 0.45, 0.0),
        "particle_board": (0.0, 0.55, 0.0),
        "mdf": (0.0, 0.5, 0.0),
        "white_wood": (0.0, 0.4, 0.0),
        "cardboard": (0.0, 0.75, 0.0),
        "matte": (0.0, 0.85, 0.0),
        "glossy": (0.15, 0.08, 0.0),
    }
    metallic, roughness, transmission = presets.get(name, (0.0, 0.4, 0.0))
    if principled:
        principled.inputs["Metallic"].default_value = metallic
        principled.inputs["Roughness"].default_value = roughness
        if "Base Color" in principled.inputs and name in {"white_wood", "mdf", "particle_board"}:
            principled.inputs["Base Color"].default_value = (0.86, 0.82, 0.74, 1.0)
        if "Transmission" in principled.inputs:
            principled.inputs["Transmission"].default_value = transmission
        elif "Transmission Weight" in principled.inputs:
            principled.inputs["Transmission Weight"].default_value = transmission
    return mat


def _add_box(name: str, size, location, material: str | None = None):
    import bpy

    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material:
        obj.data.materials.append(_bsdf(material, material + "." + name))
    return obj


def _add_plane(name: str, size: float, location):
    import bpy

    bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(_bsdf("matte", "ground"))
    return obj


def _add_camera(location, look_at, lens: float = 50):
    import bpy

    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.active_object
    cam.name = "Camera"
    cam.data.lens = lens
    _look_at(cam, look_at)
    bpy.context.scene.camera = cam
    return cam


def _add_light(name: str, kind: str, location, energy: float, color):
    import bpy

    light_type = "AREA" if kind == "area" else "SPOT" if kind == "spot" else "SUN"
    light = bpy.data.lights.new(name, light_type)
    light.energy = energy
    light.color = color[:3]
    obj = bpy.data.objects.new(name, light)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def _three_point(height: float = 1.0) -> None:
    z = max(height * 1.6, 0.8)
    _add_light("Light.Key", "area", (1.4, -1.6, z), 400, (1, 0.98, 0.94))
    _add_light("Light.Fill", "area", (-1.6, -0.9, z * 0.8), 120, (0.9, 0.95, 1))
    _add_light("Light.Rim", "spot", (0.1, 1.8, z), 220, (1, 1, 1))


def build_smoke_scene() -> dict:
    cube = _add_box("Cube", (0.5, 0.5, 0.5), (0, 0, 0.25), "plastic")
    plane = _add_plane("Plane", 4.0, (0, 0, 0))
    cam = _add_camera((1.6, -2.4, 1.2), (0, 0, 0.25), 50)
    _three_point(0.5)
    return {"Cube": cube, "Plane": plane, "Camera": cam}


def build_from_graph(graph: dict) -> dict:
    import bpy

    created = {}
    world = graph.get("world") or {}
    bg = world.get("background") or [0.92, 0.92, 0.94]
    world_data = bpy.data.worlds.new("StudioWorld")
    world_data.use_nodes = True
    bg_node = world_data.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs[0].default_value = (float(bg[0]), float(bg[1]), float(bg[2]), 1.0)
    bpy.context.scene.world = world_data
    for spec in graph.get("objects") or []:
        name = spec.get("name") or "Obj"
        kind = spec.get("type")
        loc = spec.get("location") or [0, 0, 0]
        size = spec.get("size") or [1, 1, 1]
        if kind == "plane":
            created[name] = _add_plane(name, max(size[0], size[1]), loc)
        elif kind in {"box", "cube"}:
            created[name] = _add_box(name, size, loc, spec.get("material"))
        elif kind == "camera":
            created[name] = _add_camera(loc, spec.get("look_at") or [0, 0, 0], float(spec.get("lens") or 50))
        elif kind in {"area", "spot", "sun"}:
            created[name] = _add_light(name, kind, loc, float(spec.get("energy") or 100), spec.get("color") or [1, 1, 1])
    return created


def import_glb(path: str):
    import bpy

    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=path)
    imported = [bpy.data.objects[k] for k in bpy.data.objects.keys() if k not in before]
    if not imported:
        return None
    # Center on origin, sit on z=0.
    xs, ys, zs = [], [], []
    for obj in imported:
        for corner in obj.bound_box:
            world = obj.matrix_world @ __import__("mathutils").Vector(corner)
            xs.append(world.x)
            ys.append(world.y)
            zs.append(world.z)
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    zmin = min(zs)
    for obj in imported:
        obj.location.x -= cx
        obj.location.y -= cy
        obj.location.z -= zmin
    root = imported[0]
    root.name = "Product"
    return root


def build_cabinet(engineering: dict, *, explode: bool = False) -> dict:
    """Millimetres in engineering JSON are the source of truth. Do not invent sizes."""
    created = {}
    width = float(engineering.get("width") or 800) / 1000.0
    height = float(engineering.get("height") or 1800) / 1000.0
    depth = float(engineering.get("depth") or 400) / 1000.0
    material = str(engineering.get("material") or "particle_board")
    if material == "particle_board":
        material = "white_wood"
    parts = engineering.get("components") or []
    # Simple carcass layout from roles; dimensions come from each part, not from Blender.
    counts = {"shelf": 0, "door": 0, "divider": 0, "drawer_front": 0}
    for part in parts:
        role = str(part.get("role") or "")
        name = str(part.get("partName") or role or "PART")
        length = float(part.get("length") or 0) / 1000.0
        width_p = float(part.get("width") or 0) / 1000.0
        thick = float(part.get("thickness") or 18) / 1000.0
        loc = [0.0, 0.0, height / 2]
        size = [thick, width_p, length]
        if role == "left":
            size = [thick, depth, height]
            loc = [-width / 2 + thick / 2, 0, height / 2]
        elif role == "right":
            size = [thick, depth, height]
            loc = [width / 2 - thick / 2, 0, height / 2]
        elif role == "top":
            size = [width, depth, thick]
            loc = [0, 0, height - thick / 2]
        elif role == "bottom":
            size = [width - 2 * thick, depth, thick]
            loc = [0, 0, thick / 2]
        elif role == "back":
            size = [width - 2 * thick, thick, height - 2 * thick]
            loc = [0, depth / 2 - thick / 2, height / 2]
        elif role == "shelf":
            counts["shelf"] += 1
            n = max(1, sum(1 for p in parts if p.get("role") == "shelf"))
            z = height * counts["shelf"] / (n + 1)
            size = [width - 2 * thick, depth - 0.02, thick]
            loc = [0, -0.005, z]
        elif role == "divider":
            counts["divider"] += 1
            size = [thick, depth - 0.02, height - 2 * thick]
            loc = [-width / 4 if counts["divider"] == 1 else width / 4, 0, height / 2]
        elif role == "door":
            counts["door"] += 1
            door_w = width / max(1, sum(1 for p in parts if p.get("role") == "door"))
            x = -width / 2 + door_w * (counts["door"] - 0.5)
            size = [door_w - 0.002, thick, height]
            loc = [x, -depth / 2 - thick / 2, height / 2]
            if explode:
                loc[1] -= 0.15 * counts["door"]
        elif role == "drawer_front":
            counts["drawer_front"] += 1
            size = [width - 2 * thick, thick, 0.16]
            loc = [0, -depth / 2 - thick / 2, 0.12 * counts["drawer_front"]]
        elif role == "leg":
            continue
        else:
            size = [max(length, 0.01), max(width_p, 0.01), max(thick, 0.004)]
        obj = _add_box(name, size, loc, material)
        created[name] = obj
        if role == "door":
            handle = _add_box(name + ".HANDLE", (0.012, 0.02, 0.12), (loc[0], loc[1] - 0.02, loc[2]), "metal")
            created[name + ".HANDLE"] = handle
            hinge = _add_box(name + ".HINGE", (0.02, 0.02, 0.04), (loc[0] - size[0] / 2, loc[1], loc[2]), "metal")
            created[name + ".HINGE"] = hinge
    _add_plane("Ground", 4.0, (0, 0, 0))
    _add_camera((width * 1.6, -depth * 3.2, height * 0.7), (0, 0, height * 0.45), 50)
    _three_point(height)
    return created


def _render_still(job: dict, *, width: int, height: int, samples: int) -> tuple[Path, float]:
    import bpy

    scene = bpy.context.scene
    scene.cycles.samples = samples
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    work = Path(job.get("workDir") or ".")
    work.mkdir(parents=True, exist_ok=True)
    png_path = work / "beauty.png"
    scene.render.filepath = str(png_path)
    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    elapsed = time.perf_counter() - started
    return png_path, elapsed


def _mux_png_sequence(frame_dir: Path, mp4: Path) -> str | None:
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        "12",
        "-i",
        str(frame_dir / "%03d.png"),
        "-pix_fmt",
        "yuv420p",
        str(mp4),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return str(mp4) if mp4.exists() and mp4.stat().st_size > 32 else None


def _render_turntable(job: dict, *, frames: int, width: int, height: int, samples: int) -> tuple[list[str], str | None, float]:
    import bpy

    scene = bpy.context.scene
    scene.cycles.samples = samples
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.image_settings.file_format = "PNG"
    work = Path(job.get("workDir") or ".")
    frame_dir = work / "360"
    frame_dir.mkdir(parents=True, exist_ok=True)
    product = bpy.data.objects.get("Product") or bpy.data.objects.get("Cube")
    if product is None:
        for obj in bpy.data.objects:
            if obj.type == "MESH" and obj.name not in {"Plane", "Ground"}:
                product = obj
                break
    paths: list[str] = []
    started = time.perf_counter()
    scene.frame_start = 1
    scene.frame_end = frames
    for i in range(frames):
        if _cancelled(job):
            break
        if product is not None:
            product.rotation_euler = (0, 0, math.radians(i * (360.0 / frames)))
        scene.frame_set(i + 1)
        out = frame_dir / f"{i:03d}.png"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        paths.append(str(out))
        img = bpy.data.images.get("Render Result")
        if img is not None:
            try:
                img.buffers_free()
            except Exception:
                pass
        _write_progress(job, 0.5 + 0.5 * (i + 1) / frames, f"frame_{i+1}")
    elapsed = time.perf_counter() - started
    mp4_path = _mux_png_sequence(frame_dir, work / "turntable.mp4")
    return paths, mp4_path, elapsed


def build_and_render(job: dict) -> dict:
    import bpy

    if _cancelled(job):
        return {"status": "cancelled", "realBlender": True}
    _write_progress(job, 0.05, "clear")
    bpy.ops.wm.read_factory_settings(use_empty=True)

    render_cfg = job.get("render") or {}
    require_optix = str(render_cfg.get("device") or "OPTIX").upper() == "OPTIX"
    used_device, probe = _configure_cycles_device(str(render_cfg.get("device") or "OPTIX"), require_optix=require_optix)
    if used_device == "BLOCKED_NO_OPTIX":
        return {
            "status": "blocked",
            "error": "BLOCKED_NO_OPTIX",
            "realBlender": True,
            "realCycles": True,
            "realOptix": False,
            "cyclesDevices": probe.get("devices") or [],
            "blenderVersion": probe.get("blenderVersion"),
        }

    mode = str(job.get("mode") or job.get("jobType") or "")
    created = {}
    if mode in {"REAL_SMOKE_TEST", "SMOKE"} or job.get("smokeTest"):
        created = build_smoke_scene()
    elif job.get("engineering"):
        created = build_cabinet(job["engineering"], explode=bool(job.get("explode")))
    else:
        graph = job.get("sceneGraph") or {}
        created = build_from_graph(graph)
        glb = job.get("glbPath")
        if glb and Path(glb).exists():
            product = import_glb(glb)
            if product is not None:
                created["Product"] = product
            if not any(o.get("type") in {"area", "spot"} for o in graph.get("objects") or []):
                _three_point(0.4)
            if bpy.context.scene.camera is None:
                _add_camera((1.4, -2.2, 1.0), (0, 0, 0.2), 85)
            if "Ground" not in bpy.data.objects and "Plane" not in bpy.data.objects:
                _add_plane("Ground", 4.0, (0, 0, 0))

    if _cancelled(job):
        return {"status": "cancelled", "realBlender": True}
    _write_progress(job, 0.35, "built")

    width = int(render_cfg.get("width") or 512)
    height = int(render_cfg.get("height") or 512)
    samples = int(render_cfg.get("samples") or 32)
    anim = (job.get("animation") or {})
    frames = int(anim.get("frames") or 0)
    if str(anim.get("type") or "").upper() == "TURNTABLE" or mode in {"PRODUCT_360", "PRODUCT_360_E2E"}:
        frames = int(anim.get("frames") or 36)
        paths, mp4, elapsed = _render_turntable(job, frames=frames, width=width, height=height, samples=samples)
        result = {
            "status": "succeeded",
            "engine": "CYCLES",
            "device": used_device,
            "samples": samples,
            "renderTimeSec": round(elapsed, 3),
            "blenderVersion": _blender_version(),
            "realBlender": True,
            "realCycles": True,
            "realOptix": used_device == "OPTIX",
            "outputs": {"frames": paths, "beauty.png": paths[0] if paths else None, "turntable.mp4": mp4},
            "frameCount": len(paths),
        }
        _write_json(Path(job.get("workDir") or ".") / "result.json", result)
        return result

    _write_progress(job, 0.5, "render")
    png_path, elapsed = _render_still(job, width=width, height=height, samples=samples)
    if not png_path.exists() or png_path.stat().st_size < 32:
        return {"status": "failed", "error": "no PNG written", "realBlender": True}
    result = {
        "status": "succeeded",
        "engine": "CYCLES",
        "device": used_device,
        "samples": samples,
        "renderTimeSec": round(elapsed, 3),
        "blenderVersion": _blender_version(),
        "realBlender": True,
        "realCycles": True,
        "realOptix": used_device == "OPTIX",
        "realRenderOutput": True,
        "outputs": {"beauty.png": str(png_path)},
        "objects": sorted(created.keys()),
    }
    _write_progress(job, 1.0, "done")
    return result


def main() -> int:
    args = _argv_after_double_dash(sys.argv)
    if not args:
        print("usage: blender -b --factory-startup -P blender_job.py -- job.json|--probe out.json", file=sys.stderr)
        return 2
    if args[0] == "--probe":
        out = Path(args[1] if len(args) > 1 else "probe.json")
        payload = list_cycles_devices()
        _write_json(out, payload)
        print(json.dumps(payload))
        return 0
    job = _load_job(args[0])
    result = build_and_render(job)
    out = Path(job.get("workDir") or ".") / "result.json"
    _write_json(out, result)
    if result.get("status") == "blocked":
        return 3
    return 0 if result.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
