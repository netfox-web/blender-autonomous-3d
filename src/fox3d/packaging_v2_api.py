"""Packaging Engineering V2 — stateless calculation HTTP routes under /api/packaging/v2/."""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from fox3d.packv2 import (
    BOARD_GRADES,
    barcode_zone,
    board_grade,
    box_compression_estimate,
    carton_optimize,
    shipping_load_scenario,
    validate_bleed,
    validate_dieline,
)

_MAX_MM = 5000.0
_MAX_PANELS = 64
_MAX_ZONES = 64


def _require_body_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "請求內容須為 JSON 物件")
    return payload


def _as_number(raw: Any, field: str) -> float:
    if raw is None or isinstance(raw, (bool, str, list, dict)) or not isinstance(raw, (int, float)):
        raise HTTPException(422, f"{field} 必須是有限數值")
    try:
        val = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(422, f"{field} 必須是有限數值") from None
    if not math.isfinite(val):
        raise HTTPException(422, f"{field} 必須是有限數值")
    return val


def _positive_mm(raw: Any, field: str) -> float:
    val = _as_number(raw, field)
    if val <= 0 or val > _MAX_MM:
        raise HTTPException(422, f"{field} 須為不超過 {_MAX_MM:g} mm 的正數")
    return val


def _positive_finite(raw: Any, field: str) -> float:
    val = _as_number(raw, field)
    if val <= 0:
        raise HTTPException(422, f"{field} 必須是有限正數")
    return val


def _positive_int(raw: Any, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise HTTPException(422, f"{field} 須為正整數")
    if raw <= 0:
        raise HTTPException(422, f"{field} 須為正整數")
    return raw


def _require_grade(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(422, "grade 必填且須為字串")
    sku = raw.strip()
    if sku not in BOARD_GRADES:
        raise HTTPException(422, "未知的紙板等級")
    return board_grade(sku)


def _inner_dims(inner: Any) -> dict[str, float]:
    if not isinstance(inner, dict):
        raise HTTPException(422, "inner 須為物件")
    return {
        "length": _positive_mm(inner.get("length"), "inner.length"),
        "width": _positive_mm(inner.get("width"), "inner.width"),
        "height": _positive_mm(inner.get("height"), "inner.height"),
    }


def _product_dims(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise HTTPException(422, "product 須為物件")
    return {
        "width": _positive_mm(raw.get("width"), "product.width"),
        "height": _positive_mm(raw.get("height"), "product.height"),
        "depth": _positive_mm(raw.get("depth"), "product.depth"),
    }


def _panel_dims(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise HTTPException(422, "panel 須為物件")
    return {
        "w": _positive_mm(raw.get("w"), "panel.w"),
        "h": _positive_mm(raw.get("h"), "panel.h"),
    }


def _check_dieline(dieline: dict[str, Any]) -> None:
    panels = dieline.get("panels")
    if panels is not None:
        if not isinstance(panels, list):
            raise HTTPException(422, "panels 須為陣列")
        if len(panels) > _MAX_PANELS:
            raise HTTPException(422, f"panels 最多 {_MAX_PANELS} 項")
        for index, panel in enumerate(panels):
            if not isinstance(panel, dict):
                raise HTTPException(422, f"panels[{index}] 須為物件")
            panel_id = panel.get("id")
            if panel_id is None:
                continue
            if isinstance(panel_id, bool) or not isinstance(panel_id, (str, int)):
                raise HTTPException(422, f"panels[{index}].id 須為字串或整數")
    for field in ("glue", "crease"):
        raw = dieline.get(field)
        if raw is not None and not isinstance(raw, list):
            raise HTTPException(422, f"{field} 須為陣列")


def _check_bleed(bleed: dict[str, Any]) -> None:
    zones = bleed.get("zones")
    if zones is None:
        return
    if not isinstance(zones, list):
        raise HTTPException(422, "zones 須為陣列")
    if len(zones) > _MAX_ZONES:
        raise HTTPException(422, f"zones 最多 {_MAX_ZONES} 項")
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict):
            raise HTTPException(422, f"zones[{index}] 須為物件")
        for field in ("bleedMm", "safeMm"):
            if field in zone and zone[field] is not None:
                _as_number(zone[field], f"zones[{index}].{field}")


def packaging_v2_router() -> APIRouter:
    router = APIRouter(tags=["packaging-v2"])

    @router.get("/api/packaging/v2/board-grades")
    def list_board_grades() -> dict[str, Any]:
        items = []
        for sku, row in BOARD_GRADES.items():
            item = dict(row)
            item["sku"] = sku
            item["source"] = "CONFIG"
            item["certification"] = False
            items.append(item)
        return {"items": items}

    @router.post("/api/packaging/v2/compression")
    def compression_estimate(payload: Any = Body(default=None)) -> dict[str, Any]:
        body = _require_body_dict(payload)
        inner = _inner_dims(body.get("inner"))
        grade = _require_grade(body.get("grade"))
        raw_sf = body.get("safetyFactor", 3.0)
        safety_factor = _positive_finite(raw_sf, "safetyFactor")
        comp = box_compression_estimate(inner=inner, grade=grade, safety_factor=safety_factor)
        out: dict[str, Any] = {"compression": comp, "source": comp.get("source"), "certification": False}
        weight_raw = body.get("productWeightKg")
        stack_raw = body.get("stackCount")
        if weight_raw is None and stack_raw is None:
            return out
        if weight_raw is None or stack_raw is None:
            raise HTTPException(422, "productWeightKg 與 stackCount 須同時提供")
        weight = _positive_finite(weight_raw, "productWeightKg")
        stack_count = _positive_int(stack_raw, "stackCount")
        stack_scenario = shipping_load_scenario(product_weight_kg=weight, stack_count=stack_count, compression=comp)
        out["stack"] = stack_scenario
        return out

    @router.post("/api/packaging/v2/dieline/validate")
    def dieline_validate(payload: Any = Body(default=None)) -> dict[str, Any]:
        body = _require_body_dict(payload)
        dieline = body if "panels" in body or "family" in body else body.get("dieline")
        if not isinstance(dieline, dict):
            raise HTTPException(422, "刀模須為 JSON 物件")
        _check_dieline(dieline)
        return validate_dieline(dieline)

    @router.post("/api/packaging/v2/bleed/validate")
    def bleed_validate(payload: Any = Body(default=None)) -> dict[str, Any]:
        body = _require_body_dict(payload)
        bleed = body if "zones" in body else body.get("bleed")
        if not isinstance(bleed, dict):
            raise HTTPException(422, "出血／安全區須為 JSON 物件")
        _check_bleed(bleed)
        return validate_bleed(bleed)

    @router.post("/api/packaging/v2/barcode-zone")
    def barcode_zone_estimate(payload: Any = Body(default=None)) -> dict[str, Any]:
        body = _require_body_dict(payload)
        panel = _panel_dims(body.get("panel") or body)
        quiet_raw = body.get("quietMm", body.get("quiet_mm", 3.0))
        quiet = _positive_finite(quiet_raw, "quietMm")
        return barcode_zone(panel, quiet_mm=quiet)

    @router.post("/api/packaging/v2/carton-optimize")
    def carton_optimize_route(payload: Any = Body(default=None)) -> dict[str, Any]:
        body = _require_body_dict(payload)
        product = _product_dims(body.get("product") or body)
        grade = _require_grade(body.get("grade"))
        weight_raw = body.get("weightKg", body.get("productWeightKg", 0.4))
        weight = _positive_finite(weight_raw, "weightKg")
        return carton_optimize(product, grade=grade, weight_kg=weight)

    return router