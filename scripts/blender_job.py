# SPDX-License-Identifier: UNLICENSED
"""In-Blender headless worker. Never opens a GUI.

    blender -b --factory-startup -P blender_job.py -- job.json
    blender -b --factory-startup -P blender_job.py -- --probe out.json
"""

from __future__ import annotations

import hashlib
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


def _stable_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_final_uv_hash(item: dict, mapping: dict) -> str:
    sampling = mapping.get("finalSampling") or []
    uv_rect = mapping.get("uvRect") or item.get("uvRect") or {}
    payload = {
        "placementId": item.get("placementId"),
        "objectName": item.get("objectName"),
        "componentId": item.get("componentId"),
        "face": item.get("face") or "FRONT",
        "relation": item.get("relation") or "SINGLE_SURFACE",
        "uvRect": {
            "u0": float(uv_rect.get("u0")),
            "v0": float(uv_rect.get("v0")),
            "u1": float(uv_rect.get("u1")),
            "v1": float(uv_rect.get("v1")),
        },
        "rotationDeg": float(mapping.get("rotationDeg") or 0.0) % 360.0,
        "mirrored": bool(mapping.get("mirrored")),
        "finalSampling": [[float(a), float(b)] for a, b in sampling],
    }
    return _stable_hash(payload)


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
        "acrylic_clear": (0.0, 0.05, 0.92),
        "acrylic_milky": (0.0, 0.22, 0.45),
        "acrylic_black": (0.0, 0.12, 0.0),
    }
    metallic, roughness, transmission = presets.get(name, (0.0, 0.4, 0.0))
    if principled:
        principled.inputs["Metallic"].default_value = metallic
        principled.inputs["Roughness"].default_value = roughness
        if "Base Color" in principled.inputs and name in {"white_wood", "mdf", "particle_board"}:
            principled.inputs["Base Color"].default_value = (0.86, 0.82, 0.74, 1.0)
        if "Base Color" in principled.inputs and name == "acrylic_clear":
            principled.inputs["Base Color"].default_value = (0.85, 0.92, 0.95, 1.0)
        if "Base Color" in principled.inputs and name == "acrylic_milky":
            principled.inputs["Base Color"].default_value = (0.92, 0.92, 0.9, 1.0)
        if "Base Color" in principled.inputs and name == "acrylic_black":
            principled.inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1.0)
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


def build_packaging(template: str, dims: dict) -> dict:
    width = float(dims.get("width") or 120) / 1000.0
    height = float(dims.get("height") or 160) / 1000.0
    depth = float(dims.get("depth") or 60) / 1000.0
    boxy = template.upper() in {"BOX", "CARTON", "POUCH", "BAG", "DISPLAY_BOX"}
    mat = "cardboard" if boxy else "plastic"
    size = (width, depth if boxy else width, height)
    product = _add_box("Product", size, (0, 0, height / 2), mat)
    ground = _add_plane("Ground", 2.0, (0, 0, 0))
    cam = _add_camera((width * 2.2, -depth * 3.5, height * 0.8), (0, 0, height / 2), 85)
    _three_point(height)
    return {"Product": product, "Ground": ground, "Camera": cam}


def build_packaging_fold(template: str, dims: dict) -> dict:
    """Flat net + folded box. Engineering sizes come from the job JSON."""
    width = float(dims.get("width") or dims.get("length") or 120) / 1000.0
    height = float(dims.get("height") or 80) / 1000.0
    depth = float(dims.get("depth") or 60) / 1000.0
    folded = _add_box("FoldedBox", (width, depth, height), (0.0, 0.0, height / 2), "cardboard")
    net_w = (2 * width) + (2 * depth)
    net_h = max(depth, width) + height
    flat = _add_box("FlatNet", (net_w, net_h, 0.004), (net_w * 0.6, -depth * 2.2, 0.002), "cardboard")
    ground = _add_plane("Ground", 4.0, (0, 0, 0))
    cam = _add_camera((width * 2.8, -depth * 4.2, height * 1.6), (width * 0.3, -depth * 0.6, height * 0.3), 50)
    _three_point(height)
    return {"FoldedBox": folded, "FlatNet": flat, "Ground": ground, "Camera": cam}


