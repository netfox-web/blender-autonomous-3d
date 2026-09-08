"""360, AR/GLB, synthetic data, assembly animation, Blender→AI video, retail scenes."""

from __future__ import annotations

import math
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.pngutil import write_glb_stub, write_solid_png
from fox3d.scene import CameraDSL, LightingDSL, SceneDSL, compile_scene_graph


class Product360Engine:
    def render_plan(self, twin: dict[str, Any], *, frames: int = 36) -> dict[str, Any]:
        if frames not in {36, 72, 120}:
            frames = 36
        angles = [round(i * (360 / frames), 4) for i in range(frames)]
        return {
            "jobType": "PRODUCT_360",
            "frames": frames,
            "angles": angles,
            "outputs": ["angle_png", "mp4_turntable", "web_360_viewer"],
            "twinId": twin.get("twinId"),
        }

    def render_mock(self, work_dir, twin: dict[str, Any], *, frames: int = 36) -> dict[str, Any]:
        plan = self.render_plan(twin, frames=frames)
        paths = []
        for i, angle in enumerate(plan["angles"]):
            path = work_dir / f"360_{i:03d}_{angle:.1f}.png"
            write_solid_png(path, stable_hash({"a": angle, "t": twin.get("twinId")}), 48, 48)
            paths.append(str(path))
        mp4 = work_dir / "turntable.mp4"
        mp4.write_bytes(b"ftypisom")  # container hint; muxer is a later adapter
        return {**plan, "images": paths, "mp4": str(mp4), "viewerAssets": paths}


class ARExporter:
    def export(self, twin: dict[str, Any], dest) -> dict[str, Any]:
        glb = dest / f"{twin.get('sku') or 'product'}.glb"
        write_glb_stub(glb, twin.get("sku") or "product")
        lods = []
        for level, scale in (("lod0", 1.0), ("lod1", 0.5), ("lod2", 0.25)):
            p = dest / f"{level}.glb"
            write_glb_stub(p, f"{twin.get('sku')}-{level}")
            lods.append({"level": level, "scale": scale, "path": str(p), "textureCompression": "basis-uastc", "meshOptimization": True})
        return {
            "glb": str(glb),
            "gltf": str(glb).replace(".glb", ".gltf"),
            "usdzReserved": True,
            "lod": lods,
            "webFriendly": True,
        }


class SyntheticFactory:
    def manifest(self, *, job_id: str, twin_id: str, frames: int = 8) -> dict[str, Any]:
        return {
            "jobType": "SYNTHETIC_DATA",
            "jobId": job_id,
            "twinId": twin_id,
            "frames": frames,
            "passes": ["RGB", "mask", "depth", "normal", "segmentation", "bounding_box", "camera_pose", "object_id"],
            "uses": ["YOLO", "product_recognition", "warehouse", "defect_detection", "computer_vision"],
        }

    def generate(self, work_dir, *, job_id: str, twin_id: str, frames: int = 8) -> dict[str, Any]:
        man = self.manifest(job_id=job_id, twin_id=twin_id, frames=frames)
        files: dict[str, list[str]] = {p: [] for p in ["rgb", "mask", "depth", "normal", "seg"]}
        boxes = []
        poses = []
        for i in range(frames):
            seed = stable_hash({"j": job_id, "i": i})
            for name, folder in files.items():
                path = work_dir / name / f"{i:04d}.png"
                write_solid_png(path, seed + name, 32, 32)
                folder.append(str(path))
            boxes.append({"frame": i, "objectId": twin_id, "xyxy": [8, 8, 24, 24]})
            poses.append({"frame": i, "location": [0, -1.2, 0.3], "rotation": [math.radians(i * 10), 0, 0]})
        man["files"] = files
        man["boundingBoxes"] = boxes
        man["cameraPoses"] = poses
        import json

        (work_dir / "manifest.json").write_text(json.dumps(man, default=str), encoding="utf-8")
        return man


class AssemblyAnimator:
    def from_component_graph(self, spec: dict[str, Any]) -> dict[str, Any]:
        parts = spec.get("components") or []
        explode = []
        for i, part in enumerate(parts):
            explode.append(
                {
                    "part": part.get("partName"),
                    "offset": [0.0, 0.05 * (i + 1), 0.02 * (i % 3)],
                    "order": i,
                }
            )
        return {
            "explode": explode,
            "assembly": list(reversed(explode)),
            "disassembly": explode,
            "uses": ["product_explain", "furniture_install", "retail_display", "after_sales"],
        }


class BlenderToVideo:
    def keyframes(self, scene_graph: dict[str, Any], *, frames: tuple[str, ...] = ("START_FRAME", "MIDDLE_FRAME", "END_FRAME")) -> dict[str, Any]:
        cam = next((o for o in scene_graph.get("objects") or [] if o.get("type") == "camera"), {})
        product = next((o for o in scene_graph.get("objects") or [] if o.get("name") == "Product"), {})
        refs = []
        for name in frames:
            refs.append(
                {
                    "name": name,
                    "camera": cam,
                    "productLocation": product.get("location"),
                    "passes": ["beauty", "depth", "normal", "mask", "composition", "lighting"],
                }
            )
        return {
            "principle": {"blender": "deterministic control", "aiVideo": "generative creativity"},
            "blenderOwns": ["product_position", "camera", "composition", "lighting", "depth", "normal", "mask"],
            "aiVideoOwns": ["people", "background", "fx", "motion", "creative_transformation"],
            "keyframes": refs,
        }

    def run(self, *, twin: dict[str, Any], scene_graph: dict[str, Any], gateway, adapter: str | None = None) -> dict[str, Any]:
        keys = self.keyframes(scene_graph)
        video = gateway.generate_video(
            adapter=adapter,
            request={"twinId": twin.get("twinId"), "keyframes": keys["keyframes"], "duration": 6},
        )
        return {
            "pipeline": ["digital_twin", "blender_keyframes", "reference_frames", "ai_video", "qa"],
            "keyframes": keys,
            "video": video,
            "adapterHardcoded": False,
        }


RETAIL_SCENES = ("STORE", "BOOTH", "POPUP", "DISPLAY_WALL", "SHELF", "DISPLAY_RACK")


class RetailEngine:
    def propose(self, *, space: dict[str, Any], brand: str, skus: list[str], count: int) -> dict[str, Any]:
        kind = space.get("kind") if space.get("kind") in RETAIL_SCENES else "STORE"
        width = float(space.get("width") or 6000)
        depth = float(space.get("depth") or 4000)
        dsl = SceneDSL(
            scene="LIFESTYLE",
            camera=CameraDSL(recipe="STATIC", lens=24),
            lighting=LightingDSL(preset="DAYLIGHT"),
        )
        graph = compile_scene_graph(dsl, product={"dimensions": {"width": width, "height": 2800, "depth": depth}})
        return {
            "kind": kind,
            "brand": brand,
            "skus": skus,
            "displayCount": count,
            "space": {"width": width, "depth": depth},
            "sceneGraph": graph,
            "proposal": True,
        }
