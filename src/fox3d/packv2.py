"""Packaging Engineering V2: board grade, compression estimate, dieline/preflight validators."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fox3d.ids import stable_hash
from fox3d.packaging import BOX_FAMILIES, PAPERBOARD_SHEETS, PackagingEngineeringDefinition, product_fit

BOARD_GRADES: dict[str, dict[str, Any]] = {
    "KRAFT_B_ECT32": {
        "sku": "KRAFT_B_ECT32",
        "caliperMm": 3.0,
        "flute": "B",
        "ectLbIn": 32.0,
        "basisWeightGsm": 580,
        "grain": "length",
        "source": "CONFIG",
        "certification": False,
    },
    "KRAFT_C_ECT44": {
        "sku": "KRAFT_C_ECT44",
        "caliperMm": 4.0,
        "flute": "C",
        "ectLbIn": 44.0,
        "basisWeightGsm": 720,
        "grain": "length",
        "source": "CONFIG",
        "certification": False,
    },
}


def board_grade(sku: str) -> dict[str, Any]:
    return dict(BOARD_GRADES[sku])


def box_compression_estimate(*, inner: dict[str, float], grade: dict[str, Any], safety_factor: float = 3.0) -> dict[str, Any]:
    """McKee-style engineering estimate. Not a lab certification."""
    L, W = float(inner["length"]), float(inner["width"])
    peri_in = (2 * (L + W)) / 25.4
    cal_in = float(grade.get("caliperMm") or 3) / 25.4
    ect = float(grade.get("ectLbIn") or 32)
    # BCT ≈ 5.87 * ECT * sqrt(P * t)  (lb) — published McKee approximation
    bct_lb = 5.87 * ect * (max(peri_in * cal_in, 0.01) ** 0.5)
    bct_n = bct_lb * 4.448
    allowable = bct_n / float(safety_factor)
    return {
        "bctNewton": round(bct_n, 2),
        "allowableNewton": round(allowable, 2),
        "safetyFactor": safety_factor,
        "formula": "McKee-5.87*ECT*sqrt(P*t)",
        "assumptions": ["regular slotted container", "no humidity derate", "no lab test"],
        "source": "ENGINEERING_ESTIMATE",
        "certification": False,
        "label": "PARTIAL",
        "grade": grade.get("sku"),
    }


def shipping_load_scenario(*, product_weight_kg: float, stack_count: int, compression: dict[str, Any]) -> dict[str, Any]:
    load_n = float(product_weight_kg) * 9.81 * max(int(stack_count) - 1, 0)
    margin = float(compression.get("allowableNewton") or 0) - load_n
    return {
        "stackCount": stack_count,
        "productWeightKg": product_weight_kg,
        "topLoadNewton": round(load_n, 2),
        "allowableNewton": compression.get("allowableNewton"),
        "marginNewton": round(margin, 2),
        "ok": margin > 0,
        "label": "ENGINEERING_ESTIMATE",
        "certification": False,
    }


def _seg_intersect(a, b, c, d) -> bool:
    def ccw(p, q, r):
        return (r[1] - p[1]) * (q[0] - p[0]) > (q[1] - p[1]) * (r[0] - p[0])

    return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)


def validate_dieline(dieline: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    panels = dieline.get("panels") or []
    if not panels:
        errors.append("no_panels")
    for p in panels:
        w, h = float(p.get("w") or 0), float(p.get("h") or 0)
        if w < 8 or h < 8:
            errors.append(f"short_flap:{p.get('id')}")
        if w <= 0 or h <= 0:
            errors.append(f"bounds:{p.get('id')}")
    ids = [p.get("id") for p in panels]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_panel")
    glue = dieline.get("glue") or []
    crease = dieline.get("crease") or []
    if panels and not crease and len(panels) > 1:
        errors.append("missing_crease")
    if panels and not glue and str(dieline.get("family") or "") in {"RSC_CARTON", "SLEEVE"}:
        errors.append("missing_glue")
    # naive self-intersection: sequential net rectangles sharing edges is OK; overlapping interiors is not
    x = 0.0
    boxes = []
    for p in panels:
        box = {"id": p.get("id"), "x": x, "y": 0.0, "w": float(p["w"]), "h": float(p["h"])}
        boxes.append(box)
        x += float(p["w"]) + 8
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            if a["x"] + a["w"] > b["x"] + 1e-6 and b["x"] + b["w"] > a["x"] + 1e-6 and a["y"] + a["h"] > b["y"] + 1e-6 and b["y"] + b["h"] > a["y"] + 1e-6:
                errors.append(f"overlap:{a['id']}:{b['id']}")
    return {"ok": not errors, "errors": errors, "foldConsistent": "missing_crease" not in errors, "source": "geometry"}


def validate_bleed(bleed: dict[str, Any], *, min_bleed: float = 3.0, min_safe: float = 5.0) -> dict[str, Any]:
    errors = []
    for z in bleed.get("zones") or []:
        if float(z.get("bleedMm") or 0) < min_bleed:
            errors.append(f"bleed:{z.get('name')}")
        if float(z.get("safeMm") or 0) < min_safe:
            errors.append(f"safe:{z.get('name')}")
    return {"ok": not errors, "errors": errors, "completePrintPreflight": False, "label": "PARTIAL"}


def artwork_preflight(path: Path | None, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = meta or {}
    findings: list[str] = []
    label = "PARTIAL"
    if path and path.exists():
        data = path.read_bytes()
        size = len(data)
        findings.append(f"bytes={size}")
        if data[:4] == b"%PDF":
            findings.append("pdf")
            if b"/Type /Font" not in data and b"/Font" not in data:
                findings.append("font_ref_unverified")
        elif data[:8] == b"\x89PNG\r\n\x1a\n":
            findings.append("png")
            # IHDR width/height
            if len(data) >= 24:
                w = int.from_bytes(data[16:20], "big")
                h = int.from_bytes(data[20:24], "big")
                findings.append(f"px={w}x{h}")
                dpi = meta.get("dpi")
                if dpi:
                    findings.append(f"dpi_estimate={dpi}")
        else:
            findings.append("unknown_format")
        label = "REAL" if findings else "PARTIAL"
    else:
        findings.append("missing_asset")
        label = "PARTIAL"
    return {
        "ok": "missing_asset" not in findings and "unknown_format" not in findings,
        "findings": findings,
        "pageOrArtboard": meta.get("pageMm"),
        "colorSpace": meta.get("colorSpace") or "unverified",
        "completePrintPreflight": False,
        "guessedPassForbidden": True,
        "label": label,
    }


def barcode_zone(panel: dict[str, float], *, quiet_mm: float = 3.0) -> dict[str, Any]:
    return {
        "x": 8,
        "y": 8,
        "w": min(40.0, float(panel.get("w") or 40)),
        "h": 16,
        "quietZoneMm": quiet_mm,
        "keepOut": True,
        "validator": None,
        "label": "PARTIAL",
        "note": "no formal barcode verifier connected",
    }


FIT_CASES: list[dict[str, Any]] = [
    {"name": "mailer_small", "family": "MAILER_BOX", "product": {"width": 80, "height": 40, "depth": 20}, "expect": True},
    {"name": "rsc_shoe", "family": "RSC_CARTON", "product": {"width": 320, "height": 120, "depth": 200}, "expect": True},
    {"name": "sleeve_book", "family": "SLEEVE", "product": {"width": 150, "height": 20, "depth": 210}, "expect": True},
    {"name": "tray_cos", "family": "TRAY", "product": {"width": 90, "height": 30, "depth": 90}, "expect": True},
    {"name": "pdq_unit", "family": "PDQ_TRAY", "product": {"width": 70, "height": 110, "depth": 40}, "expect": True},
    {"name": "zero", "family": "MAILER_BOX", "product": {"width": 0, "height": 0, "depth": 0}, "expect": False},
    {"name": "neg", "family": "RSC_CARTON", "product": {"width": -10, "height": 20, "depth": 20}, "expect": False},
    {"name": "huge_h", "family": "SLEEVE", "product": {"width": 50, "height": 2000, "depth": 50}, "expect": True},
    {"name": "needle", "family": "TRAY", "product": {"width": 2, "height": 2, "depth": 2}, "expect": True},
    {"name": "cube", "family": "MAILER_BOX", "product": {"width": 100, "height": 100, "depth": 100}, "expect": True},
    {"name": "flat", "family": "PDQ_TRAY", "product": {"width": 400, "height": 5, "depth": 300}, "expect": True},
    {"name": "tall_rsc", "family": "RSC_CARTON", "product": {"width": 100, "height": 600, "depth": 100}, "expect": True},
    {"name": "wide", "family": "MAILER_BOX", "product": {"width": 900, "height": 40, "depth": 40}, "expect": True},
    {"name": "missing_w", "family": "RSC_CARTON", "product": {"height": 40, "depth": 40}, "expect": True},
    {"name": "bad_family_dims", "family": "MAILER_BOX", "product": {"width": 10, "height": 10, "depth": 10}, "expect": True},
    {"name": "pdq_wide", "family": "PDQ_TRAY", "product": {"width": 250, "height": 180, "depth": 80}, "expect": True},
    {"name": "sleeve_thin", "family": "SLEEVE", "product": {"width": 40, "height": 4, "depth": 40}, "expect": True},
    {"name": "tray_deep", "family": "TRAY", "product": {"width": 120, "height": 80, "depth": 400}, "expect": True},
    {"name": "rsc_tiny", "family": "RSC_CARTON", "product": {"width": 20, "height": 20, "depth": 20}, "expect": True},
    {"name": "impossible_zero_family", "family": "MAILER_BOX", "product": {"width": 0, "height": 80, "depth": 40}, "expect": False},
]


def fit_regression() -> dict[str, Any]:
    rows = []
    for case in FIT_CASES:
        prod = case["product"]
        ok_input = all(float(prod.get(k) or 0) > 0 for k in ("width", "height", "depth") if k in prod) and float(prod.get("width") or prod.get("height") or 0) > 0
        if not ok_input:
            fit_ok = False
            fit = {"error": "invalid_product_dims"}
        else:
            fit = product_fit(prod, family=case["family"])
            inner = fit["inner"]
            fit_ok = inner["length"] > 0 and inner["width"] > 0 and inner["height"] > 0
        passed = fit_ok == case["expect"] if case["expect"] is False else fit_ok
        # impossible cases expect False
        if case["expect"] is False:
            passed = not fit_ok
        rows.append({"name": case["name"], "family": case["family"], "ok": fit_ok, "expect": case["expect"], "passed": passed})
    return {"cases": rows, "n": len(rows), "passed": sum(1 for r in rows if r["passed"]), "allOk": all(r["passed"] for r in rows)}


def carton_optimize(product: dict[str, float], *, grade: dict[str, Any], weight_kg: float = 0.4) -> dict[str, Any]:
    cands = []
    for fam in BOX_FAMILIES:
        fit = product_fit(product, family=fam)
        eng = PackagingEngineeringDefinition()
        defined = eng.define(family=fam, product_dims=product, sheet=PAPERBOARD_SHEETS["KRAFT_RSC_B"])
        panels = eng.dieline["panels"]
        area = sum(float(p["w"]) * float(p["h"]) for p in panels)
        outer = fit["outer"]
        cbm = (outer["length"] * outer["width"] * outer["height"]) / 1e9
        comp = box_compression_estimate(inner=fit["inner"], grade=grade)
        load = shipping_load_scenario(product_weight_kg=weight_kg, stack_count=5, compression=comp)
        geo = validate_dieline(eng.dieline)
        veto = not geo["ok"]
        cands.append(
            {
                "family": fam,
                "boardAreaMm2": round(area, 1),
                "cbm": round(cbm, 6),
                "compressionMargin": load["marginNewton"],
                "engineeringVeto": veto,
                "score": None if veto else round(-area / 1e4 - cbm * 100 + min(load["marginNewton"], 200) / 50, 4),
            }
        )
    legal = [c for c in cands if not c["engineeringVeto"]]
    legal.sort(key=lambda c: (-(c["score"] or -999), c["boardAreaMm2"]))
    return {"candidates": cands, "chosen": (legal or cands)[0], "engineeringVetoFirst": True}
