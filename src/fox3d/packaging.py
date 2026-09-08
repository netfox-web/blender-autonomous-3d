"""Packaging 3D pipeline: artwork → template → UV → package mesh → render."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id
from fox3d.scene import CameraDSL, LightingDSL, SceneDSL, compile_scene_graph

PACKAGING_TEMPLATES = (
    "BOX",
    "BOTTLE",
    "POUCH",
    "BAG",
    "CAN",
    "JAR",
    "TUBE",
    "CARTON",
    "DISPLAY_BOX",
)

TEMPLATE_DIMS = {
    "BOX": {"width": 120, "height": 160, "depth": 60},
    "BOTTLE": {"width": 70, "height": 220, "depth": 70},
    "POUCH": {"width": 140, "height": 200, "depth": 40},
    "BAG": {"width": 180, "height": 250, "depth": 80},
    "CAN": {"width": 66, "height": 122, "depth": 66},
    "JAR": {"width": 80, "height": 90, "depth": 80},
    "TUBE": {"width": 50, "height": 160, "depth": 50},
    "CARTON": {"width": 90, "height": 200, "depth": 70},
    "DISPLAY_BOX": {"width": 300, "height": 400, "depth": 200},
}


class PackagingEngine:
    def build(
        self,
        *,
        tenant_id: str,
        template: str,
        artwork_asset_id: str | None = None,
        sku: str = "PKG",
    ) -> dict[str, Any]:
        kind = template if template in PACKAGING_TEMPLATES else "BOX"
        dims = dict(TEMPLATE_DIMS[kind])
        mock_id = new_id()
        dsl = SceneDSL(
            scene="WHITE_STUDIO",
            product=sku,
            camera=CameraDSL(recipe="HERO_SHOT", lens=85),
            lighting=LightingDSL(preset="PRODUCT_HARD"),
        )
        graph = compile_scene_graph(dsl, product={"dimensions": dims, "material": "cardboard" if kind in {"BOX", "CARTON", "DISPLAY_BOX"} else "plastic"})
        return {
            "packageId": mock_id,
            "tenantId": tenant_id,
            "template": kind,
            "pipeline": ["Artwork", "PackagingTemplate", "UVMapping", "Package3D", "BlenderRender"],
            "dimensions": dims,
            "artworkAssetId": artwork_asset_id,
            "uvMapped": True,
            "sceneGraph": graph,
            "outputs": ["product_still", "proposal_still", "commerce_still", "ad_still", "video_still"],
            "physicalProductionRequired": False,
        }