def build_acrylic_product(kind: str, dims: dict, finish: str = "clear") -> dict:
    width = float(dims.get("width") or 210) / 1000.0
    height = float(dims.get("height") or 297) / 1000.0
    depth = float(dims.get("depth") or 80) / 1000.0
    mat = {"clear": "acrylic_clear", "milky": "acrylic_milky", "black": "acrylic_black"}.get(finish, "acrylic_clear")
    created = {}
    if kind == "MENU_STAND":
        created["Face"] = _add_box("Face", (width, 0.005, height), (0, 0, height / 2), mat)
        created["Base"] = _add_box("Base", (width, depth, 0.005), (0, depth / 4, 0.0025), mat)
    elif kind == "SIGN_HOLDER":
        created["Face"] = _add_box("Face", (width, 0.005, height), (0, 0, height / 2), mat)
        created["LegL"] = _add_box("LegL", (0.005, depth, 0.04), (-width / 2, 0, 0.02), mat)
        created["LegR"] = _add_box("LegR", (0.005, depth, 0.04), (width / 2, 0, 0.02), mat)
    elif kind == "DISPLAY_BOX":
        created["Box"] = _add_box("Box", (width, depth, height), (0, 0, height / 2), mat)
    else:
        created["Stand"] = _add_box("Stand", (width, depth, height), (0, 0, height / 2), mat)
    created["Ground"] = _add_plane("Ground", 2.0, (0, 0, 0))
    created["Camera"] = _add_camera((width * 2.2, -depth * 3.4, height * 0.9), (0, 0, height / 2), 70)
    _three_point(height)
    return created


