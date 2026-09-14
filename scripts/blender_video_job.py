"""One headless Blender worker for deterministic, product-locked sequences."""
from __future__ import annotations
import hashlib
import json
import sys
import time
import types
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
# Blender only needs the stdlib-only recipe module, not the host Platform package
# initializer (which imports FastAPI/Pydantic unavailable in bundled Blender).
package = types.ModuleType("fox3d"); package.__path__ = [str(ROOT/"src"/"fox3d")]
sys.modules["fox3d"] = package
import blender_job as core
from fox3d.video_recipe import ROLES, validate_recipe, frame_plan, articulation_gate


def matrix(value):
    return [[float(x) for x in row] for row in value]


def observe_objects(created):
    return {name: {"matrix": matrix(obj.matrix_world), "dimensions": list(obj.dimensions),
                   "vertices": len(obj.data.vertices), "polygons": len(obj.data.polygons)}
            for name, obj in created.items()}


def run(job):
    import bpy
    from mathutils import Vector
    a = job["videoAuthority"]; recipe = a["recipe"]
    validate_recipe(recipe, job["engineering"]); articulation_gate(recipe, a)
    work = Path(job["workDir"]).resolve(); work.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    device, probe = core._configure_cycles_device("OPTIX", require_optix=True)
    if device != "OPTIX":
        raise ValueError("BLOCKED_NO_OPTIX")
    created = core.build_cabinet(job["engineering"])
    product_root = bpy.data.objects.new("VideoProductRoot", None)
    bpy.context.scene.collection.objects.link(product_root)
    for obj in created.values(): obj.parent = product_root
    applied = core.apply_canonical_artwork(created, job)
    scene = bpy.context.scene
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.pass_index = 1 if obj.name in created else 0
            obj.hide_render = obj.name not in created
    room=recipe["scene"]["room"]
    if room:
        core._add_plane("VideoRoomFloor",room["width"],(0,0,-.01))
        core._add_box("VideoRoomBack",(room["width"]*2,.04,room["height"]*2),(0,room["depth"]/2,room["height"]/2),"white_wood")
    for obj in list(bpy.data.objects):
        if obj.type=="LIGHT":bpy.data.objects.remove(obj,do_unlink=True)
    for light in recipe["scene"]["lights"]:
        core._add_light(light["name"],light["type"].lower(),light["location"],light["energy"],light["color"])
    scene.world = bpy.data.worlds.new("VideoWorld"); scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*recipe["scene"]["worldColor"], 1.)
    bg.inputs[1].default_value = recipe["scene"]["worldStrength"]
    scene.render.engine = "CYCLES"; scene.cycles.samples = recipe["scene"]["samples"]
    scene.cycles.use_denoising = False
    scene.render.resolution_x = recipe["width"]; scene.render.resolution_y = recipe["height"]
    scene.render.resolution_percentage = 100; scene.render.film_transparent = recipe["scene"]["transparent"]
    scene.render.fps = recipe["fps"]; scene.frame_start = 1; scene.frame_end = recipe["frameCount"]
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = recipe["scene"]["exposure"]; scene.view_settings.gamma = 1.
    scene.render.image_settings.color_mode = "RGB"
    camera = scene.camera; cfg = recipe["camera"]
    camera.data.lens = cfg["focalLengthMm"]; camera.data.sensor_width = cfg["sensorWidthMm"]
    camera.data.sensor_fit = "HORIZONTAL"; camera.data.clip_start = cfg["clipStart"]; camera.data.clip_end = cfg["clipEnd"]
    view = scene.view_layers[0]
    view.use_pass_z = True; view.use_pass_normal = True
    view.use_pass_object_index = True; view.use_pass_material_index = True
    started = time.monotonic(); frames = []; outputs = {}
    for index in range(recipe["frameCount"]):
        if core._cancelled(job):
            raise ValueError("cancelled")
        plan = frame_plan(recipe, index); scene.frame_set(index+1)
        camera.location = plan["location"]
        camera.rotation_euler = (Vector(cfg["lookAt"])-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.keyframe_insert(data_path="location", frame=index+1)
        camera.keyframe_insert(data_path="rotation_euler", frame=index+1)
        bpy.context.view_layer.update()
        records = {}
        for role, ext in ROLES.items():
            scene.view_settings.view_transform = "Standard" if role=="beauty" else "Raw"
            scene.view_settings.exposure = recipe["scene"]["exposure"] if role=="beauty" else 0.
            tree, v5 = core._compositor_tree(scene); tree.nodes.clear()
            layer = tree.nodes.new("CompositorNodeRLayers"); out = core._ensure_comp_output(tree, v5)
            names = {"beauty": ("Image",), "depth": ("Depth","Z"), "normal": ("Normal",),
                     "alpha": ("Alpha",), "product_mask": ("IndexOB","Object Index"),
                     "artwork_mask": ("IndexMA","Material Index")}[role]
            source = next((layer.outputs.get(name) for name in names if layer.outputs.get(name) is not None), None)
            if source is None: raise ValueError("missing_AOV_socket:"+role)
            if role.endswith("mask"):
                math_node = tree.nodes.new("ShaderNodeMath" if v5 else "CompositorNodeMath")
                math_node.operation = "COMPARE"
                math_node.inputs[1].default_value = 1 if role == "product_mask" else 8
                math_node.inputs[2].default_value = .1
                tree.links.new(source, math_node.inputs[0]); source = math_node.outputs[0]
            tree.links.new(source, out.inputs[0])
            scene.render.image_settings.file_format = "OPEN_EXR" if ext == "exr" else "PNG"
            scene.render.image_settings.color_depth = "32" if ext == "exr" else "8"
            dest = work / "frames" / f"{index:04d}" / f"{role}.{ext}"
            dest.parent.mkdir(parents=True, exist_ok=True); scene.render.filepath = str(dest)
            bpy.ops.render.render(write_still=True)
            data = dest.read_bytes()
            records[role] = {"path": str(dest), "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            if ext=="exr":
                img=bpy.data.images.load(str(dest),check_existing=False)
                values=list(img.pixels[:]);channels=img.channels
                rgb=[v for i,v in enumerate(values) if i%channels<3]
                if not rgb or not all(math.isfinite(v) for v in rgb):raise ValueError("nonfinite_EXR_pixels")
                records[role]["decoded"]={"width":img.size[0],"height":img.size[1],"channels":channels,"min":min(rgb),"max":max(rgb),"finite":True}
                bpy.data.images.remove(img)
            outputs[f"f{index:04d}_{role}.{ext}"] = str(dest)
        f = recipe["width"]*camera.data.lens/camera.data.sensor_width
        frames.append({"index": index, "timestamp": (scene.frame_current-1)/scene.render.fps,
                       "cameraMatrix": matrix(camera.matrix_world),
                       "intrinsics": [[f, 0., recipe["width"]/2], [0., f, recipe["height"]/2], [0., 0., 1.]],
                       "productMatrix": matrix(product_root.matrix_world),
                       "objects": observe_objects(created), "articulation": [], "artifacts": records,
                       "identity": a["identity"], "blenderJobId": job["jobId"]})
        core._write_progress(job, (index+1)/recipe["frameCount"], f"video_frame_{index}")
    scene.view_settings.view_transform = recipe["scene"]["colorManagement"]
    scene.view_settings.exposure = recipe["scene"]["exposure"]
    # Reopen the actual saved scene and observe sampled keyed frames again.
    bpy.ops.wm.save_as_mainfile(filepath=str(work / "sequence.blend"))
    bpy.ops.wm.open_mainfile(filepath=str(work / "sequence.blend"))
    scene = bpy.context.scene; reopened = []
    for i in sorted({0, recipe["frameCount"]//2, recipe["frameCount"]-1}):
        scene.frame_set(i+1); bpy.context.view_layer.update()
        reopened.append({"index": i, "cameraMatrix": matrix(scene.camera.matrix_world),
                         "objects": observe_objects({n:bpy.data.objects[n] for n in created})})
    observation = {"identity": a["identity"], "authorityHash": a["authorityHash"],
                   "blenderJobId": job["jobId"], "frames": frames, "appliedPlacements": applied,
                   "reopened": reopened, "blenderVersion": bpy.app.version_string,
                   "device": device, "cyclesDevices": probe.get("devices"), "usedMock": False, "realBlender": True}
    observation["cameraObserved"]={"lens":scene.camera.data.lens,"sensor":scene.camera.data.sensor_width,"sensorFit":scene.camera.data.sensor_fit,
                                  "clipStart":scene.camera.data.clip_start,"clipEnd":scene.camera.data.clip_end,
                                  "width":scene.render.resolution_x,"height":scene.render.resolution_y,"fps":scene.render.fps}
    observation["sceneObserved"]={"engine":scene.render.engine,"samples":scene.cycles.samples,"transparent":scene.render.film_transparent,
                                 "worldColor":list(scene.world.node_tree.nodes['Background'].inputs[0].default_value[:3]),
                                 "worldStrength":scene.world.node_tree.nodes['Background'].inputs[1].default_value,
                                 "colorManagement":scene.view_settings.view_transform,
                                 "exposure":scene.view_settings.exposure,
                                 "lights":[{"name":v['name'],"type":bpy.data.objects[v['name']].data.type,"location":list(bpy.data.objects[v['name']].location),
                                            "energy":bpy.data.objects[v['name']].data.energy,"color":list(bpy.data.objects[v['name']].data.color)} for v in recipe['scene']['lights']]}
    core._write_json(work / "worker_sequence.json", observation)
    outputs["worker_sequence.json"] = str(work / "worker_sequence.json")
    outputs["sequence.blend"] = str(work / "sequence.blend")
    outputs["beauty.png"] = frames[0]["artifacts"]["beauty"]["path"]
    return {"status": "succeeded", "outputs": outputs, "realBlender": True, "usedMock": False,
            "realCycles": True, "realOptix": True, "engine": "CYCLES", "device": device,
            "samples": recipe["scene"]["samples"], "blenderVersion": bpy.app.version_string,
            "renderTimeSec": time.monotonic()-started, "artworkApplied": bool(applied), "appliedPlacements": applied}


if __name__ == "__main__":
    job = json.loads(Path(sys.argv[sys.argv.index("--")+1]).read_text(encoding="utf-8"))
    try:
        result = run(job)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        result = {"status": "failed", "error": str(exc), "realBlender": True, "usedMock": False}
    core._write_json(Path(job["workDir"])/"result.json", result)
    sys.exit(0 if result["status"] == "succeeded" else 1)
