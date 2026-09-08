"""Packaging 3D pipeline: artwork → template → UV → package mesh → render."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
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


BOX_FAMILIES = ("RSC_CARTON", "MAILER_BOX", "SLEEVE", "TRAY", "PDQ_TRAY")

PAPERBOARD_SHEETS: dict[str, dict[str, Any]] = {
    "KRAFT_RSC_B": {
        "sku": "KRAFT_RSC_B",
        "length": 1200,
        "width": 800,
        "caliperMm": 3.0,
        "grain": "length",
        "flute": "B",
        "costPerSheet": 28.0,
        "source": "CONFIG",
        "ect": None,
        "bct": None,
        "structuralCertification": False,
    },
    "FOLDING_CARTON": {
        "sku": "FOLDING_CARTON",
        "length": 700,
        "width": 1000,
        "caliperMm": 0.5,
        "grain": "length",
        "flute": None,
        "costPerSheet": 12.0,
        "source": "CONFIG",
        "ect": None,
        "bct": None,
        "structuralCertification": False,
    },
}

BOX_DEFAULT_CLEARANCE = {"length": 6.0, "width": 6.0, "height": 8.0}


def product_fit(product_dims: dict[str, float], *, family: str, clearance: dict[str, float] | None = None) -> dict[str, Any]:
    c = {**BOX_DEFAULT_CLEARANCE, **(clearance or {})}
    inner = {
        "length": float(product_dims.get("length") or product_dims.get("width") or 100) + c["length"] * 2,
        "width": float(product_dims.get("width") or product_dims.get("depth") or 80) + c["width"] * 2,
        "height": float(product_dims.get("height") or 60) + c["height"] * 2,
    }
    # RSC flaps add ~ caliper * 2 to outer.
    outer = dict(inner)
    if family == "RSC_CARTON":
        outer = {"length": inner["length"] + 6, "width": inner["width"] + 6, "height": inner["height"] + 6}
    elif family == "SLEEVE":
        outer = {"length": inner["length"] + 2, "width": inner["width"] + 2, "height": inner["height"]}
    elif family in {"TRAY", "PDQ_TRAY"}:
        outer = {"length": inner["length"] + 4, "width": inner["width"] + 4, "height": inner["height"] * 0.55}
    return {"family": family, "inner": inner, "outer": outer, "clearance": c, "artworkNotStructural": True}


def dieline_primitives(family: str, inner: dict[str, float], *, caliper: float = 3.0) -> dict[str, Any]:
    L, W, H = inner["length"], inner["width"], inner["height"]
    # Simple net: panels with cut/crease semantics. Not a die-maker CAD.
    panels = []
    if family == "RSC_CARTON":
        panels = [
            {"id": "bottom", "w": L, "h": W, "kind": "panel"},
            {"id": "front", "w": L, "h": H, "kind": "panel"},
            {"id": "top", "w": L, "h": W, "kind": "panel"},
            {"id": "back", "w": L, "h": H, "kind": "panel"},
            {"id": "left", "w": W, "h": H, "kind": "panel"},
            {"id": "right", "w": W, "h": H, "kind": "panel"},
        ]
    elif family == "MAILER_BOX":
        panels = [
            {"id": "base", "w": L, "h": W, "kind": "panel"},
            {"id": "lid", "w": L, "h": W, "kind": "panel"},
            {"id": "front", "w": L, "h": H, "kind": "panel"},
            {"id": "side_l", "w": W, "h": H, "kind": "panel"},
            {"id": "side_r", "w": W, "h": H, "kind": "panel"},
        ]
    elif family == "SLEEVE":
        panels = [
            {"id": "wrap", "w": 2 * (L + W), "h": H, "kind": "panel"},
        ]
    elif family == "TRAY":
        panels = [
            {"id": "base", "w": L, "h": W, "kind": "panel"},
            {"id": "front", "w": L, "h": H, "kind": "panel"},
            {"id": "back", "w": L, "h": H, "kind": "panel"},
            {"id": "left", "w": W, "h": H, "kind": "panel"},
            {"id": "right", "w": W, "h": H, "kind": "panel"},
        ]
    else:  # PDQ_TRAY
        panels = [
            {"id": "base", "w": L, "h": W, "kind": "panel"},
            {"id": "back", "w": L, "h": H * 1.4, "kind": "panel"},
            {"id": "left", "w": W, "h": H, "kind": "panel"},
            {"id": "right", "w": W, "h": H, "kind": "panel"},
            {"id": "front_lip", "w": L, "h": H * 0.4, "kind": "panel"},
        ]
    cuts = [{"panelId": p["id"], "op": "cut", "w": p["w"], "h": p["h"]} for p in panels]
    creases = [{"from": a["id"], "to": b["id"], "op": "crease"} for a, b in zip(panels, panels[1:])]
    perfs = [{"panelId": panels[0]["id"], "op": "perforation", "note": "tear-strip placeholder"}] if family in {"MAILER_BOX", "PDQ_TRAY"} else []
    glue = [{"panelId": panels[-1]["id"], "op": "glue", "widthMm": 15}]
    svg_parts = []
    x = 0.0
    for p in panels:
        svg_parts.append(f'<rect x="{x}" y="0" width="{p["w"]}" height="{p["h"]}" fill="none" stroke="#111"/>')
        x += p["w"] + 8
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x} {max(p["h"] for p in panels)+10}">{"".join(svg_parts)}</svg>'
    man = {
        "family": family,
        "caliperMm": caliper,
        "panels": panels,
        "cut": cuts,
        "crease": creases,
        "perforation": perfs,
        "glue": glue,
        "svg": svg,
        "dxfFriendly": {"units": "mm", "layers": ["CUT", "CREASE", "PERF", "GLUE"], "liveMachineControl": False},
        "liveMachineControl": False,
    }
    man["manifestHash"] = stable_hash({k: man[k] for k in man if k != "svg"})
    return man


def bleed_safe_metadata(zones: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "zones": zones
        or [
            {"name": "main", "bleedMm": 3, "safeMm": 5, "kind": "printable"},
        ],
        "trapping": "PARTIAL",
        "colorManagement": "PARTIAL",
        "preflight": "PARTIAL",
        "note": "Artwork geometry only — print preflight not connected.",
    }


class PackagingEngineeringDefinition:
    """Structural packaging wrapper. Same Product Digital Twin, extra engineering."""

    def __init__(self, twin: dict[str, Any] | None = None) -> None:
        self.twin = twin or {}
        self.family: str | None = None
        self.fit: dict[str, Any] | None = None
        self.dieline: dict[str, Any] | None = None

    def define(self, *, family: str, product_dims: dict[str, float], sheet: dict[str, Any] | None = None) -> dict[str, Any]:
        if family not in BOX_FAMILIES:
            raise ValueError(family)
        self.family = family
        self.fit = product_fit(product_dims, family=family)
        sheet = sheet or PAPERBOARD_SHEETS["KRAFT_RSC_B"]
        self.dieline = dieline_primitives(family, self.fit["inner"], caliper=float(sheet.get("caliperMm") or 3))
        rec = {
            "family": family,
            "twinId": self.twin.get("twinId"),
            "fit": self.fit,
            "dieline": {k: v for k, v in self.dieline.items() if k != "svg"},
            "dielineSvgBytes": len(self.dieline.get("svg") or ""),
            "sheet": sheet,
            "bleed": bleed_safe_metadata(),
            "strength": {
                "ect": sheet.get("ect"),
                "bct": sheet.get("bct"),
                "label": "PARTIAL",
                "structuralCertification": False,
                "note": "No REAL ECT/BCT model.",
            },
            "compatibleTwin": True,
        }
        rec["engineeringHash"] = stable_hash({k: rec[k] for k in rec if k != "engineeringHash"})
        return rec


class StructuralPackagingFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.items: dict[str, dict[str, Any]] = {}

    def build(
        self,
        *,
        tenant_id: str,
        family: str,
        product_dims: dict[str, float],
        sheet_sku: str = "KRAFT_RSC_B",
        render: bool = False,
        twin: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from fox3d.nesting_v3 import NestingV3

        sheet = dict(PAPERBOARD_SHEETS[sheet_sku])
        eng = PackagingEngineeringDefinition(twin)
        defined = eng.define(family=family, product_dims=product_dims, sheet=sheet)
        panels = []
        for p in eng.dieline["panels"]:
            panels.append(
                {
                    "partId": p["id"],
                    "partName": p["id"].upper(),
                    "length": p["w"],
                    "width": p["h"],
                    "thickness": sheet.get("caliperMm") or 3,
                    "quantity": 1,
                    "grain": "length" if sheet.get("grain") == "length" else "none",
                    "hardware": False,
                }
            )
        product_id = new_id()
        bom = {"productId": product_id, "lines": panels, "revision": 1, "bomHash": stable_hash(panels)}
        nest_sheet = {
            "sku": sheet["sku"],
            "length": sheet["length"],
            "width": sheet["width"],
            "thickness": sheet.get("caliperMm") or 3,
            "grain": sheet.get("grain") or "none",
        }
        nest = NestingV3().nest(bom, material="PAPERBOARD", thickness=float(nest_sheet["thickness"]), sheet=nest_sheet, seed=f"pkg:{family}")
        rec = {
            "packageId": product_id,
            "tenantId": tenant_id,
            "family": family,
            "engineering": defined,
            "bom": bom,
            "nesting": {k: nest[k] for k in nest if k != "svg"},
            "waste": {
                "partUsedArea": nest.get("partUsedArea"),
                "trueScrapArea": nest.get("trueScrapArea"),
                "reusableRemnantArea": nest.get("reusableRemnantArea"),
                "trimLossArea": nest.get("trimLossArea"),
            },
            "approvalState": "WAITING_APPROVAL",
            "liveMachineControl": False,
            "preview": None,
            "sameTwinStore": True,
            "sameScheduler": True,
        }
        rec["lineage"] = {
            "engineeringHash": defined["engineeringHash"],
            "bomHash": bom["bomHash"],
            "nestingHash": nest.get("nestingHash"),
            "twinId": (twin or {}).get("twinId"),
        }
        if render:
            job = self.platform.submit_job(
                {
                    "tenantId": tenant_id,
                    "jobType": "BLENDER_PREVIEW",
                    "mode": "PACKAGING_FOLD",
                    "packagingTemplate": "BOX" if family != "SLEEVE" else "CARTON",
                    "foldPreview": True,
                    "dimensions": defined["fit"]["outer"],
                    "render": {"width": 256, "height": 256, "engine": "CYCLES", "device": "OPTIX", "samples": 8},
                    "timeoutSeconds": 180,
                }
            )
            preview = self.platform.execute_job(job)
            if preview.get("status") in {"queued", "retry_scheduled"}:
                preview = self.platform.execute_job(preview)
            rec["preview"] = preview
            rec["previewLabel"] = "REAL" if rec["preview"].get("realBlender") and not rec["preview"].get("usedMock") else "MOCK"
        self.items[product_id] = rec
        return rec

    def bundle_with_retail(
        self,
        *,
        tenant_id: str,
        product: dict[str, Any],
        fixture_family: str = "PDQ_DISPLAY",
        box_family: str = "PDQ_TRAY",
    ) -> dict[str, Any]:
        dims = product.get("dimensions") or {}
        pkg = self.build(tenant_id=tenant_id, family=box_family, product_dims=dims, twin=product)
        fixture = self.platform.retail_fixtures.build(tenant_id=tenant_id, family=fixture_family, product=product, render=False)
        return {
            "twinId": product.get("twinId"),
            "sku": product.get("sku"),
            "consumerPackage": {"packageId": pkg["packageId"], "family": box_family, "lineage": pkg["lineage"]},
            "pdq": {"packageId": pkg["packageId"], "family": box_family},
            "retailFixture": {"fixtureId": fixture["fixtureId"], "family": fixture_family, "lineage": fixture["lineage"]},
            "sameTwin": True,
        }