def _render_emission_mask(job: dict, *, width: int, height: int) -> str | None:
    import bpy

    for i, obj in enumerate(bpy.data.objects):
        if obj.type != "MESH":
            continue
        mat = bpy.data.materials.new(f"mask.{obj.name}")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        em = nodes.new("ShaderNodeEmission")
        hue = (i * 47) % 255
        em.inputs[0].default_value = ((hue % 8) / 8.0, ((hue // 8) % 8) / 8.0, 0.2, 1.0)
        em.inputs[1].default_value = 1.0
        out = nodes.new("ShaderNodeOutputMaterial")
        links.new(em.outputs[0], out.inputs[0])
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    scene = bpy.context.scene
    scene.cycles.samples = 1
    path = Path(job.get("workDir") or ".") / "mask.png"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return str(path) if path.exists() else None


def _render_keyframes(job: dict, *, width: int, height: int, samples: int) -> dict:
    import bpy

    cam = bpy.context.scene.camera
    origin = list(cam.location) if cam is not None else [1.4, -2.2, 1.0]
    work = Path(job.get("workDir") or ".")
    scene = bpy.context.scene
    scene.cycles.samples = max(4, samples // 2)
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    names = ("START_FRAME", "MIDDLE_FRAME", "END_FRAME")
    scales = (1.15, 1.0, 0.85)
    paths = {}
    for name, scale in zip(names, scales):
        if cam is not None:
            cam.location = (origin[0] * scale, origin[1] * scale, origin[2])
        out = work / f"{name}.png"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        if out.exists():
            paths[name] = str(out)
    if cam is not None:
        cam.location = origin
    return paths


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


class ArtworkApplyError(Exception):
    """Fail-closed canonical artwork apply."""


_SUPPORTED_ROT = {0.0, 90.0, 180.0, 270.0}


def door_layout_from_engineering(engineering: dict) -> list[dict]:
    """Door mesh size/pose from engineering components only — no hidden clearance."""
    parts = engineering.get("components") or []
    width = float(engineering.get("width") or 0)
    depth = float(engineering.get("depth") or 0)
    doors = []
    cursor = 0.0
    for part in parts:
        if not isinstance(part, dict) or str(part.get("role") or "") != "door":
            continue
        dw = float(part.get("width") or 0)
        dh = float(part.get("length") or 0)
        th = float(part.get("thickness") or 18)
        if dw <= 0 or dh <= 0:
            raise ArtworkApplyError("engineering door face missing dimensions")
        x_mm = -width / 2.0 + cursor + dw / 2.0
        y_mm = -depth / 2.0 - th / 2.0
        z_mm = dh / 2.0
        doors.append(
            {
                "name": str(part.get("partName") or part.get("partId") or "DOOR"),
                "partId": str(part.get("partId") or ""),
                "widthMm": dw,
                "heightMm": dh,
                "thicknessMm": th,
                "sizeMm": (dw, th, dh),
                "locMm": (x_mm, y_mm, z_mm),
                "sizeM": (dw / 1000.0, th / 1000.0, dh / 1000.0),
                "locM": (x_mm / 1000.0, y_mm / 1000.0, z_mm / 1000.0),
            }
        )
        cursor += dw
    return doors


def expected_front_normal(face: str = "FRONT") -> tuple[float, float, float]:
    key = str(face or "FRONT").upper()
    if key == "FRONT":
        return (0.0, -1.0, 0.0)
    if key == "BACK":
        return (0.0, 1.0, 0.0)
    raise ArtworkApplyError("unsupported printable face")


def select_unique_front_face(polygons: list[dict], face: str = "FRONT") -> dict:
    want = expected_front_normal(face)
    hits = []
    for poly in polygons or []:
        n = poly.get("normal") or (0, 0, 0)
        dot = float(n[0]) * want[0] + float(n[1]) * want[1] + float(n[2]) * want[2]
        if dot >= 0.9:
            hits.append(poly)
    if len(hits) != 1:
        raise ArtworkApplyError("unique FRONT face missing")
    return hits[0]


def cube_polygons_local() -> list[dict]:
    """Deterministic local-space cube faces. FRONT is -Y, matching cabinet camera."""
    return [
        {"index": 0, "normal": (0.0, -1.0, 0.0), "loop_start": 0, "loop_total": 4, "material_index": 0},
        {"index": 1, "normal": (0.0, 1.0, 0.0), "loop_start": 4, "loop_total": 4, "material_index": 0},
        {"index": 2, "normal": (1.0, 0.0, 0.0), "loop_start": 8, "loop_total": 4, "material_index": 0},
        {"index": 3, "normal": (-1.0, 0.0, 0.0), "loop_start": 12, "loop_total": 4, "material_index": 0},
        {"index": 4, "normal": (0.0, 0.0, 1.0), "loop_start": 16, "loop_total": 4, "material_index": 0},
        {"index": 5, "normal": (0.0, 0.0, -1.0), "loop_start": 20, "loop_total": 4, "material_index": 0},
    ]


def require_identity_shader(mapping: dict) -> None:
    sm = mapping.get("shaderMapping") or {}
    loc = tuple(float(x) for x in (sm.get("location") or ()))
    scale = tuple(float(x) for x in (sm.get("scale") or ()))
    rot = tuple(float(x) for x in (sm.get("rotation") or ()))
    if loc != (0.0, 0.0, 0.0) or scale != (1.0, 1.0, 1.0) or rot != (0.0, 0.0, 0.0):
        raise ArtworkApplyError("shader mapping not identity")
    if mapping.get("finalSampling") != mapping.get("corners"):
        raise ArtworkApplyError("final sampling mismatch")
    if mapping.get("mappingMode") not in {None, "MESH_UV"}:
        raise ArtworkApplyError("unsupported mapping mode")


def final_uv_sampling(mapping: dict) -> list:
    require_identity_shader(mapping)
    return list(mapping.get("finalSampling") or mapping.get("corners") or [])


def _quarter_turn_local_corners(*, rotation_deg: float = 0.0, mirrored: bool = False) -> list:
    rot = float(rotation_deg or 0.0) % 360.0
    if rot not in _SUPPORTED_ROT:
        raise ArtworkApplyError("unsupported rotation")
    pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    steps = int(rot // 90.0)
    for _ in range(steps):
        pts = [(1.0 - t, s) for s, t in pts]
    if mirrored:
        pts = [(1.0 - s, t) for s, t in pts]
    return pts


def canonical_uv_mapping(uv_rect: dict, *, rotation_deg: float = 0.0, mirrored: bool = False) -> dict:
    """Scheme A: mesh FRONT UV is the final source UV. Shader mapping stays identity."""
    if not isinstance(uv_rect, dict):
        raise ArtworkApplyError("missing uvRect")
    try:
        u0 = float(uv_rect["u0"])
        v0 = float(uv_rect["v0"])
        u1 = float(uv_rect["u1"])
        v1 = float(uv_rect["v1"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ArtworkApplyError("missing uvRect") from exc
    if not all(math.isfinite(v) for v in (u0, v0, u1, v1)):
        raise ArtworkApplyError("non-finite uvRect")
    rot = float(rotation_deg or 0.0) % 360.0
    if rot not in _SUPPORTED_ROT:
        raise ArtworkApplyError("unsupported rotation")
    local = _quarter_turn_local_corners(rotation_deg=rot, mirrored=bool(mirrored))
    corners = [(u0 + s * (u1 - u0), v0 + t * (v1 - v0)) for s, t in local]
    umin, umax = (u0, u1) if u0 <= u1 else (u1, u0)
    vmin, vmax = (v0, v1) if v0 <= v1 else (v1, v0)
    for u, v in corners:
        if u < umin - 1e-9 or u > umax + 1e-9 or v < vmin - 1e-9 or v > vmax + 1e-9:
            raise ArtworkApplyError("uv rotation escaped rect")
    return {
        "uvRect": {"u0": u0, "v0": v0, "u1": u1, "v1": v1},
        "rotationDeg": rot,
        "mirrored": bool(mirrored),
        "corners": corners,
        "finalSampling": corners,
        "mappingMode": "MESH_UV",
        "shaderMapping": {"location": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0), "rotation": (0.0, 0.0, 0.0)},
        "targetFace": "FRONT",
        "targetNormal": expected_front_normal("FRONT"),
        "otherFacesUntouched": True,
    }


def apply_canonical_artwork(created: dict, job: dict) -> list[dict]:
    """Apply canonical UV/crop/rotation to the exact engineering object. Fail closed."""
    items = job.get("artworkPlacements") or []
    if not items:
        return []
    applied: list[dict] = []
    bpy = None
    try:
        import bpy as _bpy

        bpy = _bpy
    except ImportError:
        bpy = None
    for item in items:
        if not isinstance(item, dict):
            raise ArtworkApplyError("malformed artwork placement")
        for key in ("objectName", "imagePath", "uvRect", "engineeringHash", "surfaceHash", "artworkHash", "placementHash", "artworkSha256"):
            val = item.get(key)
            if val is None or val == "":
                raise ArtworkApplyError(f"missing {key}")
        name = str(item["objectName"])
        path = Path(str(item["imagePath"]))
        if not path.exists() or not path.is_file():
            raise ArtworkApplyError("missing artwork image")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != str(item.get("artworkSha256")):
            raise ArtworkApplyError("artwork bytes digest mismatch")
        mapping = canonical_uv_mapping(
            item.get("uvRect"),
            rotation_deg=float(item.get("rotationDeg") or 0.0),
            mirrored=bool(item.get("mirrored")),
        )
        require_identity_shader(mapping)
        obj = (created or {}).get(name) if created is not None else None
        if obj is None and bpy is not None:
            obj = bpy.data.objects.get(name)
        if obj is None:
            raise ArtworkApplyError(f"missing object {name}")
        if bpy is not None and getattr(obj, "data", None) is not None:
            img = bpy.data.images.load(str(path))
            mat = bpy.data.materials.new(f"artwork.{name}")
            mat.use_nodes = True
            nt = mat.node_tree
            principled = nt.nodes.get("Principled BSDF")
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = img
            texcoord = nt.nodes.new("ShaderNodeTexCoord")
            nt.links.new(texcoord.outputs["UV"], tex.inputs["Vector"])
            if principled:
                nt.links.new(tex.outputs["Color"], principled.inputs["Base Color"])
            mesh = obj.data
            if hasattr(mesh, "materials"):
                mesh.materials.append(mat)
                art_idx = len(mesh.materials) - 1
            else:
                art_idx = 0
            polys = []
            for p in getattr(mesh, "polygons", []) or []:
                n = p.normal
                polys.append(
                    {
                        "index": p.index,
                        "normal": (float(n.x), float(n.y), float(n.z)),
                        "loop_start": p.loop_start,
                        "loop_total": p.loop_total,
                    }
                )
            hit = select_unique_front_face(polys, item.get("face") or "FRONT")
            for p in mesh.polygons:
                if p.index == hit["index"]:
                    p.material_index = art_idx
            if hasattr(mesh, "uv_layers"):
                uv_layer = mesh.uv_layers.active or mesh.uv_layers.new(name="canonical")
                corners = mapping["finalSampling"]
                for i in range(int(hit["loop_total"])):
                    uv_layer.data[hit["loop_start"] + i].uv = corners[i % 4]
            mapping["frontFaceIndex"] = hit["index"]
        elif isinstance(obj, dict) and obj.get("polygons"):
            hit = select_unique_front_face(obj["polygons"], item.get("face") or "FRONT")
            mats = list(obj.get("materials") or ["base"])
            mats.append(f"artwork.{name}")
            obj["materials"] = mats
            art_idx = len(mats) - 1
            corners = mapping["finalSampling"]
            loops = list(obj.get("uv_loops") or [])
            need = max(int(p.get("loop_start") or 0) + int(p.get("loop_total") or 0) for p in obj["polygons"])
            if len(loops) < need:
                loops.extend([(0.0, 0.0)] * (need - len(loops)))
            for p in obj["polygons"]:
                if p.get("index") == hit["index"]:
                    p["material_index"] = art_idx
                    p["uv"] = list(corners)
                    for i in range(int(p.get("loop_total") or 4)):
                        loops[int(p.get("loop_start") or 0) + i] = corners[i % 4]
            obj["uv_loops"] = loops
            mapping["frontFaceIndex"] = hit["index"]
        record = {
            "objectName": name,
            "componentId": item.get("componentId"),
            "placementId": item.get("placementId"),
            "face": item.get("face") or "FRONT",
            "relation": item.get("relation") or "SINGLE_SURFACE",
            "applied": True,
            **mapping,
            "engineeringHash": item.get("engineeringHash"),
            "surfaceHash": item.get("surfaceHash"),
            "artworkHash": item.get("artworkHash"),
            "artworkSha256": digest,
            "placementHash": item.get("placementHash"),
            "finalUvHash": compute_final_uv_hash(item, mapping),
        }
        if isinstance(obj, dict):
            obj["canonicalArtwork"] = record
        else:
            try:
                obj["canonicalArtworkApplied"] = True
                obj["engineeringHash"] = item.get("engineeringHash")
                obj["surfaceHash"] = item.get("surfaceHash")
                obj["artworkHash"] = item.get("artworkHash")
                obj["placementHash"] = item.get("placementHash")
                obj["uvRect"] = str(mapping["uvRect"])
            except Exception:
                pass
        applied.append(record)
    return applied


def build_cabinet(engineering: dict, *, explode: bool = False, origin=(0.0, 0.0, 0.0), name_prefix: str = "", setup_scene: bool = True) -> dict:
    """Millimetres in engineering JSON are the source of truth. Do not invent sizes."""
    created = add_cabinet_parts(engineering, explode=explode, origin=origin, name_prefix=name_prefix)
    if setup_scene:
        width = float(engineering.get("width") or 800) / 1000.0
        height = float(engineering.get("height") or 1800) / 1000.0
        depth = float(engineering.get("depth") or 400) / 1000.0
        _add_plane("Ground", 4.0, (0, 0, 0))
        _add_camera((origin[0] + width * 1.6, origin[1] - depth * 3.2, origin[2] + height * 0.7), (origin[0], origin[1], origin[2] + height * 0.45), 50)
        _three_point(height)
    return created


def add_cabinet_parts(engineering: dict, *, explode: bool = False, origin=(0.0, 0.0, 0.0), name_prefix: str = "") -> dict:
    created = {}
    width = float(engineering.get("width") or 800) / 1000.0
    height = float(engineering.get("height") or 1800) / 1000.0
    depth = float(engineering.get("depth") or 400) / 1000.0
    material = str(engineering.get("material") or "particle_board")
    if material == "particle_board" or material.startswith("WOOD_"):
        material = "white_wood"
    parts = engineering.get("components") or []
    counts = {"shelf": 0, "door": 0, "divider": 0, "drawer_front": 0}
    door_cursor = 0.0
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
            door_w = width_p if width_p > 0 else 0.0
            door_h = length if length > 0 else height
            if door_w <= 0 or door_h <= 0:
                raise ArtworkApplyError("engineering door face missing dimensions")
            x = -width / 2 + door_cursor + door_w / 2
            door_cursor += door_w
            size = [door_w, thick, door_h]
            loc = [x, -depth / 2 - thick / 2, door_h / 2]
            if explode:
                loc[1] -= 0.15 * counts["door"]
        elif role == "drawer_front":
            counts["drawer_front"] += 1
            size = [width - 2 * thick, thick, 0.16]
            loc = [0, -depth / 2 - thick / 2, 0.12 * counts["drawer_front"]]
        elif role == "leg":
            continue
        elif role == "top_filler":
            size = [width, depth, max(thick, 0.018)]
            loc = [0, 0, height + max(thick, 0.018) / 2]
        elif role == "side_filler":
            size = [max(thick, 0.018), depth, height]
            loc = [width / 2 + max(thick, 0.018), 0, height / 2]
        elif role in {"plinth", "toe_kick"}:
            size = [width, 0.08 if role == "toe_kick" else depth, max(thick, 0.08)]
            loc = [0, -depth / 2 + size[1] / 2 if role == "toe_kick" else 0, size[2] / 2]
        elif role == "h_partition":
            size = [width - 2 * thick, depth - 0.02, thick]
            loc = [0, 0, height * 0.5]
        else:
            size = [max(length, 0.01), max(width_p, 0.01), max(thick, 0.004)]
        if explode and role not in {"door"}:
            loc = [loc[0], loc[1] - 0.05, loc[2] + 0.02]
        loc = [loc[0] + origin[0], loc[1] + origin[1], loc[2] + origin[2]]
        obj = _add_box(name_prefix + name, size, loc, material)
        created[name_prefix + name] = obj
        if role == "door":
            handle = _add_box(name_prefix + name + ".HANDLE", (0.012, 0.02, 0.12), (loc[0], loc[1] - 0.02, loc[2]), "metal")
            created[name_prefix + name + ".HANDLE"] = handle
            hinge = _add_box(name_prefix + name + ".HINGE", (0.02, 0.02, 0.04), (loc[0] - size[0] / 2, loc[1], loc[2]), "metal")
            created[name_prefix + name + ".HINGE"] = hinge
    return created


def build_space_preview(space: dict, assembly: dict) -> dict:
    created = {}
    width = float(space.get("width") or 3600) / 1000.0
    depth = float(space.get("depth") or 3000) / 1000.0
    height = float(space.get("height") or 2600) / 1000.0
    created["Floor"] = _add_plane("Floor", max(width, depth) * 1.4, (width / 2, depth / 2, 0))
    for wall in space.get("walls") or []:
        length = float(wall.get("length") or 0) / 1000.0
        thick = float(wall.get("thickness") or 100) / 1000.0
        origin = wall.get("origin") or [0, 0, 0]
        direction = wall.get("direction") or [1, 0]
        dx, dy = float(direction[0]), float(direction[1])
        cx = float(origin[0]) / 1000.0 + dx * length / 2
        cy = float(origin[1]) / 1000.0 + dy * length / 2
        cz = height / 2
        size = (abs(dx) * length + abs(dy) * thick + 0.02, abs(dy) * length + abs(dx) * thick + 0.02, height)
        created[str(wall.get("name") or wall.get("wallId"))] = _add_box(str(wall.get("name") or "Wall"), size, (cx, cy, cz), "matte")
    for i, cab in enumerate(assembly.get("cabinets") or []):
        spec = cab.get("spec") or {}
        start = float(cab.get("startMm") or cab.get("originX") or 0) / 1000.0
        origin = (start + float(spec.get("width") or 800) / 2000.0, 0.15, 0.0)
        parts = add_cabinet_parts(spec, origin=origin, name_prefix=f"C{i}_")
        created.update(parts)
    _add_camera((width * 0.5, -depth * 0.9, height * 0.7), (width * 0.5, depth * 0.3, height * 0.3), 28)
    _three_point(height)
    return created


def _compositor_tree(scene):
    import bpy

    scene.render.use_compositing = True
    if hasattr(scene, "compositing_node_group"):
        tree = scene.compositing_node_group
        if tree is None:
            tree = bpy.data.node_groups.new("fox3d_compositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        return tree, True
    scene.use_nodes = True
    return scene.node_tree, False


def _ensure_comp_output(tree, blender5: bool):
    if blender5:
        if not any(s.name == "Image" and getattr(s, "in_out", "") in {"OUTPUT", "out"} for s in tree.interface.items_tree):
            try:
                tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            except Exception:
                pass
        node = tree.nodes.new("NodeGroupOutput")
        return node
    return tree.nodes.new("CompositorNodeComposite")


def _render_aov_pngs(job: dict, *, width: int, height: int) -> dict:
    """Cycles compositor stills for depth / normal / object-index segmentation."""
    import bpy

    scene = bpy.context.scene
    view = scene.view_layers[0]
    view.use_pass_z = True
    view.use_pass_normal = True
    view.use_pass_object_index = True
    for i, obj in enumerate(bpy.data.objects):
        if obj.type == "MESH":
            obj.pass_index = i + 1
    scene.cycles.samples = 1
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.image_settings.file_format = "PNG"
    work = Path(job.get("workDir") or ".")
    found: dict[str, str] = {}
    debug = {"outputs": [], "errors": [], "blender5": False}

    def _socket(rl, *names):
        debug["outputs"] = [getattr(s, "name", "") or getattr(s, "identifier", "") for s in rl.outputs]
        for name in names:
            try:
                return rl.outputs[name]
            except (KeyError, LookupError, TypeError):
                continue
        return None

    def _render_connected(filename: str, kind: str) -> None:
        tree, blender5 = _compositor_tree(scene)
        debug["blender5"] = blender5
        tree.nodes.clear()
        rl = tree.nodes.new("CompositorNodeRLayers")
        try:
            rl.scene = scene
        except Exception:
            pass
        out_node = _ensure_comp_output(tree, blender5)
        src = None
        src_out = None
        if kind == "depth":
            src = _socket(rl, "Depth", "Z")
            if src is None:
                debug["errors"].append("no Depth/Z socket")
                return
            mapper = None
            for ntype in ("ShaderNodeMapRange", "CompositorNodeMapRange"):
                try:
                    mapper = tree.nodes.new(ntype)
                    break
                except Exception:
                    mapper = None
            if mapper is not None:
                try:
                    mapper.inputs[1].default_value = 0.1
                    mapper.inputs[2].default_value = 8.0
                    mapper.inputs[3].default_value = 1.0
                    mapper.inputs[4].default_value = 0.0
                except Exception:
                    pass
                tree.links.new(src, mapper.inputs[0])
                src_out = mapper.outputs[0]
            else:
                src_out = src
        elif kind == "normal":
            src_out = _socket(rl, "Normal")
        else:
            src_out = _socket(rl, "Object Index", "IndexOB", "IndexMA")
        if src_out is None:
            debug["errors"].append(f"no socket for {kind}: {debug.get('outputs')}")
            return
        tree.links.new(src_out, out_node.inputs[0])
        out = work / filename
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        if out.exists() and out.stat().st_size > 32:
            found[filename] = str(out)

    for filename, kind in (("depth.png", "depth"), ("normal.png", "normal"), ("seg.png", "seg")):
        try:
            _render_connected(filename, kind)
        except Exception as exc:
            debug["errors"].append(f"{kind}: {exc}")
    if job.get("productTruthAovs"):
        if found.get("seg.png") and "product_mask.png" not in found:
            found["product_mask.png"] = found["seg.png"]
        try:
            _render_connected("alpha.png", "seg")
        except Exception as exc:
            debug["errors"].append(f"alpha: {exc}")
        if found.get("alpha.png") is None and found.get("product_mask.png"):
            found["alpha.png"] = found["product_mask.png"]
        if found.get("product_mask.png") and "artwork_mask.png" not in found:
            found["artwork_mask.png"] = found["product_mask.png"]
    _write_json(work / "aov_debug.json", debug)
    try:
        tree, blender5 = _compositor_tree(scene)
        tree.nodes.clear()
        rl = tree.nodes.new("CompositorNodeRLayers")
        out_node = _ensure_comp_output(tree, blender5)
        tree.links.new(rl.outputs["Image"], out_node.inputs[0])
    except Exception:
        pass
    return found


def _render_assembly_anim(job: dict, created: dict, *, frames: int, width: int, height: int, samples: int) -> tuple[list[str], str | None]:
    import bpy

    scene = bpy.context.scene
    scene.cycles.samples = max(4, samples // 2)
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    work = Path(job.get("workDir") or ".")
    frame_dir = work / "assembly"
    frame_dir.mkdir(parents=True, exist_ok=True)
    originals = {name: tuple(obj.location) for name, obj in created.items() if getattr(obj, "location", None) is not None}
    paths = []
    for i in range(frames):
        t = i / max(frames - 1, 1)
        for name, obj in created.items():
            if name not in originals:
                continue
            ox, oy, oz = originals[name]
            obj.location = (ox, oy - 0.25 * t, oz + 0.08 * t)
        out = frame_dir / f"{i:03d}.png"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        paths.append(str(out))
    for name, obj in created.items():
        if name in originals:
            obj.location = originals[name]
    mp4 = _mux_png_sequence(frame_dir, work / "assembly.mp4")
    return paths, mp4


def _find_beauty_png(work: Path) -> Path | None:
    candidates = [work / "beauty.png", work / "beauty.png.png"]
    candidates.extend(sorted(work.glob("beauty*.png")))
    for path in candidates:
        try:
            if path.exists() and path.stat().st_size >= 32:
                return path
        except OSError:
            continue
    return None


def _render_still(job: dict, *, width: int, height: int, samples: int) -> tuple[Path, float]:
    import bpy

    scene = bpy.context.scene
    scene.cycles.samples = samples
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.use_file_extension = True
    work = Path(job.get("workDir") or ".").resolve()
    work.mkdir(parents=True, exist_ok=True)
    png_path = work / "beauty.png"
    scene.render.filepath = str(png_path)
    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    elapsed = time.perf_counter() - started
    found = _find_beauty_png(work) or png_path
    return found, elapsed


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
    applied_placements: list[dict] = []
    if mode in {"REAL_SMOKE_TEST", "SMOKE"} or job.get("smokeTest"):
        created = build_smoke_scene()
    elif mode in {"PACKAGING_FOLD"} or job.get("foldPreview"):
        created = build_packaging_fold(str(job.get("packagingTemplate") or "BOX"), job.get("dimensions") or {})
    elif job.get("packagingTemplate"):
        created = build_packaging(str(job.get("packagingTemplate")), job.get("dimensions") or {})
    elif mode in {"ACRYLIC_PRODUCT", "ACRYLIC_PREVIEW"} or job.get("acrylic"):
        acr = job.get("acrylic") or {}
        created = build_acrylic_product(str(acr.get("kind") or "MENU_STAND"), acr.get("dimensions") or {}, str(acr.get("finish") or "clear"))
    elif mode in {"SPACE_PREVIEW"} or job.get("space"):
        created = build_space_preview(job.get("space") or {}, job.get("assembly") or {})
    elif job.get("engineering"):
        created = build_cabinet(job["engineering"], explode=bool(job.get("explode")))
        try:
            applied_placements = apply_canonical_artwork(created, job)
        except ArtworkApplyError as exc:
            return {"status": "failed", "error": str(exc), "realBlender": True, "artworkApplied": False, "appliedPlacements": []}
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
    want_aov = bool(job.get("aovs") or mode in {"SYNTHETIC_DATA"} or job.get("passes"))
    png_path, elapsed = _render_still(job, width=width, height=height, samples=samples)
    found = png_path if png_path.exists() and png_path.stat().st_size >= 32 else _find_beauty_png(Path(job.get("workDir") or ".").resolve())
    if found is None or not found.exists() or found.stat().st_size < 32:
        return {"status": "failed", "error": "no PNG written", "realBlender": True, "workDir": job.get("workDir")}
    png_path = found
    outputs = {"beauty.png": str(png_path)}
    produced = ["RGB"]
    if want_aov:
        try:
            aovs = _render_aov_pngs(job, width=width, height=height)
            outputs.update(aovs)
        except Exception:
            aovs = {}
        if outputs.get("depth.png"):
            produced.append("depth")
        if outputs.get("normal.png"):
            produced.append("normal")
        if outputs.get("seg.png"):
            produced.append("segmentation")
    if job.get("assemblyAnimation") or mode == "ASSEMBLY_ANIM":
        frames_n = int((job.get("animation") or {}).get("frames") or 8)
        asm_paths, asm_mp4 = _render_assembly_anim(job, created, frames=frames_n, width=width, height=height, samples=samples)
        outputs["assemblyFrames"] = asm_paths
        if asm_mp4:
            outputs["assembly.mp4"] = asm_mp4
            produced.append("assembly_mp4")
        else:
            produced.append("assembly_png_sequence")
    if mode in {"BLENDER_TO_VIDEO", "SYNTHETIC_DATA"} or job.get("passes"):
        keys = _render_keyframes(job, width=width, height=max(256, height // 2), samples=max(8, samples // 2))
        outputs.update(keys)
        mask = _render_emission_mask(job, width=width, height=height)
        if mask:
            outputs["mask.png"] = mask
            produced.append("mask")
        produced.extend([k for k in keys if keys[k]])
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
        "outputs": outputs,
        "objects": sorted(created.keys()),
        "producedPasses": produced,
    }
    if job.get("artworkPlacements"):
        want_n = len(job.get("artworkPlacements") or [])
        ok_applied = (
            len(applied_placements) == want_n
            and want_n > 0
            and all(isinstance(row, dict) and row.get("applied") is True for row in applied_placements)
        )
        if not ok_applied:
            return {
                "status": "failed",
                "error": "artwork not applied",
                "realBlender": True,
                "artworkApplied": False,
                "appliedPlacements": applied_placements,
            }
        result["artworkApplied"] = True
        result["appliedPlacements"] = applied_placements
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
