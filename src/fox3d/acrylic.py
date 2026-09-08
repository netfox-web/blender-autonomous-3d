"""Acrylic / sheet product extension. Reuses Nesting Strategy Registry + Waste V2."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.manufacturing import NestingEngine
from fox3d.nesting_v3 import NestingV3

ACRYLIC_SHEETS: dict[str, dict[str, Any]] = {
    "ACR_CLEAR_5": {
        "sku": "ACR_CLEAR_5",
        "length": 1220,
        "width": 2440,
        "thickness": 5,
        "grain": "none",
        "finish": "clear",
        "costPerSheet": 1600.0,
        "costPerM2": 540.0,
        "source": "CONFIG",
        "engineering": "acrylic",
    },
    "ACR_MILKY_5": {
        "sku": "ACR_MILKY_5",
        "length": 1220,
        "width": 2440,
        "thickness": 5,
        "grain": "none",
        "finish": "milky",
        "costPerSheet": 1500.0,
        "costPerM2": 510.0,
        "source": "CONFIG",
        "engineering": "acrylic",
    },
    "ACR_BLACK_5": {
        "sku": "ACR_BLACK_5",
        "length": 1220,
        "width": 2440,
        "thickness": 5,
        "grain": "none",
        "finish": "black",
        "costPerSheet": 1450.0,
        "costPerM2": 490.0,
        "source": "CONFIG",
        "engineering": "acrylic",
    },
}

ACRYLIC_FAMILIES = ("MENU_STAND", "SIGN_HOLDER", "RISER_STAND", "DISPLAY_BOX", "PRODUCT_STAND")

ACRYLIC_DEFAULTS: dict[str, dict[str, float]] = {
    "MENU_STAND": {"width": 210, "height": 297, "depth": 80},
    "SIGN_HOLDER": {"width": 100, "height": 150, "depth": 60},
    "RISER_STAND": {"width": 200, "height": 80, "depth": 200},
    "DISPLAY_BOX": {"width": 200, "height": 200, "depth": 200},
    "PRODUCT_STAND": {"width": 150, "height": 250, "depth": 150},
}


def acrylic_parts(kind: str, *, width: float, height: float, depth: float, thickness: float) -> list[dict[str, Any]]:
    t = thickness
    if kind == "MENU_STAND":
        return [
            {"partId": "face", "partName": "FACE", "length": width, "width": height, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "base", "partName": "BASE", "length": width, "width": depth, "thickness": t, "quantity": 1, "grain": "none"},
        ]
    if kind == "SIGN_HOLDER":
        return [
            {"partId": "face", "partName": "FACE", "length": width, "width": height, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "leg_l", "partName": "LEG_L", "length": depth, "width": 40, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "leg_r", "partName": "LEG_R", "length": depth, "width": 40, "thickness": t, "quantity": 1, "grain": "none"},
        ]
    if kind == "RISER_STAND":
        return [
            {"partId": "top", "partName": "TOP", "length": width, "width": depth, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "left", "partName": "LEFT", "length": depth, "width": height, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "right", "partName": "RIGHT", "length": depth, "width": height, "thickness": t, "quantity": 1, "grain": "none"},
        ]
    if kind == "DISPLAY_BOX":
        return [
            {"partId": "bottom", "partName": "BOTTOM", "length": width, "width": depth, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "left", "partName": "LEFT", "length": depth, "width": height, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "right", "partName": "RIGHT", "length": depth, "width": height, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "back", "partName": "BACK", "length": width, "width": height, "thickness": t, "quantity": 1, "grain": "none"},
            {"partId": "top", "partName": "TOP", "length": width, "width": depth, "thickness": t, "quantity": 1, "grain": "none"},
        ]
    return [
        {"partId": "column", "partName": "COLUMN", "length": height, "width": 60, "thickness": t, "quantity": 1, "grain": "none"},
        {"partId": "top", "partName": "TOP", "length": width, "width": depth, "thickness": t, "quantity": 1, "grain": "none"},
        {"partId": "base", "partName": "BASE", "length": width + 20, "width": depth + 20, "thickness": t, "quantity": 1, "grain": "none"},
    ]


def cut_bend_manifest(kind: str, parts: list[dict[str, Any]], *, bend_radius_mm: float = 6.0) -> dict[str, Any]:
    cuts = [{"partId": p["partId"], "profile": "outer", "length": p["length"], "width": p["width"]} for p in parts]
    bends = []
    if kind in {"MENU_STAND", "SIGN_HOLDER"}:
        bends.append({"partId": "face", "axis": "width", "angleDeg": 80, "radiusMm": bend_radius_mm, "source": "CONFIG"})
    man = {
        "kind": kind,
        "cuts": cuts,
        "bends": bends,
        "bendRadiusMm": bend_radius_mm,
        "heatParameters": {"source": "CONFIG", "label": "PARTIAL"},
        "liveLaser": False,
        "liveCnc": False,
        "liveMachineControl": False,
        "boundary": "geometry-interface-only",
    }
    man["manifestHash"] = stable_hash(man)
    return man


class AcrylicFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.nester = NestingV3()
        self.baseline = NestingEngine()
        self.items: dict[str, dict[str, Any]] = {}

    def materials(self) -> list[dict[str, Any]]:
        return [dict(v) for v in ACRYLIC_SHEETS.values()]

    def build(
        self,
        *,
        tenant_id: str,
        kind: str,
        sheet_sku: str = "ACR_CLEAR_5",
        render: bool = False,
        **dims: Any,
    ) -> dict[str, Any]:
        if kind not in ACRYLIC_FAMILIES:
            raise ValueError(kind)
        sheet = dict(ACRYLIC_SHEETS[sheet_sku])
        d = {**ACRYLIC_DEFAULTS[kind], **{k: v for k, v in dims.items() if v is not None}}
        parts = acrylic_parts(kind, width=d["width"], height=d["height"], depth=d["depth"], thickness=sheet["thickness"])
        product_id = new_id()
        bom_lines = []
        for p in parts:
            bom_lines.append(
                {
                    **p,
                    "skuId": product_id,
                    "productVersion": 1,
                    "bomLineId": p["partId"],
                    "hardware": False,
                }
            )
        bom = {"productId": product_id, "lines": bom_lines, "revision": 1}
        bom["bomHash"] = stable_hash(bom_lines)
        nest = self.nester.nest(bom, material="ACRYLIC", thickness=float(sheet["thickness"]), sheet=sheet, seed=f"acr:{kind}")
        packing = {
            "length": max(p["length"] for p in parts) + 20,
            "width": max(p["width"] for p in parts) + 20,
            "height": sheet["thickness"] * len(parts) + 20,
            "derivedFromPanels": True,
        }
        packing["packagingHash"] = stable_hash(packing)
        packing["costSource"] = "ESTIMATED"
        packing["packagingCost"] = 18.0
        area_m2 = sum(p["length"] * p["width"] * p["quantity"] for p in parts) / 1e6
        unit_cost = area_m2 * float(sheet["costPerM2"]) + packing["packagingCost"]
        rec = {
            "productId": product_id,
            "tenantId": tenant_id,
            "kind": kind,
            "family": "ACRYLIC_SHEET",
            "sheet": sheet,
            "dimensions": d,
            "parts": parts,
            "bom": bom,
            "engineeringHash": stable_hash({"kind": kind, "dims": d, "sheet": sheet["sku"]}),
            "nesting": {k: nest[k] for k in nest if k != "svg"},
            "cutBend": cut_bend_manifest(kind, parts),
            "packing": packing,
            "cost": {
                "unitCost": round(unit_cost, 2),
                "source": "CONFIG",
                "notLiveSupplierPrice": True,
            },
            "approvalState": "WAITING_APPROVAL",
            "liveMachineControl": False,
            "preview": None,
        }
        rec["lineage"] = {
            "engineeringHash": rec["engineeringHash"],
            "bomHash": bom["bomHash"],
            "nestingHash": nest.get("nestingHash"),
        }
        if render:
            job = self.platform.submit_job(
                {
                    "tenantId": tenant_id,
                    "jobType": "BLENDER_PREVIEW",
                    "mode": "ACRYLIC_PRODUCT",
                    "acrylic": {"kind": kind, "dimensions": d, "finish": sheet["finish"]},
                    "render": {"width": 256, "height": 256, "engine": "CYCLES", "device": "OPTIX", "samples": 8},
                    "timeoutSeconds": 180,
                }
            )
            preview = self.platform.execute_job(job)
            if preview.get("status") in {"queued", "retry_scheduled"}:
                preview = self.platform.execute_job(preview)
            rec["preview"] = preview
        rec["approval"] = {"status": "WAITING_APPROVAL", "liveMachineControl": False, "forbidden": ["LIVE_LASER", "LIVE_CNC"]}
        self.items[product_id] = rec
        return rec
