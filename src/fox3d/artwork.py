"""Artwork Placement / Surface Decoration Engine V1.

Printable surfaces and millimetre placements are derived from existing
Engineering Definition. Blender and production files consume the same
placementHash. FIXTURE/REAL_LOGIC — not physical print, not Production Ready.
"""

from __future__ import annotations

import importlib.util
import math
import struct
import zlib
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.pngutil import write_png

FIT_CONTAIN = "CONTAIN"
FIT_COVER = "COVER"
FIT_STRETCH = "STRETCH"
ANCHORS = frozenset({"BOTTOM_LEFT", "BOTTOM_RIGHT", "TOP_LEFT", "TOP_RIGHT", "CENTER"})
PRINT_DPI_MIN = 150.0  # CONFIG policy, not a print-industry standard
PREVIEW_DPI_MIN = 72.0  # CONFIG
SAFE_MM_DEFAULT = 5.0  # CONFIG
BLEED_MM_DEFAULT = 3.0  # CONFIG
HANDLE_KEEP_W = 24.0  # CONFIG typical bar handle
HANDLE_KEEP_H = 140.0
HINGE_KEEP = 28.0
MM_EPS = 1e-4
UV_ROUNDTRIP_MM = 1e-3
DECORATABLE = {
    "door": ("width", "length"),
    "drawer_front": ("width", "length"),
    "top": ("length", "width"),
    "desktop": ("length", "width"),
    "lid": ("length", "width"),
    "seat": ("length", "width"),
    "face": ("length", "width"),
    "kick_plate": ("length", "width"),
    "front": ("length", "width"),
}


class ArtworkError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ArtworkError("BLOCKED", f"invalid {name}") from exc
    if not math.isfinite(number):
        raise ArtworkError("BLOCKED", f"non-finite {name}")
    if positive and number <= 0:
        raise ArtworkError("BLOCKED", f"{name} must be > 0")
    return number


def _present(value: Any) -> bool:
    return value is not None and value != ""


def png_size(data: bytes) -> tuple[int | None, int | None]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    if data[12:16] != b"IHDR":
        return None, None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def decode_png_rgb(data: bytes) -> tuple[int, int, bytes]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ArtworkError("BLOCKED", "artwork is not PNG")
    offset = 8
    width = height = bit_depth = color_type = None
    idat = b""
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        tag = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk[:10])
        elif tag == b"IDAT":
            idat += chunk
        elif tag == b"IEND":
            break
    if width is None or height is None or bit_depth != 8 or color_type not in {2, 6}:
        raise ArtworkError("BLOCKED", "unsupported PNG")
    raw = zlib.decompress(idat)
    bpp = 3 if color_type == 2 else 4
    stride = width * bpp
    out = bytearray(width * height * 3)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        filt = raw[pos]
        pos += 1
        row = bytearray(raw[pos : pos + stride])
        pos += stride
        if filt == 1:
            for i in range(stride):
                row[i] = (row[i] + (row[i - bpp] if i >= bpp else 0)) & 255
        elif filt == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 255
        elif filt == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) // 2)) & 255
        elif filt == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[i] = (row[i] + pr) & 255
        elif filt != 0:
            raise ArtworkError("BLOCKED", "unsupported PNG filter")
        for x in range(width):
            src = x * bpp
            dst = (y * width + x) * 3
            out[dst : dst + 3] = row[src : src + 3]
        prev = row
    return width, height, bytes(out)


def checkerboard_rgb(width: int, height: int, *, cell: int = 32) -> bytes:
    buf = bytearray(width * height * 3)
    cx, cy = width // 2, height // 2
    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 3
            on = ((x // cell) + (y // cell)) % 2 == 0
            buf[i] = buf[i + 1] = buf[i + 2] = 240 if on else 20
            if abs(x - cx) < 3 or abs(y - cy) < 3:
                buf[i] = 220
                buf[i + 1] = 30
                buf[i + 2] = 30
            if x < 8:
                buf[i], buf[i + 1], buf[i + 2] = 20, 180, 40
            if x >= width - 8:
                buf[i], buf[i + 1], buf[i + 2] = 30, 80, 220
            if y < 8:
                buf[i], buf[i + 1], buf[i + 2] = 230, 200, 20
    return bytes(buf)


def crop_rgb(rgb: bytes, src_w: int, src_h: int, x: int, y: int, w: int, h: int) -> bytes:
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > src_w or y + h > src_h:
        raise ArtworkError("BLOCKED", "invalid crop")
    out = bytearray(w * h * 3)
    for row in range(h):
        src = ((y + row) * src_w + x) * 3
        dst = row * w * 3
        out[dst : dst + w * 3] = rgb[src : src + w * 3]
    return bytes(out)


def _engineering(spec: Any) -> dict[str, Any]:
    if hasattr(spec, "model_dump") and hasattr(spec, "engineering_hash"):
        body = spec.model_dump(mode="json")
        body["engineeringHash"] = spec.engineering_hash()
        return body
    if not isinstance(spec, dict):
        raise ArtworkError("BLOCKED", "engineering definition required")
    return dict(spec)


def _component_mm(part: dict[str, Any]) -> tuple[float, float] | None:
    role = str(part.get("role") or part.get("partType") or "").lower()
    keys = DECORATABLE.get(role)
    if keys is None and str(part.get("partId") or "").lower() in DECORATABLE:
        keys = DECORATABLE[str(part.get("partId") or "").lower()]
    if keys is None:
        return None
    width = _finite(part.get(keys[0]), "surface width", positive=True)
    height = _finite(part.get(keys[1]), "surface height", positive=True)
    return width, height


def _canonicalize_basis(basis_x: tuple[float, float, float], basis_y: tuple[float, float, float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    def _norm(vec: tuple[float, float, float]) -> tuple[float, float, float]:
        mag = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
        if mag <= 0 or not math.isfinite(mag):
            raise ArtworkError("BLOCKED", "invalid surface basis")
        return (round(vec[0] / mag, 9), round(vec[1] / mag, 9), round(vec[2] / mag, 9))

    return _norm(basis_x), _norm(basis_y)


def surface_hash_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenantId": row.get("tenantId"),
        "productId": row.get("productId"),
        "candidateId": row.get("candidateId"),
        "version": row.get("version"),
        "engineeringHash": row.get("engineeringHash"),
        "componentId": row.get("componentId"),
        "face": row.get("face"),
        "origin": row.get("origin"),
        "basisX": row.get("basisX"),
        "basisY": row.get("basisY"),
        "widthMm": row.get("widthMm"),
        "heightMm": row.get("heightMm"),
        "safeMm": row.get("safeMm"),
        "bleedMm": row.get("bleedMm"),
        "keepOuts": row.get("keepOuts"),
        "trimSource": row.get("trimSource"),
    }


def derive_printable_surfaces(
    spec: Any,
    *,
    tenant_id: str,
    product_id: str | None = None,
    candidate_id: str | None = None,
    version: Any = None,
    family: str | None = None,
) -> list[dict[str, Any]]:
    eng = _engineering(spec)
    if eng.get("tenantId") and eng.get("tenantId") != tenant_id:
        raise ArtworkError("BLOCKED", "cross-tenant engineering")
    eng_hash = eng.get("engineeringHash")
    if not _present(eng_hash):
        raise ArtworkError("BLOCKED", "engineeringHash missing")
    pid = product_id or eng.get("productId")
    if not _present(pid):
        raise ArtworkError("BLOCKED", "product identity missing")
    parts = [p for p in (eng.get("components") or []) if isinstance(p, dict)]
    if family == "PACKAGING" or (eng.get("dieline") or {}).get("panels"):
        for panel in (eng.get("dieline") or {}).get("panels") or []:
            parts.append(
                {
                    "partId": panel.get("id") or panel.get("partId"),
                    "partName": str(panel.get("id") or "PANEL").upper(),
                    "role": "face",
                    "length": panel.get("w") or panel.get("length"),
                    "width": panel.get("h") or panel.get("width"),
                }
            )
    surfaces: list[dict[str, Any]] = []
    door_index = 0
    door_count = int(eng.get("doorCount") or 0)
    handles = bool(eng.get("handles"))
    for part in parts:
        mm = _component_mm(part)
        if mm is None:
            continue
        width_mm, height_mm = mm
        role = str(part.get("role") or part.get("partType") or "face").lower()
        cid = str(part.get("partId") or part.get("partName") or role)
        object_name = str(part.get("partName") or cid)
        origin_x = 0.0
        hinge = "NONE"
        if role == "door":
            origin_x = round(door_index * width_mm, 6)
            hinge = "LEFT" if door_index < max(door_count, 1) / 2 else "RIGHT"
            door_index += 1
        basis_x, basis_y = _canonicalize_basis((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        keep = _derived_keepouts(width_mm, height_mm, role=role, hinge=hinge, handles=handles, hardware=eng.get("hardware") or [])
        rec = {
            "surfaceId": new_id(),
            "tenantId": tenant_id,
            "productId": pid,
            "candidateId": candidate_id or eng.get("candidateId"),
            "version": version if version is not None else eng.get("revision") or 1,
            "kind": eng.get("kind") or family or "CABINET",
            "engineeringHash": eng_hash,
            "componentId": cid,
            "objectName": object_name,
            "face": "FRONT",
            "mirrored": False,
            "origin": {"xMm": origin_x, "yMm": 0.0},
            "basisX": list(basis_x),
            "basisY": list(basis_y),
            "widthMm": width_mm,
            "heightMm": height_mm,
            "safeMm": SAFE_MM_DEFAULT,
            "bleedMm": BLEED_MM_DEFAULT,
            "trimSource": "CONFIG",
            "keepOuts": keep,
            "hingeEdge": hinge,
            "liveMachineControl": False,
        }
        rec["surfaceHash"] = stable_hash(surface_hash_payload(rec))
        surfaces.append(rec)
    if not surfaces:
        raise ArtworkError("BLOCKED", "no printable surface in engineering")
    return surfaces


def _derived_keepouts(
    width_mm: float,
    height_mm: float,
    *,
    role: str,
    hinge: str,
    handles: bool,
    hardware: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    hw_names = {str(h.get("partName") or h.get("sku") or "").lower() for h in hardware if isinstance(h, dict)}
    if role == "door" and (handles or "handle" in hw_names):
        hx = width_mm - HANDLE_KEEP_W - 18.0 if hinge == "LEFT" else 18.0
        hy = (height_mm - HANDLE_KEEP_H) / 2.0
        rows.append(
            {
                "kind": "HANDLE",
                "xMm": round(hx, 4),
                "yMm": round(hy, 4),
                "widthMm": HANDLE_KEEP_W,
                "heightMm": HANDLE_KEEP_H,
                "source": "CONFIG",
                "truthLabel": "CONFIG",
            }
        )
    if role == "door" and ("hinge" in hw_names or hinge in {"LEFT", "RIGHT"}):
        x = 0.0 if hinge == "LEFT" else width_mm - HINGE_KEEP
        for y in (80.0, height_mm - 80.0 - HINGE_KEEP):
            rows.append(
                {
                    "kind": "HINGE",
                    "xMm": round(x, 4),
                    "yMm": round(max(0.0, y), 4),
                    "widthMm": HINGE_KEEP,
                    "heightMm": HINGE_KEEP,
                    "source": "CONFIG",
                    "truthLabel": "CONFIG",
                }
            )
            rows.append(
                {
                    "kind": "DRILLING",
                    "xMm": round(x, 4),
                    "yMm": round(max(0.0, y), 4),
                    "widthMm": 12.0,
                    "heightMm": 12.0,
                    "source": "CONFIG",
                    "truthLabel": "PARTIAL",
                }
            )
    if not rows:
        rows.append({"kind": "UNKNOWN", "source": "UNKNOWN", "truthLabel": "PARTIAL", "xMm": 0, "yMm": 0, "widthMm": 0, "heightMm": 0})
    return rows


def mm_to_uv(x_mm: float, y_mm: float, surface: dict[str, Any], *, mirrored: bool = False) -> tuple[float, float]:
    width = _finite(surface.get("widthMm"), "widthMm", positive=True)
    height = _finite(surface.get("heightMm"), "heightMm", positive=True)
    u = _finite(x_mm, "xMm") / width
    v = _finite(y_mm, "yMm") / height
    if mirrored:
        u = 1.0 - u
    if not math.isfinite(u) or not math.isfinite(v):
        raise ArtworkError("BLOCKED", "non-finite UV")
    return u, v


def uv_to_mm(u: float, v: float, surface: dict[str, Any], *, mirrored: bool = False) -> tuple[float, float]:
    width = _finite(surface.get("widthMm"), "widthMm", positive=True)
    height = _finite(surface.get("heightMm"), "heightMm", positive=True)
    uu = 1.0 - _finite(u, "u") if mirrored else _finite(u, "u")
    return uu * width, _finite(v, "v") * height


def roundtrip_ok(x_mm: float, y_mm: float, surface: dict[str, Any], *, mirrored: bool = False) -> bool:
    u, v = mm_to_uv(x_mm, y_mm, surface, mirrored=mirrored)
    bx, by = uv_to_mm(u, v, surface, mirrored=mirrored)
    return abs(bx - x_mm) <= UV_ROUNDTRIP_MM and abs(by - y_mm) <= UV_ROUNDTRIP_MM


def _aabb(x: float, y: float, w: float, h: float) -> dict[str, float]:
    return {"xMm": x, "yMm": y, "widthMm": w, "heightMm": h}


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    aw = float(a.get("widthMm") or 0)
    ah = float(a.get("heightMm") or 0)
    bw = float(b.get("widthMm") or 0)
    bh = float(b.get("heightMm") or 0)
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return (
        float(a["xMm"]) < float(b["xMm"]) + bw
        and float(a["xMm"]) + aw > float(b["xMm"])
        and float(a["yMm"]) < float(b["yMm"]) + bh
        and float(a["yMm"]) + ah > float(b["yMm"])
    )


def _fit_rect(
    *,
    box_w: float,
    box_h: float,
    art_w_px: int | None,
    art_h_px: int | None,
    fit: str,
    anchor: str,
) -> dict[str, float]:
    if fit == FIT_STRETCH:
        raise ArtworkError("BLOCKED", "STRETCH is forbidden")
    if fit not in {FIT_CONTAIN, FIT_COVER}:
        raise ArtworkError("BLOCKED", "unknown fit mode")
    if art_w_px and art_h_px:
        aspect = art_w_px / art_h_px
        box_aspect = box_w / box_h
        if fit == FIT_CONTAIN:
            if aspect > box_aspect:
                fw, fh = box_w, box_w / aspect
            else:
                fh, fw = box_h, box_h * aspect
        else:
            if aspect > box_aspect:
                fh, fw = box_h, box_h * aspect
            else:
                fw, fh = box_w, box_w / aspect
    else:
        fw, fh = box_w, box_h
    if anchor not in ANCHORS:
        raise ArtworkError("BLOCKED", "unknown anchor")
    if "LEFT" in anchor:
        x = 0.0
    elif "RIGHT" in anchor:
        x = box_w - fw
    else:
        x = (box_w - fw) / 2.0
    if "BOTTOM" in anchor:
        y = 0.0
    elif "TOP" in anchor:
        y = box_h - fh
    else:
        y = (box_h - fh) / 2.0
    return {"xMm": x, "yMm": y, "widthMm": fw, "heightMm": fh}


def effective_dpi(
    pixel_w: int | None,
    placed_width_mm: float,
    pixel_h: int | None = None,
    placed_height_mm: float | None = None,
) -> float | None:
    values: list[float] = []
    if pixel_w and placed_width_mm and placed_width_mm > 0:
        inches_w = placed_width_mm / 25.4
        if inches_w > 0:
            values.append(float(pixel_w) / inches_w)
    if pixel_h and placed_height_mm and placed_height_mm > 0:
        inches_h = placed_height_mm / 25.4
        if inches_h > 0:
            values.append(float(pixel_h) / inches_h)
    if not values:
        return None
    return min(values)


def evaluate_placement_policy(
    surface: dict[str, Any],
    placed: dict[str, Any],
    *,
    dpi: float | None,
    protected: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    keepouts = [k for k in (surface.get("keepOuts") or []) if isinstance(k, dict) and k.get("kind") not in {None, "UNKNOWN"}]
    for region in protected or []:
        if not isinstance(region, dict):
            continue
        for keep in keepouts:
            if keep.get("kind") in {"HANDLE", "HINGE", "DRILLING", "SEAM"} and _overlap(region, keep):
                blockers.append("BLOCKED_PLACEMENT")
    bleed = _finite(surface.get("bleedMm") if surface.get("bleedMm") is not None else BLEED_MM_DEFAULT, "bleedMm")
    safe = _finite(surface.get("safeMm") if surface.get("safeMm") is not None else SAFE_MM_DEFAULT, "safeMm")
    if bleed < 0 or safe < 0:
        raise ArtworkError("BLOCKED", "negative bleed/safe")
    print_ready = dpi is not None and dpi >= PRINT_DPI_MIN
    preview_ok = dpi is None or dpi >= PREVIEW_DPI_MIN
    if dpi is not None and dpi < PRINT_DPI_MIN:
        print_label = "PARTIAL"
    elif dpi is None:
        print_label = "UNKNOWN"
    else:
        print_label = "CONFIG"
    return {
        "blockers": blockers,
        "printReady": print_ready and not blockers,
        "previewOk": preview_ok and not blockers,
        "printPreflight": "PARTIAL",
        "dpiPolicy": {"printMin": PRINT_DPI_MIN, "previewMin": PREVIEW_DPI_MIN, "source": "CONFIG"},
        "dpi": dpi,
        "dpiLabel": print_label if dpi is not None else "UNKNOWN",
        "bleedMm": bleed,
        "safeMm": safe,
        "ok": not blockers,
    }


def placement_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenantId": row.get("tenantId"),
        "productId": row.get("productId"),
        "candidateId": row.get("candidateId"),
        "version": row.get("version"),
        "engineeringHash": row.get("engineeringHash"),
        "surfaceId": row.get("surfaceId"),
        "surfaceHash": row.get("surfaceHash"),
        "artworkId": row.get("artworkId"),
        "artworkHash": row.get("artworkHash"),
        "xMm": row.get("xMm"),
        "yMm": row.get("yMm"),
        "widthMm": row.get("widthMm"),
        "heightMm": row.get("heightMm"),
        "rotationDeg": row.get("rotationDeg"),
        "anchor": row.get("anchor"),
        "fit": row.get("fit"),
        "crop": row.get("crop"),
        "protectedRegions": row.get("protectedRegions"),
        "mirrored": bool(row.get("mirrored")),
        "objectName": row.get("objectName"),
        "componentId": row.get("componentId"),
        "face": row.get("face") or "FRONT",
        "relation": row.get("relation") or "SINGLE_SURFACE",
        "masterHash": row.get("masterHash"),
        "masterCropMm": row.get("masterCropMm"),
        "masterSurfaceIds": list(row.get("masterSurfaceIds") or []),
        "masterId": row.get("masterId"),
        "uv": row.get("uv"),
    }


_APPLIED_IDENTITY_KEYS = (
    "placementId",
    "objectName",
    "componentId",
    "face",
    "relation",
    "engineeringHash",
    "surfaceHash",
    "artworkHash",
    "placementHash",
    "finalUvHash",
)


def canonical_final_sampling(
    uv_rect: dict[str, Any],
    *,
    rotation_deg: float = 0.0,
    mirrored: bool = False,
) -> list[list[float]]:
    try:
        u0 = float(uv_rect["u0"])
        v0 = float(uv_rect["v0"])
        u1 = float(uv_rect["u1"])
        v1 = float(uv_rect["v1"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ArtworkError("BLOCKED", "missing uvRect") from exc
    if not all(math.isfinite(v) for v in (u0, v0, u1, v1)):
        raise ArtworkError("BLOCKED", "non-finite uvRect")
    rot = float(rotation_deg or 0.0) % 360.0
    if rot not in {0.0, 90.0, 180.0, 270.0}:
        raise ArtworkError("BLOCKED", "unsupported rotation")
    cx, cy = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    steps = int(rot // 90.0)
    for _ in range(steps):
        corners = [(cx - (y - cy), cy + (x - cx)) for x, y in corners]
    if mirrored:
        corners = [(u0 + u1 - x, y) for x, y in corners]
    return [[float(x), float(y)] for x, y in corners]


def final_uv_identity(
    *,
    placement_id: Any,
    object_name: Any,
    component_id: Any,
    face: Any,
    relation: Any,
    uv_rect: dict[str, Any],
    rotation_deg: Any = 0.0,
    mirrored: Any = False,
) -> dict[str, Any]:
    sampling = canonical_final_sampling(uv_rect, rotation_deg=float(rotation_deg or 0.0), mirrored=bool(mirrored))
    payload = {
        "placementId": placement_id,
        "objectName": object_name,
        "componentId": component_id,
        "face": face or "FRONT",
        "relation": relation or "SINGLE_SURFACE",
        "uvRect": {
            "u0": float(uv_rect["u0"]),
            "v0": float(uv_rect["v0"]),
            "u1": float(uv_rect["u1"]),
            "v1": float(uv_rect["v1"]),
        },
        "rotationDeg": float(rotation_deg or 0.0) % 360.0,
        "mirrored": bool(mirrored),
        "finalSampling": sampling,
    }
    return {**payload, "finalUvHash": stable_hash(payload)}


def canonical_source_crop(
    *,
    pixel_width: int | None,
    pixel_height: int | None,
    box_w_mm: float,
    box_h_mm: float,
    placed: dict[str, Any],
    fit: str,
    anchor: str | None = None,
) -> dict[str, Any]:
    if fit == FIT_STRETCH:
        raise ArtworkError("BLOCKED", "STRETCH is forbidden")
    crop: dict[str, Any] = {
        "xMm": 0.0,
        "yMm": 0.0,
        "widthMm": float(placed["widthMm"]),
        "heightMm": float(placed["heightMm"]),
        "fit": fit,
        "anchor": anchor,
    }
    pw = int(pixel_width) if pixel_width else None
    ph = int(pixel_height) if pixel_height else None
    if fit == FIT_COVER and pw and ph:
        placed_w = float(placed["widthMm"])
        placed_h = float(placed["heightMm"])
        if placed_w <= 0 or placed_h <= 0:
            raise ArtworkError("BLOCKED", "placed size")
        px = float(placed.get("xMm") or 0.0)
        py = float(placed.get("yMm") or 0.0)
        vis_x0 = max(0.0, px)
        vis_x1 = min(float(box_w_mm), px + placed_w)
        vis_y0 = max(0.0, py)
        vis_y1 = min(float(box_h_mm), py + placed_h)
        vis_w = max(0.0, vis_x1 - vis_x0)
        vis_h = max(0.0, vis_y1 - vis_y0)
        src_x = max(0, int(round((vis_x0 - px) * pw / placed_w)))
        src_y = max(0, int(round((py + placed_h - vis_y1) * ph / placed_h)))
        src_w = max(1, int(round(vis_w * pw / placed_w)))
        src_h = max(1, int(round(vis_h * ph / placed_h)))
        src_x = min(src_x, max(0, pw - 1))
        src_y = min(src_y, max(0, ph - 1))
        src_w = min(src_w, pw - src_x)
        src_h = min(src_h, ph - src_y)
        crop.update({"sourceXPx": src_x, "sourceYPx": src_y, "sourceWPx": src_w, "sourceHPx": src_h})
    elif pw and ph:
        crop.update({"sourceXPx": 0, "sourceYPx": 0, "sourceWPx": pw, "sourceHPx": ph})
    return crop


def _copy_rgb_pixel(src: bytes, sw: int, sx: int, sy: int, dest: bytearray, dw: int, dx: int, dy: int) -> None:
    si = (sy * sw + sx) * 3
    di = (dy * dw + dx) * 3
    dest[di : di + 3] = src[si : si + 3]


def flip_h_rgb(rgb: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            _copy_rgb_pixel(rgb, width, x, y, out, width, width - 1 - x, y)
    return bytes(out)


def rot90_cw_rgb(rgb: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    nw, nh = height, width
    out = bytearray(nw * nh * 3)
    for y in range(height):
        for x in range(width):
            _copy_rgb_pixel(rgb, width, x, y, out, nw, height - 1 - y, x)
    return bytes(out), nw, nh


def orient_rgb(rgb: bytes, width: int, height: int, *, rotation_deg: float = 0.0, mirrored: bool = False) -> tuple[bytes, int, int]:
    rot = float(rotation_deg or 0.0) % 360.0
    if rot not in {0.0, 90.0, 180.0, 270.0}:
        raise ArtworkError("BLOCKED", "unsupported rotation")
    buf = rgb
    w, h = width, height
    if mirrored:
        buf = flip_h_rgb(buf, w, h)
    if rot == 90.0:
        buf, w, h = rot90_cw_rgb(buf, w, h)
    elif rot == 180.0:
        buf, w, h = rot90_cw_rgb(buf, w, h)
        buf, w, h = rot90_cw_rgb(buf, w, h)
    elif rot == 270.0:
        buf, w, h = rot90_cw_rgb(buf, w, h)
        buf, w, h = rot90_cw_rgb(buf, w, h)
        buf, w, h = rot90_cw_rgb(buf, w, h)
    return buf, w, h


def scale_rgb(rgb: bytes, src_w: int, src_h: int, dest_w: int, dest_h: int) -> bytes:
    if dest_w <= 0 or dest_h <= 0 or src_w <= 0 or src_h <= 0:
        raise ArtworkError("BLOCKED", "invalid scale")
    out = bytearray(dest_w * dest_h * 3)
    for y in range(dest_h):
        sy = min(src_h - 1, (y * src_h) // dest_h)
        for x in range(dest_w):
            sx = min(src_w - 1, (x * src_w) // dest_w)
            _copy_rgb_pixel(rgb, src_w, sx, sy, out, dest_w, x, y)
    return bytes(out)


def blit_rgb(dest: bytearray, dw: int, dh: int, src: bytes, sw: int, sh: int, dx: int, dy: int) -> None:
    for y in range(sh):
        ty = dy + y
        if ty < 0 or ty >= dh:
            continue
        for x in range(sw):
            tx = dx + x
            if tx < 0 or tx >= dw:
                continue
            _copy_rgb_pixel(src, sw, x, y, dest, dw, tx, ty)


def production_transform(
    *,
    rec: dict[str, Any],
    surface: dict[str, Any],
    source_crop: dict[str, Any],
    final_uv_hash: str,
) -> dict[str, Any]:
    payload = {
        "fit": rec.get("fit") or FIT_CONTAIN,
        "anchor": rec.get("anchor") or "BOTTOM_LEFT",
        "rotationDeg": float(rec.get("rotationDeg") or 0.0) % 360.0,
        "mirrored": bool(rec.get("mirrored")),
        "canvasMm": {"widthMm": float(surface["widthMm"]), "heightMm": float(surface["heightMm"])},
        "placedMm": {
            "xMm": float(rec.get("xMm") or 0.0),
            "yMm": float(rec.get("yMm") or 0.0),
            "widthMm": float(rec.get("widthMm") or surface["widthMm"]),
            "heightMm": float(rec.get("heightMm") or surface["heightMm"]),
        },
        "sourceCropPx": {
            "x": int(source_crop.get("sourceXPx") or 0),
            "y": int(source_crop.get("sourceYPx") or 0),
            "w": int(source_crop.get("sourceWPx") or 0),
            "h": int(source_crop.get("sourceHPx") or 0),
        },
        "background": "BLACK",
        "placementHash": rec.get("placementHash"),
        "finalUvHash": final_uv_hash,
    }
    return {**payload, "transformHash": stable_hash(payload)}


_MASTER_RELATION_FIELDS = (
    "masterHash",
    "tenantId",
    "productId",
    "candidateId",
    "version",
    "engineeringHash",
    "surfaceIds",
    "panelOrder",
    "widthMm",
    "heightMm",
    "seamMm",
    "seamSource",
    "cropGeometry",
)


def master_relation_hash(rel: dict[str, Any]) -> str:
    return stable_hash({k: rel.get(k) for k in _MASTER_RELATION_FIELDS})


def _source_crop_matches(stored: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    if not isinstance(stored, dict) or not isinstance(expected, dict):
        return False
    for key in ("sourceXPx", "sourceYPx", "sourceWPx", "sourceHPx"):
        want = expected.get(key)
        if want is None:
            continue
        got = stored.get(key)
        if got is None:
            return False
        try:
            if int(got) != int(want):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _job_artifact_meta(done: dict[str, Any]) -> tuple[str | None, int | None]:
    output = done.get("output") if isinstance(done.get("output"), dict) else {}
    files = output.get("files") if isinstance(output.get("files"), dict) else {}
    artifact = done.get("artifact") if isinstance(done.get("artifact"), dict) else {}
    sha = done.get("outputHash") or files.get("beautyHash") or artifact.get("sha256")
    size = done.get("outputSize")
    if size is None:
        size = files.get("beautySize")
    if size is None:
        size = artifact.get("size")
    sha_s = str(sha) if sha not in {None, ""} else None
    try:
        size_i = int(size) if size is not None else None
    except (TypeError, ValueError):
        size_i = None
    return sha_s, size_i


def _norm_sampling(value: Any) -> list[list[float]] | None:
    if not isinstance(value, (list, tuple)):
        return None
    out: list[list[float]] = []
    try:
        for pair in value:
            out.append([float(pair[0]), float(pair[1])])
    except (TypeError, ValueError, IndexError):
        return None
    return out


def _applied_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(k) for k in _APPLIED_IDENTITY_KEYS)


def master_canvas(surfaces: list[dict[str, Any]], *, seam_mm: float | None = None) -> dict[str, Any]:
    if not surfaces:
        raise ArtworkError("BLOCKED", "master canvas requires surfaces")
    tenant = surfaces[0]["tenantId"]
    product = surfaces[0]["productId"]
    eng = surfaces[0]["engineeringHash"]
    ordered = sorted(list(surfaces), key=lambda s: float((s.get("origin") or {}).get("xMm") or 0.0))
    derived_seams: list[float] = []
    for i in range(1, len(ordered)):
        prev = ordered[i - 1]
        cur = ordered[i]
        gap = float((cur.get("origin") or {}).get("xMm") or 0.0) - (
            float((prev.get("origin") or {}).get("xMm") or 0.0) + float(prev.get("widthMm") or 0.0)
        )
        derived_seams.append(gap)
    if seam_mm is None:
        seam = derived_seams[0] if derived_seams else 0.0
        seam_source = "ENGINEERING" if derived_seams else "CONFIG"
        if derived_seams and any(abs(s - seam) > MM_EPS for s in derived_seams):
            raise ArtworkError("BLOCKED", "inconsistent engineering seam")
    else:
        seam = _finite(seam_mm, "seamMm")
        seam_source = "CONFIG"
    if seam < 0:
        raise ArtworkError("BLOCKED", "negative seam")
    width = 0.0
    height = 0.0
    panels = []
    cursor = 0.0
    for i, surf in enumerate(ordered):
        if surf.get("tenantId") != tenant:
            raise ArtworkError("BLOCKED", "cross-tenant surface")
        if surf.get("productId") != product:
            raise ArtworkError("BLOCKED", "cross-product surface")
        if surf.get("engineeringHash") != eng:
            raise ArtworkError("BLOCKED", "stale engineeringHash")
        if surf.get("candidateId") not in {None, surfaces[0].get("candidateId")}:
            raise ArtworkError("BLOCKED", "cross-candidate surface")
        if surf.get("version") not in {None, surfaces[0].get("version")}:
            raise ArtworkError("BLOCKED", "cross-version surface")
        w = _finite(surf["widthMm"], "widthMm", positive=True)
        h = _finite(surf["heightMm"], "heightMm", positive=True)
        panels.append(
            {
                "surfaceId": surf["surfaceId"],
                "surfaceHash": surf["surfaceHash"],
                "componentId": surf["componentId"],
                "index": i,
                "xMm": cursor,
                "yMm": 0.0,
                "widthMm": w,
                "heightMm": h,
            }
        )
        cursor += w
        if i < len(ordered) - 1:
            cursor += seam
        height = max(height, h)
    width = cursor
    rec = {
        "tenantId": tenant,
        "productId": product,
        "engineeringHash": eng,
        "widthMm": width,
        "heightMm": height,
        "seamMm": seam,
        "seamSource": seam_source,
        "candidateId": surfaces[0].get("candidateId"),
        "version": surfaces[0].get("version"),
        "panels": panels,
    }
    rec["masterHash"] = stable_hash({k: rec[k] for k in rec if k != "masterHash"})
    return rec


def split_master(master: dict[str, Any], *, stretch: bool = False) -> list[dict[str, Any]]:
    if stretch:
        raise ArtworkError("BLOCKED", "panel split may not stretch")
    crops = []
    prev_right = None
    seam = float(master.get("seamMm") or 0)
    for panel in master.get("panels") or []:
        left = float(panel["xMm"])
        right = left + float(panel["widthMm"])
        if prev_right is not None and abs(left - (prev_right + seam)) > MM_EPS:
            raise ArtworkError("BLOCKED", "panel crop discontinuity")
        prev_right = right
        crops.append(
            {
                "surfaceId": panel["surfaceId"],
                "surfaceHash": panel["surfaceHash"],
                "componentId": panel["componentId"],
                "cropMm": {"xMm": left, "yMm": 0.0, "widthMm": panel["widthMm"], "heightMm": panel["heightMm"]},
                "masterHash": master.get("masterHash"),
            }
        )
    return crops


class ArtworkFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.artworks: dict[str, dict[str, Any]] = {}
        self.surfaces: dict[str, dict[str, Any]] = {}
        self.placements: dict[str, dict[str, Any]] = {}
        self.by_hash: dict[str, str] = {}
        self.engineering: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
        self.masters: dict[str, dict[str, Any]] = {}

    def register_surfaces(self, spec: Any, *, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        rows = derive_printable_surfaces(spec, tenant_id=tenant_id, **kwargs)
        eng = _engineering(spec)
        if rows:
            self.engineering[(tenant_id, rows[0]["productId"], rows[0]["engineeringHash"])] = eng
        out = []
        for row in rows:
            if row["surfaceId"] in self.surfaces:
                raise ArtworkError("BLOCKED", "duplicate surfaceId")
            if row["surfaceHash"] in self.by_hash:
                raise ArtworkError("BLOCKED", "duplicate surfaceHash")
            self.surfaces[row["surfaceId"]] = row
            self.by_hash[row["surfaceHash"]] = row["surfaceId"]
            out.append(row)
        return out

    def require_surface(
        self,
        surface_id: str,
        *,
        tenant_id: str,
        engineering_hash: str | None = None,
        product_id: str | None = None,
        candidate_id: str | None = None,
        version: Any = None,
    ) -> dict[str, Any]:
        rec = self.surfaces.get(surface_id)
        if rec is None:
            raise ArtworkError("BLOCKED", "surface missing")
        if rec.get("tenantId") != tenant_id:
            raise ArtworkError("BLOCKED", "cross-tenant surface")
        if engineering_hash and rec.get("engineeringHash") != engineering_hash:
            raise ArtworkError("STALE", "stale engineeringHash")
        if product_id and rec.get("productId") != product_id:
            raise ArtworkError("BLOCKED", "cross-product surface")
        if candidate_id and rec.get("candidateId") not in {None, candidate_id}:
            raise ArtworkError("BLOCKED", "cross-candidate surface")
        if version is not None and rec.get("version") not in {None, version}:
            raise ArtworkError("BLOCKED", "cross-version surface")
        return rec

    def register_artwork(
        self,
        *,
        tenant_id: str,
        data: bytes,
        name: str = "artwork.png",
        source: str = "IMPORTED",
        mime: str = "image/png",
        color_space: str = "UNKNOWN",
        role: str = "ARTWORK",
    ) -> dict[str, Any]:
        if not data:
            raise ArtworkError("BLOCKED", "empty artwork bytes")
        digest = sha256_bytes(data)
        if mime == "image/png" and data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ArtworkError("BLOCKED", "MIME contradicts bytes")
        px_w, px_h = png_size(data)
        if mime == "image/png" and (not px_w or not px_h):
            raise ArtworkError("BLOCKED", "PNG size missing")
        obj = self.platform.dam.put(
            tenant_id=tenant_id,
            kind="artwork",
            name=name,
            data=data,
            metadata={"role": role, "mime": mime, "source": source, "sha256": digest, "size": len(data)},
        )
        if obj.sha256 != digest:
            raise ArtworkError("BLOCKED", "DAM hash mismatch")
        rec = {
            "artworkId": obj.asset_id,
            "tenantId": tenant_id,
            "assetId": obj.asset_id,
            "role": role,
            "source": source,
            "sha256": digest,
            "size": len(data),
            "mime": mime,
            "pixelWidth": px_w,
            "pixelHeight": px_h,
            "colorSpace": color_space if color_space else "UNKNOWN",
            "path": obj.path,
        }
        rec["artworkHash"] = stable_hash({k: rec[k] for k in rec if k not in {"artworkId", "path", "artworkHash"}})
        if rec["artworkId"] in self.artworks:
            raise ArtworkError("BLOCKED", "duplicate artworkId")
        self.artworks[rec["artworkId"]] = rec
        return rec

    def require_artwork(self, artwork_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.artworks.get(artwork_id)
        if rec is None:
            raise ArtworkError("BLOCKED", "artwork missing")
        if rec.get("tenantId") != tenant_id:
            raise ArtworkError("BLOCKED", "cross-tenant artwork")
        obj = self.platform.dam.get(rec["assetId"], tenant_id=tenant_id)
        live = Path(obj.path).read_bytes()
        if sha256_bytes(live) != rec.get("sha256") or len(live) != rec.get("size"):
            raise ArtworkError("BLOCKED", "artwork bytes/hash mismatch")
        if obj.sha256 != rec.get("sha256"):
            raise ArtworkError("BLOCKED", "artwork metadata/hash mismatch")
        return rec

    def place(
        self,
        *,
        tenant_id: str,
        surface_id: str,
        artwork_id: str,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        width_mm: float | None = None,
        height_mm: float | None = None,
        rotation_deg: float = 0.0,
        anchor: str = "BOTTOM_LEFT",
        fit: str = FIT_CONTAIN,
        protected_regions: list[dict[str, Any]] | None = None,
        engineering_hash: str | None = None,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        rot = _finite(rotation_deg, "rotationDeg")
        if not math.isfinite(rot):
            raise ArtworkError("BLOCKED", "non-finite rotation")
        if (rot % 360.0) not in {0.0, 90.0, 180.0, 270.0}:
            raise ArtworkError("BLOCKED", "unsupported rotation")
        surface = self.require_surface(surface_id, tenant_id=tenant_id, engineering_hash=engineering_hash, product_id=product_id)
        artwork = self.require_artwork(artwork_id, tenant_id=tenant_id)
        box_w = _finite(width_mm if width_mm is not None else surface["widthMm"], "widthMm", positive=True)
        box_h = _finite(height_mm if height_mm is not None else surface["heightMm"], "heightMm", positive=True)
        origin_x = _finite(x_mm, "xMm")
        origin_y = _finite(y_mm, "yMm")
        fitted = _fit_rect(
            box_w=box_w,
            box_h=box_h,
            art_w_px=artwork.get("pixelWidth"),
            art_h_px=artwork.get("pixelHeight"),
            fit=fit,
            anchor=anchor,
        )
        placed = {
            "xMm": origin_x + fitted["xMm"],
            "yMm": origin_y + fitted["yMm"],
            "widthMm": fitted["widthMm"],
            "heightMm": fitted["heightMm"],
        }
        crop = canonical_source_crop(
            pixel_width=artwork.get("pixelWidth"),
            pixel_height=artwork.get("pixelHeight"),
            box_w_mm=box_w,
            box_h_mm=box_h,
            placed=placed,
            fit=fit,
            anchor=anchor,
        )
        dpi = effective_dpi(
            artwork.get("pixelWidth"),
            placed["widthMm"],
            artwork.get("pixelHeight"),
            placed["heightMm"],
        )
        policy = evaluate_placement_policy(surface, placed, dpi=dpi, protected=protected_regions)
        if policy["blockers"]:
            raise ArtworkError("BLOCKED_PLACEMENT", "important region hits keep-out")
        rec = {
            "placementId": new_id(),
            "tenantId": tenant_id,
            "productId": surface["productId"],
            "candidateId": surface.get("candidateId"),
            "version": surface.get("version"),
            "objectName": surface.get("objectName") or surface.get("componentId"),
            "mirrored": bool(surface.get("mirrored")),
            "engineeringHash": surface["engineeringHash"],
            "surfaceId": surface["surfaceId"],
            "surfaceHash": surface["surfaceHash"],
            "artworkId": artwork["artworkId"],
            "artworkHash": artwork["artworkHash"],
            "xMm": placed["xMm"],
            "yMm": placed["yMm"],
            "widthMm": placed["widthMm"],
            "heightMm": placed["heightMm"],
            "rotationDeg": rot,
            "anchor": anchor,
            "fit": fit,
            "crop": crop,
            "protectedRegions": list(protected_regions or []),
            "dpi": dpi,
            "policy": policy,
            "uv": {
                "u0": mm_to_uv(placed["xMm"], placed["yMm"], surface)[0],
                "v0": mm_to_uv(placed["xMm"], placed["yMm"], surface)[1],
                "u1": mm_to_uv(placed["xMm"] + placed["widthMm"], placed["yMm"] + placed["heightMm"], surface)[0],
                "v1": mm_to_uv(placed["xMm"] + placed["widthMm"], placed["yMm"] + placed["heightMm"], surface)[1],
            },
            "componentId": surface.get("componentId"),
            "face": surface.get("face") or "FRONT",
            "relation": "SINGLE_SURFACE",
            "masterHash": None,
            "masterCropMm": None,
            "masterSurfaceIds": [],
            "masterId": None,
        }
        rec["placementHash"] = stable_hash(placement_payload(rec))
        if rec["placementId"] in self.placements:
            raise ArtworkError("BLOCKED", "duplicate placementId")
        self.placements[rec["placementId"]] = rec
        return rec

    def place_across_panels(
        self,
        *,
        tenant_id: str,
        artwork_id: str,
        surfaces: list[dict[str, Any]],
        engineering_hash: str,
        product_id: str,
        fit: str = FIT_COVER,
        seam_mm: float | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        if fit == FIT_STRETCH:
            raise ArtworkError("BLOCKED", "STRETCH is forbidden")
        by_id = {s["surfaceId"]: s for s in surfaces}
        if len(by_id) != len(surfaces):
            raise ArtworkError("BLOCKED", "duplicate surface in master")
        master = master_canvas(surfaces, seam_mm=seam_mm)
        crops = split_master(master)
        canonical_ids = [p["surfaceId"] for p in master["panels"]]
        relation = {
            "masterId": new_id(),
            "masterHash": master["masterHash"],
            "tenantId": master["tenantId"],
            "productId": master["productId"],
            "candidateId": master.get("candidateId"),
            "version": master.get("version"),
            "engineeringHash": master["engineeringHash"],
            "surfaceIds": list(canonical_ids),
            "panelOrder": [p.get("componentId") for p in master["panels"]],
            "widthMm": master["widthMm"],
            "heightMm": master["heightMm"],
            "seamMm": master["seamMm"],
            "seamSource": master.get("seamSource"),
            "cropGeometry": [c.get("cropMm") for c in crops],
        }
        relation["relationHash"] = master_relation_hash(relation)
        stored_master = self._store_master(relation)
        rows: list[dict[str, Any]] = []
        crop_by_sid = {c["surfaceId"]: c for c in crops}
        for panel in master["panels"]:
            surf = by_id.get(panel["surfaceId"])
            crop = crop_by_sid.get(panel["surfaceId"])
            if surf is None or crop is None:
                raise ArtworkError("BLOCKED", "master surface missing")
            rec = self.place(
                tenant_id=tenant_id,
                surface_id=surf["surfaceId"],
                artwork_id=artwork_id,
                engineering_hash=engineering_hash,
                product_id=product_id,
                x_mm=0.0,
                y_mm=0.0,
                width_mm=surf["widthMm"],
                height_mm=surf["heightMm"],
                fit=fit,
            )
            rec["relation"] = "MASTER_SPLIT"
            rec["masterHash"] = stored_master["masterHash"]
            rec["masterId"] = stored_master["masterId"]
            rec["masterCropMm"] = crop["cropMm"]
            rec["masterSurfaceIds"] = list(canonical_ids)
            rec["componentId"] = surf.get("componentId")
            rec["face"] = surf.get("face") or "FRONT"
            rec["objectName"] = surf.get("objectName") or surf.get("componentId")
            mw = _finite(master["widthMm"], "master width", positive=True)
            mh = _finite(master["heightMm"], "master height", positive=True)
            box = crop["cropMm"]
            rec["uv"] = {
                "u0": float(box["xMm"]) / mw,
                "v0": float(box["yMm"]) / mh,
                "u1": (float(box["xMm"]) + float(box["widthMm"])) / mw,
                "v1": (float(box["yMm"]) + float(box["heightMm"])) / mh,
            }
            rec["xMm"] = 0.0
            rec["yMm"] = 0.0
            rec["widthMm"] = surf["widthMm"]
            rec["heightMm"] = surf["heightMm"]
            rec["placementHash"] = stable_hash(placement_payload(rec))
            crop["placementHash"] = rec["placementHash"]
            self.placements[rec["placementId"]] = rec
            rows.append(rec)
        return master, crops, rows

    def _store_master(self, relation: dict[str, Any]) -> dict[str, Any]:
        key = relation.get("masterHash")
        if not key:
            raise ArtworkError("BLOCKED", "masterHash missing")
        existing = self.masters.get(key)
        if existing is None:
            self.masters[key] = dict(relation)
            return dict(self.masters[key])
        if existing.get("relationHash") != relation.get("relationHash") or existing.get("relationHash") != master_relation_hash(existing):
            raise ArtworkError("BLOCKED", "master relation collision")
        if existing.get("tenantId") != relation.get("tenantId"):
            raise ArtworkError("BLOCKED", "cross-tenant master")
        if existing.get("productId") != relation.get("productId"):
            raise ArtworkError("BLOCKED", "cross-product master")
        if existing.get("engineeringHash") != relation.get("engineeringHash"):
            raise ArtworkError("BLOCKED", "stale master engineeringHash")
        return dict(existing)

    def require_master(
        self,
        master_hash: str | None,
        *,
        tenant_id: str,
        product_id: str | None = None,
        engineering_hash: str | None = None,
        candidate_id: Any = None,
        version: Any = None,
    ) -> dict[str, Any]:
        if not master_hash:
            raise ArtworkError("BLOCKED", "masterHash missing")
        rec = self.masters.get(master_hash)
        if rec is None:
            raise ArtworkError("BLOCKED", "master relation missing")
        if rec.get("relationHash") != master_relation_hash(rec):
            raise ArtworkError("BLOCKED", "forged relationHash")
        if rec.get("tenantId") != tenant_id:
            raise ArtworkError("BLOCKED", "cross-tenant master")
        if product_id and rec.get("productId") != product_id:
            raise ArtworkError("BLOCKED", "cross-product master")
        if engineering_hash and rec.get("engineeringHash") != engineering_hash:
            raise ArtworkError("STALE", "stale master engineeringHash")
        if candidate_id not in {None, ""} and rec.get("candidateId") not in {None, candidate_id}:
            raise ArtworkError("BLOCKED", "cross-candidate master")
        if version is not None and rec.get("version") not in {None, version}:
            raise ArtworkError("BLOCKED", "cross-version master")
        return dict(rec)

    def applied_identity(self, rec: dict[str, Any]) -> dict[str, Any]:
        ident = final_uv_identity(
            placement_id=rec.get("placementId"),
            object_name=rec.get("objectName"),
            component_id=rec.get("componentId"),
            face=rec.get("face") or "FRONT",
            relation=rec.get("relation") or "SINGLE_SURFACE",
            uv_rect=rec.get("uv") or {},
            rotation_deg=rec.get("rotationDeg") or 0.0,
            mirrored=rec.get("mirrored"),
        )
        return {
            "placementId": rec.get("placementId"),
            "objectName": rec.get("objectName"),
            "componentId": rec.get("componentId"),
            "face": rec.get("face") or "FRONT",
            "relation": rec.get("relation") or "SINGLE_SURFACE",
            "engineeringHash": rec.get("engineeringHash"),
            "surfaceHash": rec.get("surfaceHash"),
            "artworkHash": rec.get("artworkHash"),
            "placementHash": rec.get("placementHash"),
            "finalUvHash": ident["finalUvHash"],
            "finalSampling": ident["finalSampling"],
            "uvRect": ident["uvRect"],
        }

    def _derive_uv(self, rec: dict[str, Any], surface: dict[str, Any]) -> dict[str, float]:
        if rec.get("relation") == "MASTER_SPLIT":
            master, crop = self._authoritative_master(rec, tenant_id=rec["tenantId"])
            mw = _finite(master["widthMm"], "master width", positive=True)
            mh = _finite(master["heightMm"], "master height", positive=True)
            box = crop["cropMm"]
            return {
                "u0": float(box["xMm"]) / mw,
                "v0": float(box["yMm"]) / mh,
                "u1": (float(box["xMm"]) + float(box["widthMm"])) / mw,
                "v1": (float(box["yMm"]) + float(box["heightMm"])) / mh,
            }
        u0, v0 = mm_to_uv(rec.get("xMm") or 0.0, rec.get("yMm") or 0.0, surface)
        u1, v1 = mm_to_uv(
            float(rec.get("xMm") or 0.0) + float(rec.get("widthMm") or surface["widthMm"]),
            float(rec.get("yMm") or 0.0) + float(rec.get("heightMm") or surface["heightMm"]),
            surface,
        )
        return {"u0": u0, "v0": v0, "u1": u1, "v1": v1}

    def require_placement(self, placement_id: str, *, tenant_id: str, engineering_hash: str | None = None) -> dict[str, Any]:
        rec = self.placements.get(placement_id)
        if rec is None:
            raise ArtworkError("BLOCKED", "placement missing")
        if rec.get("tenantId") != tenant_id:
            raise ArtworkError("BLOCKED", "cross-tenant placement")
        if engineering_hash and rec.get("engineeringHash") != engineering_hash:
            raise ArtworkError("STALE", "stale placement engineeringHash")
        live = self.require_surface(
            rec["surfaceId"],
            tenant_id=tenant_id,
            engineering_hash=engineering_hash or rec.get("engineeringHash"),
            product_id=rec.get("productId"),
            candidate_id=rec.get("candidateId"),
            version=rec.get("version"),
        )
        if live.get("surfaceHash") != rec.get("surfaceHash"):
            raise ArtworkError("STALE", "stale surfaceHash")
        art = self.require_artwork(rec["artworkId"], tenant_id=tenant_id)
        if art.get("artworkHash") != rec.get("artworkHash"):
            raise ArtworkError("STALE", "stale artworkHash")
        live_comp = live.get("componentId")
        live_obj = live.get("objectName") or live_comp
        stored_comp = rec.get("componentId")
        stored_obj = rec.get("objectName")
        if stored_comp not in {None, "", live_comp}:
            raise ArtworkError("BLOCKED", "forged componentId")
        if stored_obj not in {None, "", live_obj, live_comp}:
            raise ArtworkError("BLOCKED", "forged objectName")
        derived_uv = self._derive_uv(rec, live)
        stored_uv = rec.get("uv") if isinstance(rec.get("uv"), dict) else {}
        for key in ("u0", "v0", "u1", "v1"):
            if stored_uv.get(key) is not None and abs(float(stored_uv[key]) - float(derived_uv[key])) > 1e-6:
                raise ArtworkError("BLOCKED", "forged uv")
        recomputed = stable_hash(placement_payload({**rec, "uv": derived_uv, "surfaceHash": live["surfaceHash"]}))
        if recomputed != rec.get("placementHash"):
            raise ArtworkError("BLOCKED", "forged placementHash")
        out = dict(rec)
        out["uv"] = derived_uv
        out["objectName"] = live.get("objectName") or rec.get("objectName")
        out["componentId"] = live.get("componentId") or rec.get("componentId")
        out["face"] = live.get("face") or "FRONT"
        return out

    def _authoritative_master(self, placement: dict[str, Any], *, tenant_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if placement.get("relation") != "MASTER_SPLIT":
            raise ArtworkError("BLOCKED", "not a master split")
        rel = self.require_master(
            placement.get("masterHash"),
            tenant_id=tenant_id,
            product_id=placement.get("productId"),
            engineering_hash=placement.get("engineeringHash"),
            candidate_id=placement.get("candidateId"),
            version=placement.get("version"),
        )
        if not placement.get("masterId"):
            raise ArtworkError("BLOCKED", "masterId missing")
        if placement.get("masterId") != rel.get("masterId"):
            raise ArtworkError("BLOCKED", "forged masterId")
        ids = list(rel.get("surfaceIds") or [])
        if not ids:
            raise ArtworkError("BLOCKED", "masterSurfaceIds missing")
        stored_ids = list(placement.get("masterSurfaceIds") or [])
        if stored_ids != ids:
            raise ArtworkError("BLOCKED", "forged masterSurfaceIds")
        siblings = []
        for sid in ids:
            surf = self.surfaces.get(sid)
            if surf is None:
                raise ArtworkError("BLOCKED", "master surface missing")
            if surf.get("tenantId") != tenant_id:
                raise ArtworkError("BLOCKED", "cross-tenant surface")
            if surf.get("productId") != rel.get("productId"):
                raise ArtworkError("BLOCKED", "cross-product surface")
            if surf.get("engineeringHash") != rel.get("engineeringHash"):
                raise ArtworkError("STALE", "stale engineeringHash")
            siblings.append(surf)
        if rel.get("seamSource") == "CONFIG":
            master = master_canvas(siblings, seam_mm=float(rel.get("seamMm") or 0.0))
        else:
            master = master_canvas(siblings)
        if master.get("masterHash") != rel.get("masterHash"):
            raise ArtworkError("BLOCKED", "forged masterHash")
        if placement.get("masterHash") != master.get("masterHash"):
            raise ArtworkError("BLOCKED", "forged masterHash")
        if abs(float(master.get("seamMm") or 0) - float(rel.get("seamMm") or 0)) > MM_EPS:
            raise ArtworkError("BLOCKED", "forged seamMm")
        if [p.get("componentId") for p in master.get("panels") or []] != list(rel.get("panelOrder") or []):
            raise ArtworkError("BLOCKED", "forged panelOrder")
        if abs(float(master.get("widthMm") or 0) - float(rel.get("widthMm") or 0)) > MM_EPS:
            raise ArtworkError("BLOCKED", "forged master width")
        if abs(float(master.get("heightMm") or 0) - float(rel.get("heightMm") or 0)) > MM_EPS:
            raise ArtworkError("BLOCKED", "forged master height")
        crops = split_master(master)
        stored_geo = list(rel.get("cropGeometry") or [])
        if len(stored_geo) != len(crops):
            raise ArtworkError("BLOCKED", "forged cropGeometry")
        for got, want in zip(crops, stored_geo):
            box = got.get("cropMm") or {}
            for key in ("xMm", "yMm", "widthMm", "heightMm"):
                if abs(float(box.get(key) or 0) - float((want or {}).get(key) or 0)) > MM_EPS:
                    raise ArtworkError("BLOCKED", "forged cropGeometry")
        crop = next((c for c in crops if c.get("surfaceId") == placement.get("surfaceId")), None)
        if crop is None:
            raise ArtworkError("BLOCKED", "authoritative crop missing")
        return master, crop

    def produce_panel(
        self,
        *,
        tenant_id: str,
        placement_id: str,
        artwork_id: str | None = None,
        master: dict[str, Any] | None = None,
        crop: dict[str, Any] | None = None,
        placement_hash: str | None = None,
        engineering_hash: str | None = None,
        output_px_per_mm: float = 2.0,
    ) -> dict[str, Any]:
        rec = self.require_placement(placement_id, tenant_id=tenant_id, engineering_hash=engineering_hash)
        if placement_hash and placement_hash != rec.get("placementHash"):
            raise ArtworkError("BLOCKED", "forged placementHash")
        if artwork_id and artwork_id != rec.get("artworkId"):
            raise ArtworkError("BLOCKED", "forged artworkId")
        if engineering_hash and engineering_hash != rec.get("engineeringHash"):
            raise ArtworkError("STALE", "stale engineeringHash")
        surface = self.require_surface(
            rec["surfaceId"],
            tenant_id=tenant_id,
            engineering_hash=rec["engineeringHash"],
            product_id=rec.get("productId"),
            candidate_id=rec.get("candidateId"),
            version=rec.get("version"),
        )
        if surface.get("surfaceHash") != rec.get("surfaceHash"):
            raise ArtworkError("STALE", "stale surfaceHash")
        art = self.require_artwork(rec["artworkId"], tenant_id=tenant_id)
        data = Path(art["path"]).read_bytes()
        if sha256_bytes(data) != art["sha256"]:
            raise ArtworkError("BLOCKED", "tampered artwork bytes")
        src_w, src_h, rgb = decode_png_rgb(data)
        relation = rec.get("relation") or "SINGLE_SURFACE"
        if relation == "MASTER_SPLIT":
            auth_master, auth_crop = self._authoritative_master(rec, tenant_id=tenant_id)
            if rec.get("masterHash") and rec.get("masterHash") != auth_master.get("masterHash"):
                raise ArtworkError("BLOCKED", "forged masterHash")
            if master is not None and master.get("masterHash") not in {None, auth_master.get("masterHash")}:
                raise ArtworkError("BLOCKED", "forged master")
            box = auth_crop["cropMm"]
            if crop is not None:
                caller_box = crop.get("cropMm") if isinstance(crop.get("cropMm"), dict) else crop
                for key in ("xMm", "yMm", "widthMm", "heightMm"):
                    if caller_box.get(key) is not None and abs(float(caller_box[key]) - float(box[key])) > MM_EPS:
                        raise ArtworkError("BLOCKED", "forged crop")
                if crop.get("surfaceHash") and crop.get("surfaceHash") != surface.get("surfaceHash"):
                    raise ArtworkError("BLOCKED", "forged surfaceHash")
            master_w = _finite(auth_master["widthMm"], "master width", positive=True)
            master_h = _finite(auth_master["heightMm"], "master height", positive=True)
            x0 = int(round((_finite(box["xMm"], "crop x") / master_w) * src_w))
            y0 = int(round((1.0 - (_finite(box["yMm"], "crop y") + _finite(box["heightMm"], "crop h", positive=True)) / master_h) * src_h))
            w_px = max(1, int(round((_finite(box["widthMm"], "crop w", positive=True) / master_w) * src_w)))
            h_px = max(1, int(round((_finite(box["heightMm"], "crop h", positive=True) / master_h) * src_h)))
        elif relation == "SINGLE_SURFACE":
            if master is not None and master.get("masterHash"):
                raise ArtworkError("BLOCKED", "single-surface cannot use master")
            box = {"xMm": 0.0, "yMm": 0.0, "widthMm": surface["widthMm"], "heightMm": surface["heightMm"]}
            if crop is not None:
                caller_box = crop.get("cropMm") if isinstance(crop.get("cropMm"), dict) else crop
                for key in ("xMm", "yMm", "widthMm", "heightMm"):
                    if caller_box.get(key) is not None and abs(float(caller_box[key]) - float(box[key])) > MM_EPS:
                        raise ArtworkError("BLOCKED", "forged crop")
            placed = {
                "xMm": rec.get("xMm") or 0.0,
                "yMm": rec.get("yMm") or 0.0,
                "widthMm": rec.get("widthMm") or surface["widthMm"],
                "heightMm": rec.get("heightMm") or surface["heightMm"],
            }
            fit = str(rec.get("fit") or FIT_CONTAIN)
            fitted = _fit_rect(
                box_w=float(surface["widthMm"]),
                box_h=float(surface["heightMm"]),
                art_w_px=art.get("pixelWidth"),
                art_h_px=art.get("pixelHeight"),
                fit=fit,
                anchor=str(rec.get("anchor") or "BOTTOM_LEFT"),
            )
            for key in ("xMm", "yMm", "widthMm", "heightMm"):
                if abs(float(placed[key]) - float(fitted[key])) > MM_EPS:
                    raise ArtworkError("BLOCKED", "forged placement geometry")
            expected_crop = canonical_source_crop(
                pixel_width=art.get("pixelWidth"),
                pixel_height=art.get("pixelHeight"),
                box_w_mm=float(surface["widthMm"]),
                box_h_mm=float(surface["heightMm"]),
                placed=placed,
                fit=fit,
                anchor=str(rec.get("anchor") or "BOTTOM_LEFT"),
            )
            stored_crop = rec.get("crop") if isinstance(rec.get("crop"), dict) else None
            if not _source_crop_matches(stored_crop, expected_crop):
                raise ArtworkError("BLOCKED", "forged source crop")
            x0 = int(expected_crop.get("sourceXPx") or 0)
            y0 = int(expected_crop.get("sourceYPx") or 0)
            w_px = int(expected_crop.get("sourceWPx") or src_w)
            h_px = int(expected_crop.get("sourceHPx") or src_h)
            auth_master = {"widthMm": box["widthMm"], "heightMm": box["heightMm"], "masterHash": None}
            y0 = max(0, min(src_h - 1, y0))
            x0 = max(0, min(src_w - 1, x0))
            w_px = min(w_px, src_w - x0)
            h_px = min(h_px, src_h - y0)
            cropped = crop_rgb(rgb, src_w, src_h, x0, y0, w_px, h_px)
            oriented, ow, oh = orient_rgb(
                cropped,
                w_px,
                h_px,
                rotation_deg=float(rec.get("rotationDeg") or 0.0),
                mirrored=bool(rec.get("mirrored")),
            )
            canvas_w = max(1, int(round(_finite(surface["widthMm"], "w", positive=True) * output_px_per_mm)))
            canvas_h = max(1, int(round(_finite(surface["heightMm"], "h", positive=True) * output_px_per_mm)))
            if fit == FIT_COVER:
                panel_rgb = scale_rgb(oriented, ow, oh, canvas_w, canvas_h)
            else:
                dest_w = max(1, int(round(_finite(placed["widthMm"], "placed w", positive=True) * output_px_per_mm)))
                dest_h = max(1, int(round(_finite(placed["heightMm"], "placed h", positive=True) * output_px_per_mm)))
                scaled = scale_rgb(oriented, ow, oh, dest_w, dest_h)
                canvas = bytearray(canvas_w * canvas_h * 3)
                dx = int(round(float(placed["xMm"]) * output_px_per_mm))
                dy = int(round((float(surface["heightMm"]) - float(placed["yMm"]) - float(placed["heightMm"])) * output_px_per_mm))
                blit_rgb(canvas, canvas_w, canvas_h, scaled, dest_w, dest_h, dx, dy)
                panel_rgb = bytes(canvas)
            out_w, out_h = canvas_w, canvas_h
            ident = self.applied_identity(rec)
            xform = production_transform(rec=rec, surface=surface, source_crop=expected_crop, final_uv_hash=ident["finalUvHash"])
        else:
            raise ArtworkError("BLOCKED", "unknown placement relation")
        if relation == "MASTER_SPLIT":
            y0 = max(0, min(src_h - 1, y0))
            x0 = max(0, min(src_w - 1, x0))
            w_px = min(w_px, src_w - x0)
            h_px = min(h_px, src_h - y0)
            panel_rgb = crop_rgb(rgb, src_w, src_h, x0, y0, w_px, h_px)
            out_w, out_h = w_px, h_px
            xform = None
        dest = Path(self.platform.root) / "artwork-out" / f"{surface['surfaceId']}.png"
        write_png(dest, out_w, out_h, panel_rgb)
        raw = dest.read_bytes()
        digest = sha256_bytes(raw)
        obj = self.platform.dam.put(
            tenant_id=tenant_id,
            kind="production_artwork",
            name=f"{surface['componentId']}.png",
            data=raw,
            metadata={
                "role": "PRODUCTION_ARTWORK",
                "engineeringHash": rec["engineeringHash"],
                "surfaceHash": surface["surfaceHash"],
                "artworkHash": art["artworkHash"],
                "placementHash": rec["placementHash"],
                "masterHash": auth_master.get("masterHash"),
                "placementId": rec["placementId"],
            },
        )
        dpi = effective_dpi(out_w, float(box["widthMm"]), out_h, float(box["heightMm"]))
        policy = evaluate_placement_policy(surface, box, dpi=dpi)
        verified = (
            obj.sha256 == digest
            and rec.get("placementHash") == rec["placementHash"]
            and surface.get("surfaceHash") == rec.get("surfaceHash")
            and art.get("artworkHash") == rec.get("artworkHash")
        )
        manifest = {
            "tenantId": tenant_id,
            "productId": rec.get("productId"),
            "candidateId": rec.get("candidateId"),
            "version": rec.get("version"),
            "placementId": rec["placementId"],
            "engineeringHash": rec["engineeringHash"],
            "surfaceId": surface["surfaceId"],
            "surfaceHash": surface["surfaceHash"],
            "componentId": surface["componentId"],
            "artworkId": art["artworkId"],
            "masterArtworkHash": art["artworkHash"],
            "artworkHash": art["artworkHash"],
            "placementHash": rec["placementHash"],
            "masterHash": auth_master.get("masterHash"),
            "cropMm": box,
            "cropPx": {"x": x0, "y": y0, "w": w_px, "h": h_px},
            "outputPhysicalMm": {"widthMm": box["widthMm"], "heightMm": box["heightMm"]},
            "placedArtworkMm": None if xform is None else (xform.get("placedMm")),
            "rotationDeg": rec.get("rotationDeg") or 0.0,
            "mirrored": bool(rec.get("mirrored")),
            "anchor": rec.get("anchor"),
            "fit": rec.get("fit"),
            "background": None if xform is None else "BLACK",
            "transformHash": None if xform is None else xform.get("transformHash"),
            "finalUvHash": None if xform is None else xform.get("finalUvHash"),
            "canvasPx": {"w": out_w, "h": out_h},
            "bleedSafeKeepOut": policy,
            "pixelWidth": out_w,
            "pixelHeight": out_h,
            "effectiveDpi": dpi,
            "sha256": digest,
            "size": len(raw),
            "mime": "image/png",
            "assetId": obj.asset_id,
            "generatedAt": utcnow().isoformat(),
            "source": "GENERATED",
            "truthLabel": "REAL_LOGIC",
            "productionArtworkFileReady": bool(verified),
            "physicalPrintValidated": False,
            "printPreflight": "PARTIAL",
        }
        if not verified:
            raise ArtworkError("BLOCKED", "production hash mismatch")
        return manifest

    def blender_job_payload(
        self,
        *,
        tenant_id: str,
        engineering: dict[str, Any] | None = None,
        placements: list[dict[str, Any]] | None = None,
        placement_ids: list[str] | None = None,
        artwork_path: str | None = None,
    ) -> dict[str, Any]:
        ids = list(placement_ids or [])
        for rec in placements or []:
            pid = rec.get("placementId")
            if not pid:
                raise ArtworkError("BLOCKED", "placementId required")
            ids.append(str(pid))
        if not ids:
            raise ArtworkError("BLOCKED", "placement identity missing")
        items = []
        caller_by_id = {str(r.get("placementId")): r for r in (placements or []) if r.get("placementId")}
        eng = engineering
        for pid in ids:
            rec = self.require_placement(pid, tenant_id=tenant_id)
            caller = caller_by_id.get(str(pid)) or {}
            for key in ("artworkId", "productId", "engineeringHash"):
                if caller.get(key) not in {None, "", rec.get(key)}:
                    raise ArtworkError("BLOCKED", f"forged {key}")
            surface = self.require_surface(
                rec["surfaceId"],
                tenant_id=tenant_id,
                engineering_hash=rec.get("engineeringHash"),
                product_id=rec.get("productId"),
                candidate_id=rec.get("candidateId"),
                version=rec.get("version"),
            )
            uv = self._derive_uv(rec, surface)
            art = self.require_artwork(rec["artworkId"], tenant_id=tenant_id)
            canonical_path = str(art.get("path") or "")
            digest = str(art.get("sha256") or "")
            if not digest:
                raise ArtworkError("BLOCKED", "artwork sha256 missing")
            if artwork_path:
                override = Path(str(artwork_path))
                if not override.is_file() or sha256_bytes(override.read_bytes()) != digest:
                    raise ArtworkError("BLOCKED", "artwork path digest mismatch")
            path = canonical_path
            live_eng = self.engineering.get((tenant_id, rec.get("productId"), rec.get("engineeringHash")))
            if eng and eng.get("engineeringHash") not in {None, "", rec.get("engineeringHash")}:
                raise ArtworkError("BLOCKED", "forged engineeringHash")
            items.append(
                {
                    "objectName": rec.get("objectName") or surface.get("objectName") or surface.get("componentId"),
                    "imagePath": path,
                    "artworkSha256": digest,
                    "uvRect": uv,
                    "rotationDeg": rec.get("rotationDeg") or 0.0,
                    "mirrored": bool(rec.get("mirrored")),
                    "face": rec.get("face") or "FRONT",
                    "engineeringHash": rec.get("engineeringHash"),
                    "surfaceHash": rec.get("surfaceHash"),
                    "artworkHash": rec.get("artworkHash"),
                    "placementHash": rec.get("placementHash"),
                    "componentId": rec.get("componentId") or surface.get("componentId"),
                    "placementId": rec.get("placementId"),
                    "relation": rec.get("relation") or "SINGLE_SURFACE",
                }
            )
            if eng is None:
                eng = live_eng
        return {
            "tenantId": tenant_id,
            "engineering": eng or {},
            "artworkPlacements": items,
            "mode": "ARTWORK_PREVIEW",
        }

    def preview(
        self,
        *,
        tenant_id: str,
        placement: dict[str, Any],
        production: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not placement.get("placementId"):
            raise ArtworkError("BLOCKED", "placementId required")
        live = self.require_placement(placement["placementId"], tenant_id=tenant_id)
        for key in ("artworkId", "productId", "engineeringHash"):
            if placement.get(key) not in {None, "", live.get(key)}:
                raise ArtworkError("BLOCKED", f"forged {key}")
        hashes = {
            "engineeringHash": live.get("engineeringHash"),
            "surfaceHash": live.get("surfaceHash"),
            "artworkHash": live.get("artworkHash"),
            "placementHash": live.get("placementHash"),
        }
        requested = self.applied_identity(live)
        mock = bool(getattr(self.platform, "mock_blender", True))
        rec = {
            **hashes,
            "usedMock": mock,
            "realBlender": False,
            "realArtworkPreviewReady": False,
            "physicalPrintValidated": False,
            "label": "MOCK" if mock else "PARTIAL",
            "requestedIdentity": requested,
        }
        if production:
            for key in ("engineeringHash", "surfaceHash", "artworkHash", "placementHash"):
                if production.get(key) != hashes.get(key) and production.get(key) != hashes.get(key if key != "artworkHash" else "masterArtworkHash"):
                    if key == "artworkHash" and production.get("masterArtworkHash") == hashes.get("artworkHash"):
                        continue
                    raise ArtworkError("BLOCKED", "preview/production hash mismatch")
            rec["productionArtworkFileReady"] = True
        art = self.require_artwork(live["artworkId"], tenant_id=tenant_id)
        eng = self.engineering.get((tenant_id, live.get("productId"), live.get("engineeringHash")))
        payload = self.blender_job_payload(
            tenant_id=tenant_id,
            engineering=eng or {},
            placement_ids=[live["placementId"]],
        )
        rec["jobPayload"] = {
            "hasEngineering": bool(eng),
            "objectName": (payload.get("artworkPlacements") or [{}])[0].get("objectName"),
            "uvRect": (payload.get("artworkPlacements") or [{}])[0].get("uvRect"),
            "imagePath": (payload.get("artworkPlacements") or [{}])[0].get("imagePath"),
            "artworkSha256": (payload.get("artworkPlacements") or [{}])[0].get("artworkSha256"),
            "artworkId": live.get("artworkId"),
            "hashes": hashes,
        }
        if mock:
            rec["realArtworkPreviewReady"] = False
            rec["label"] = "MOCK"
            return rec
        if not eng or not payload.get("artworkPlacements"):
            rec["realArtworkPreviewReady"] = False
            rec["label"] = "BLOCKED_ENVIRONMENT"
            return rec
        try:
            done = self.platform.submit_job({**payload, "jobType": "BLENDER_RENDER", "tenantId": tenant_id}) if hasattr(self.platform, "submit_job") else None
            used_mock = bool((done or {}).get("usedMock") if isinstance(done, dict) else True)
            artifact = ((done or {}).get("output") or {}).get("beauty.png") if isinstance(done, dict) else None
            rec["usedMock"] = used_mock
            rec["realBlender"] = bool(isinstance(done, dict) and done.get("realBlender") and not used_mock)
            rec["jobId"] = done.get("jobId") if isinstance(done, dict) else None
            rec["blenderVersion"] = (done.get("blenderVersion") if isinstance(done, dict) else None)
            rec["device"] = (done.get("device") if isinstance(done, dict) else None) or ((done or {}).get("output") or {}).get("device")
            rec["artifact"] = artifact
            out = (done.get("output") if isinstance(done, dict) else None) or {}
            files = out.get("files") if isinstance(out, dict) and isinstance(out.get("files"), dict) else {}
            rec["outputHash"] = (done.get("outputHash") if isinstance(done, dict) else None) or files.get("beautyHash")
            rec["outputSize"] = (done.get("outputSize") if isinstance(done, dict) else None) or files.get("beautySize")
            rec["artworkApplied"] = done.get("artworkApplied") if isinstance(done, dict) else None
            rec["appliedPlacements"] = done.get("appliedPlacements") if isinstance(done, dict) else None
            gate = dict(done) if isinstance(done, dict) else None
            if isinstance(gate, dict):
                if not gate.get("device"):
                    gate["device"] = rec.get("device")
                if not gate.get("outputHash"):
                    gate["outputHash"] = rec.get("outputHash")
                if gate.get("outputSize") is None:
                    gate["outputSize"] = rec.get("outputSize")
            rec["realArtworkPreviewReady"] = preview_ready_from_job(gate, requested, mock=False)
            rec["label"] = "REAL" if rec["realArtworkPreviewReady"] else "BLOCKED_ENVIRONMENT"
        except Exception:
            rec["realArtworkPreviewReady"] = False
            rec["label"] = "BLOCKED_ENVIRONMENT"
        return rec


def preview_ready_from_job(done: dict[str, Any] | None, requested: dict[str, Any], *, mock: bool = False) -> bool:
    if mock or not isinstance(done, dict) or not isinstance(requested, dict):
        return False
    if done.get("usedMock"):
        return False
    if done.get("artworkApplied") is not True:
        return False
    if done.get("realBlender") is not True:
        return False
    if done.get("status") not in {"completed", "succeeded"}:
        return False
    if not done.get("blenderVersion") or not done.get("jobId"):
        return False
    device = done.get("device") or (done.get("output") if isinstance(done.get("output"), dict) else {}).get("device")
    if not device:
        return False
    sha, size = _job_artifact_meta(done)
    if not sha or size is None or size <= 0:
        return False
    applied = done.get("appliedPlacements")
    if not isinstance(applied, list) or not applied:
        output = done.get("output") if isinstance(done.get("output"), dict) else {}
        applied = output.get("appliedPlacements")
    if not isinstance(applied, list) or not applied:
        return False
    if any(not isinstance(r, dict) or r.get("applied") is not True for r in applied):
        return False
    want_list = requested.get("placements") if isinstance(requested.get("placements"), list) else [requested]
    if not want_list or any(not isinstance(w, dict) for w in want_list):
        return False
    for want in want_list:
        if any(want.get(k) in {None, ""} for k in _APPLIED_IDENTITY_KEYS):
            return False
    got = [_applied_identity(r) for r in applied]
    want = [_applied_identity(w) for w in want_list]
    if len(got) != len(want) or len(set(got)) != len(got) or set(got) != set(want):
        return False
    by_pid = {r.get("placementId"): r for r in applied if isinstance(r, dict)}
    if len(by_pid) != len(applied):
        return False
    for want_row in want_list:
        row = by_pid.get(want_row.get("placementId"))
        if row is None:
            return False
        if row.get("finalUvHash") != want_row.get("finalUvHash"):
            return False
        expected_sampling = want_row.get("finalSampling")
        if expected_sampling is not None:
            got_sampling = _norm_sampling(row.get("finalSampling") or row.get("corners"))
            if got_sampling != _norm_sampling(expected_sampling):
                return False
        for key in ("objectName", "componentId", "face", "relation"):
            if row.get(key) != want_row.get(key):
                return False
    return True


_REQUIRED_NEGATIVES = {
    "keepout": "BLOCKED_PLACEMENT",
    "stale": "STALE",
    "cross_tenant": "BLOCKED",
    "cross_product": "BLOCKED",
    "cross_version": "BLOCKED",
    "tamper": "BLOCKED",
    "stretch": "BLOCKED",
    "nan": "BLOCKED",
    "forged_production": "BLOCKED",
    "duplicate": "BLOCKED",
    "forged_preview_art": "BLOCKED",
    "forged_artwork_path": "BLOCKED",
    "master_relation": "BLOCKED",
    "missing_masterId": "BLOCKED",
}


def _tripled(value: Any, want: tuple[float, float, float]) -> bool:
    try:
        got = tuple(float(x) for x in (value or ()))
    except (TypeError, ValueError):
        return False
    return got == want


def _shader_identity(row: dict[str, Any]) -> bool:
    sm = row.get("shaderMapping") if isinstance(row.get("shaderMapping"), dict) else {}
    return (
        _tripled(sm.get("location"), (0.0, 0.0, 0.0))
        and _tripled(sm.get("scale"), (1.0, 1.0, 1.0))
        and _tripled(sm.get("rotation"), (0.0, 0.0, 0.0))
        and (row.get("finalSampling") or row.get("corners")) == row.get("corners")
    )


def validate_artwork_acceptance_result(result: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if result.get("physicalPrintValidated") is True:
        failures.append("physical_print")
    for flag in ("globalProductionReady", "fullAutonomousFactoryReady", "liveFactoryExecutionReady", "liveMachineControl"):
        if result.get(flag) not in {None, False}:
            failures.append(flag)
    if result.get("mockBlender") and result.get("realArtworkPreviewReady") is True:
        failures.append("mock_claimed_real_preview")
    scenarios = result.get("scenarios") if isinstance(result.get("scenarios"), dict) else {}
    if not scenarios:
        failures.append("scenarios_missing")
    negatives = result.get("negatives") if isinstance(result.get("negatives"), dict) else {}
    for key, want in _REQUIRED_NEGATIVES.items():
        got = negatives.get(key)
        if got != want:
            failures.append(f"negative_{key}")
    for n, name in ((2, "cabinet2"), (3, "cabinet3"), (4, "cabinet4")):
        row = scenarios.get(name) if isinstance(scenarios.get(name), dict) else {}
        crops = row.get("panelCrops") or []
        ids = row.get("surfaceIds") or []
        comps = row.get("componentIds") or []
        hashes = row.get("placementHashes") or []
        if len(crops) != n or len(ids) != n or len(set(ids)) != n:
            failures.append(f"split_{n}")
        if comps and (len(comps) != n or len(set(comps)) != n):
            failures.append(f"split_{n}_components")
        if hashes and (len(hashes) != n or len(set(hashes)) != n):
            failures.append("duplicate_placement" if n == 4 else f"split_{n}_placements")
        if crops:
            for i in range(1, len(crops)):
                prev = crops[i - 1]
                cur = crops[i]
                if abs(float(cur.get("xMm") or 0) - (float(prev.get("xMm") or 0) + float(prev.get("widthMm") or 0))) > MM_EPS:
                    failures.append(f"continuity_{name}")
    cab4 = scenarios.get("cabinet4") if isinstance(scenarios.get("cabinet4"), dict) else {}
    preview = result.get("preview") if isinstance(result.get("preview"), dict) else {}
    lineage = result.get("lineage") if isinstance(result.get("lineage"), dict) else {}
    for key in ("engineeringHash", "surfaceHash", "artworkHash", "placementHash"):
        if not lineage.get(key):
            failures.append(f"lineage_{key}")
        if preview.get(key) and preview.get(key) != lineage.get(key):
            failures.append(f"preview_lineage_{key}")
        prods = cab4.get("production") or []
        if prods and prods[0].get(key) not in {None, lineage.get(key)} and key != "artworkHash":
            if key == "placementHash" and prods[0].get("placementHash") not in (cab4.get("placementHashes") or []):
                failures.append("production_lineage_placement")
    applied = cab4.get("appliedUv") or []
    want_hashes = list(cab4.get("placementHashes") or [])
    if not applied:
        failures.append("applied_uv_missing")
    else:
        got_hashes = [a.get("placementHash") for a in applied if isinstance(a, dict)]
        if want_hashes and (set(got_hashes) != set(want_hashes) or len(got_hashes) != len(set(got_hashes))):
            failures.append("applied_set")
        ordered = sorted(
            [a for a in applied if isinstance(a, dict)],
            key=lambda a: float(((a.get("uvRect") or {}).get("u0") if isinstance(a.get("uvRect"), dict) else 0) or 0),
        )
        if len(ordered) == 4:
            got_u = []
            for row in ordered:
                rect = row.get("uvRect") if isinstance(row.get("uvRect"), dict) else {}
                try:
                    got_u.append((round(float(rect["u0"]), 6), round(float(rect["u1"]), 6)))
                except (KeyError, TypeError, ValueError):
                    got_u.append(None)
            if got_u != [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0)]:
                failures.append("wrong_final_uv")
        for row in applied:
            if not isinstance(row, dict) or row.get("applied") is not True:
                failures.append("applied_false")
                continue
            if not _shader_identity(row):
                failures.append("double_uv")
    single = scenarios.get("cabinet4Single") if isinstance(scenarios.get("cabinet4Single"), dict) else {}
    if single:
        if single.get("relation") != "SINGLE_SURFACE":
            failures.append("single_relation")
        if single.get("masterHash") not in {None, ""}:
            failures.append("single_master")
        crop = single.get("cropPx") if isinstance(single.get("cropPx"), dict) else {}
        if int(crop.get("x") or 0) != 0:
            failures.append("single_quarter")
        out_mm = single.get("outputPhysicalMm") if isinstance(single.get("outputPhysicalMm"), dict) else {}
        if out_mm and float(out_mm.get("widthMm") or 0) <= 0:
            failures.append("single_physical")
    contain = scenarios.get("containCenter") if isinstance(scenarios.get("containCenter"), dict) else {}
    if contain:
        placed = contain.get("placedMm") if isinstance(contain.get("placedMm"), dict) else {}
        canvas = contain.get("outputPhysicalMm") if isinstance(contain.get("outputPhysicalMm"), dict) else {}
        if float(placed.get("heightMm") or 0) <= 0 or float(canvas.get("heightMm") or 0) <= float(placed.get("heightMm") or 0):
            failures.append("contain_letterbox")
        if not contain.get("transformHash") or not contain.get("finalUvHash"):
            failures.append("contain_transform")
        if int(contain.get("pixelWidth") or 0) <= int(placed.get("widthMm") or 0):
            failures.append("contain_canvas")
    cover = scenarios.get("coverAnchor") if isinstance(scenarios.get("coverAnchor"), dict) else {}
    if cover and int(cover.get("leftSourceXPx") or 0) >= int(cover.get("rightSourceXPx") or 0):
        failures.append("cover_anchor")
    rotp = scenarios.get("rotationParity") if isinstance(scenarios.get("rotationParity"), dict) else {}
    if rotp and (float(rotp.get("rotationDeg") or 0) != 90.0 or not rotp.get("finalUvHash")):
        failures.append("rotation_parity")
    seam = scenarios.get("masterSeam") if isinstance(scenarios.get("masterSeam"), dict) else {}
    if seam and (abs(float(seam.get("seamMm") or 0) - 25.0) > MM_EPS or seam.get("ready") is not True):
        failures.append("master_seam")
    if preview.get("status") in {"completed", "succeeded"} or preview.get("realBlender") is True:
        if preview.get("artworkApplied") is not True:
            failures.append("preview_missing_artworkApplied")
    if result.get("realArtworkPreviewReady") is True and preview.get("artworkApplied") is not True:
        failures.append("preview_missing_artworkApplied")
    if result.get("mockBlender") and result.get("realArtworkPreviewReady"):
        failures.append("mock_real_preview")
    if result.get("surfaceDecorationLogicReady") is not True:
        failures.append("surfaceDecorationLogicReady")
    if result.get("productionArtworkFileReady") is not True:
        failures.append("productionArtworkFileReady")
    if not (cab4.get("blenderDoors") or cab4.get("doorLayout")):
        failures.append("blender_door_layout")
    return failures


def run_artwork_scenario(plat: Any, *, tenant_a: str = "aw-a", tenant_b: str = "aw-b") -> dict[str, Any]:
    from fox3d.parametric import CabinetEngine
    from fox3d.acrylic import acrylic_parts
    from fox3d.ids import stable_hash as _h

    factory = plat.artwork
    engine = CabinetEngine()
    cab2, _rep = engine.create("STORAGE_CABINET", tenant_id=tenant_a, width=800, height=1800, doorCount=2, shelfCount=2)
    cab4, _r4 = engine.create("STORAGE_CABINET", tenant_id=tenant_a, width=2400, height=1800, doorCount=4, shelfCount=1)
    desk, _rd = engine.create("STUDENT_DESK", tenant_id=tenant_a, width=1200, height=750, depth=600)
    retail, _rr = engine.create("RETAIL_DISPLAY", tenant_id=tenant_a, width=600, height=1600, depth=400)
    acr_parts = acrylic_parts("MENU_STAND", width=210, height=297, depth=80, thickness=5)
    acr = {
        "tenantId": tenant_a,
        "productId": new_id(),
        "kind": "MENU_STAND",
        "engineeringHash": _h({"kind": "MENU_STAND", "parts": acr_parts}),
        "components": [{**p, "role": "face" if p["partId"] == "face" else p["partId"]} for p in acr_parts],
    }
    pkg = {
        "tenantId": tenant_a,
        "productId": new_id(),
        "kind": "PACKAGING",
        "engineeringHash": _h({"pkg": "BOX", "w": 120, "h": 160}),
        "dieline": {"panels": [{"id": "FRONT", "w": 120, "h": 160}]},
        "components": [],
    }
    cab3, _r3 = engine.create("STORAGE_CABINET", tenant_id=tenant_a, width=1800, height=1800, doorCount=3, shelfCount=1)
    s2 = factory.register_surfaces(cab2, tenant_id=tenant_a)
    s4 = factory.register_surfaces(cab4, tenant_id=tenant_a)
    s3 = factory.register_surfaces(cab3, tenant_id=tenant_a)
    s_desk = factory.register_surfaces(desk, tenant_id=tenant_a)
    s_retail = factory.register_surfaces(retail, tenant_id=tenant_a)
    s_acr = factory.register_surfaces(acr, tenant_id=tenant_a)
    s_pkg = factory.register_surfaces(pkg, tenant_id=tenant_a, family="PACKAGING")
    doors2 = [s for s in s2 if str(s["componentId"]).upper().startswith("DOOR")]
    doors3 = [s for s in s3 if str(s["componentId"]).upper().startswith("DOOR")]
    doors4 = [s for s in s4 if str(s["componentId"]).upper().startswith("DOOR")]
    doors2.sort(key=lambda s: float((s.get("origin") or {}).get("xMm") or 0))
    doors3.sort(key=lambda s: float((s.get("origin") or {}).get("xMm") or 0))
    doors4.sort(key=lambda s: float((s.get("origin") or {}).get("xMm") or 0))
    grid = checkerboard_rgb(480, 360, cell=24)
    path = Path(plat.root) / "fixture-art.png"
    write_png(path, 480, 360, grid)
    art = factory.register_artwork(tenant_id=tenant_a, data=path.read_bytes(), name="grid.png", source="GENERATED")
    master4, crops4, places4 = factory.place_across_panels(
        tenant_id=tenant_a,
        artwork_id=art["artworkId"],
        surfaces=doors4,
        engineering_hash=cab4.engineering_hash(),
        product_id=cab4.productId,
        fit=FIT_COVER,
    )
    master3, crops3, places3 = factory.place_across_panels(
        tenant_id=tenant_a,
        artwork_id=art["artworkId"],
        surfaces=doors3,
        engineering_hash=cab3.engineering_hash(),
        product_id=cab3.productId,
        fit=FIT_COVER,
    )
    productions = [
        factory.produce_panel(
            tenant_id=tenant_a,
            placement_id=place["placementId"],
            artwork_id=art["artworkId"],
            master=master4,
            crop=crop,
            placement_hash=place["placementHash"],
            engineering_hash=cab4.engineering_hash(),
        )
        for place, crop in zip(places4, crops4)
    ]
    single_place = factory.place(
        tenant_id=tenant_a,
        surface_id=doors4[1]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab4.engineering_hash(),
        product_id=cab4.productId,
        fit=FIT_CONTAIN,
    )
    single_prod = factory.produce_panel(
        tenant_id=tenant_a,
        placement_id=single_place["placementId"],
        artwork_id=art["artworkId"],
        placement_hash=single_place["placementHash"],
        engineering_hash=cab4.engineering_hash(),
    )
    master2, crops2, places2 = factory.place_across_panels(
        tenant_id=tenant_a,
        artwork_id=art["artworkId"],
        surfaces=doors2,
        engineering_hash=cab2.engineering_hash(),
        product_id=cab2.productId,
        fit=FIT_CONTAIN,
    )
    place2 = places2[0]
    preview = factory.preview(tenant_id=tenant_a, placement=places4[0], production=productions[0])
    negatives: dict[str, str] = {}
    try:
        factory.place(
            tenant_id=tenant_a,
            surface_id=doors2[0]["surfaceId"],
            artwork_id=art["artworkId"],
            engineering_hash=cab2.engineering_hash(),
            product_id=cab2.productId,
            protected_regions=[{"xMm": doors2[0]["keepOuts"][0]["xMm"], "yMm": doors2[0]["keepOuts"][0]["yMm"], "widthMm": 30, "heightMm": 40, "source": "IMPORTED"}],
        )
        negatives["keepout"] = "passed"
    except ArtworkError as exc:
        negatives["keepout"] = exc.code
    tiny = factory.register_artwork(tenant_id=tenant_a, data=_tiny_png(), name="tiny.png", source="GENERATED")
    low = factory.place(
        tenant_id=tenant_a,
        surface_id=doors2[1]["surfaceId"],
        artwork_id=tiny["artworkId"],
        engineering_hash=cab2.engineering_hash(),
        product_id=cab2.productId,
        width_mm=doors2[1]["widthMm"],
        height_mm=doors2[1]["heightMm"],
    )
    resized, _ = engine.resize(cab4, width=2000)
    try:
        factory.require_placement(places4[0]["placementId"], tenant_id=tenant_a, engineering_hash=resized.engineering_hash())
        negatives["stale"] = "passed"
    except ArtworkError as exc:
        negatives["stale"] = exc.code
    try:
        factory.require_artwork(art["artworkId"], tenant_id=tenant_b)
        negatives["cross_tenant"] = "passed"
    except (ArtworkError, PermissionError):
        negatives["cross_tenant"] = "BLOCKED"
    try:
        factory.place(
            tenant_id=tenant_a,
            surface_id=doors4[0]["surfaceId"],
            artwork_id=art["artworkId"],
            engineering_hash=cab4.engineering_hash(),
            product_id=cab2.productId,
        )
        negatives["cross_product"] = "passed"
    except ArtworkError as exc:
        negatives["cross_product"] = exc.code
    tampered = Path(art["path"])
    original = tampered.read_bytes()
    tampered.write_bytes(original[:-8] + b"xxxxxxxx")
    try:
        factory.require_artwork(art["artworkId"], tenant_id=tenant_a)
        negatives["tamper"] = "passed"
    except ArtworkError as exc:
        negatives["tamper"] = exc.code
    tampered.write_bytes(original)
    try:
        split_master(master4, stretch=True)
        negatives["stretch"] = "passed"
    except ArtworkError as exc:
        negatives["stretch"] = exc.code
    try:
        mm_to_uv(float("nan"), 0, doors2[0])
        negatives["nan"] = "passed"
    except ArtworkError as exc:
        negatives["nan"] = exc.code
    try:
        factory.require_surface(doors4[0]["surfaceId"], tenant_id=tenant_a, version="other")
        negatives["cross_version"] = "passed"
    except ArtworkError as exc:
        negatives["cross_version"] = exc.code
    try:
        factory.produce_panel(
            tenant_id=tenant_a,
            placement_id=places4[0]["placementId"],
            placement_hash=places4[0]["placementHash"],
            engineering_hash=cab4.engineering_hash(),
            crop={"cropMm": {"xMm": 99.0, "yMm": 0.0, "widthMm": 10.0, "heightMm": 10.0}, "surfaceHash": places4[0]["surfaceHash"]},
            master={"masterHash": master4["masterHash"], "widthMm": master4["widthMm"], "heightMm": master4["heightMm"]},
        )
        negatives["forged_production"] = "passed"
    except ArtworkError:
        negatives["forged_production"] = "BLOCKED"
    try:
        factory.register_surfaces(cab4, tenant_id=tenant_a)
        negatives["duplicate"] = "passed"
    except ArtworkError:
        negatives["duplicate"] = "BLOCKED"
    other_art = factory.register_artwork(tenant_id=tenant_a, data=_tiny_png(), name="other.png", source="GENERATED")
    try:
        factory.preview(tenant_id=tenant_a, placement={**places4[0], "artworkId": other_art["artworkId"]})
        negatives["forged_preview_art"] = "passed"
    except ArtworkError:
        negatives["forged_preview_art"] = "BLOCKED"
    try:
        factory.blender_job_payload(
            tenant_id=tenant_a,
            placement_ids=[places4[0]["placementId"]],
            artwork_path=str(other_art["path"]),
        )
        negatives["forged_artwork_path"] = "passed"
    except ArtworkError:
        negatives["forged_artwork_path"] = "BLOCKED"
    rel_row = factory.masters.get(master4["masterHash"])
    if rel_row is not None:
        orig_seam = rel_row.get("seamMm")
        rel_row["seamMm"] = float(orig_seam or 0) + 17.0
        try:
            factory.require_placement(places4[0]["placementId"], tenant_id=tenant_a)
            negatives["master_relation"] = "passed"
        except ArtworkError:
            negatives["master_relation"] = "BLOCKED"
        rel_row["seamMm"] = orig_seam
    else:
        negatives["master_relation"] = "BLOCKED"
    rec_mid = factory.placements[places4[2]["placementId"]]
    orig_mid = rec_mid.get("masterId")
    rec_mid["masterId"] = ""
    rec_mid["placementHash"] = stable_hash(placement_payload(rec_mid))
    try:
        factory.require_placement(places4[2]["placementId"], tenant_id=tenant_a)
        negatives["missing_masterId"] = "passed"
    except ArtworkError:
        negatives["missing_masterId"] = "BLOCKED"
    rec_mid["masterId"] = orig_mid
    rec_mid["placementHash"] = stable_hash(placement_payload(rec_mid))
    contain_center = factory.place(
        tenant_id=tenant_a,
        surface_id=doors4[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab4.engineering_hash(),
        product_id=cab4.productId,
        fit=FIT_CONTAIN,
        anchor="CENTER",
    )
    contain_prod = factory.produce_panel(
        tenant_id=tenant_a,
        placement_id=contain_center["placementId"],
        placement_hash=contain_center["placementHash"],
        engineering_hash=cab4.engineering_hash(),
    )
    cover_left = factory.place(
        tenant_id=tenant_a,
        surface_id=doors4[2]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab4.engineering_hash(),
        product_id=cab4.productId,
        fit=FIT_COVER,
        anchor="BOTTOM_LEFT",
    )
    cover_right = factory.place(
        tenant_id=tenant_a,
        surface_id=doors4[2]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab4.engineering_hash(),
        product_id=cab4.productId,
        fit=FIT_COVER,
        anchor="BOTTOM_RIGHT",
    )
    rot_place = factory.place(
        tenant_id=tenant_a,
        surface_id=doors4[3]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab4.engineering_hash(),
        product_id=cab4.productId,
        fit=FIT_CONTAIN,
        anchor="CENTER",
        rotation_deg=90,
    )
    rot_prod = factory.produce_panel(
        tenant_id=tenant_a,
        placement_id=rot_place["placementId"],
        placement_hash=rot_place["placementHash"],
        engineering_hash=cab4.engineering_hash(),
    )
    seam_master, _seam_crops, seam_places = factory.place_across_panels(
        tenant_id=tenant_a,
        artwork_id=art["artworkId"],
        surfaces=doors2,
        engineering_hash=cab2.engineering_hash(),
        product_id=cab2.productId,
        seam_mm=25.0,
    )
    seam_prod = factory.produce_panel(
        tenant_id=tenant_a,
        placement_id=seam_places[0]["placementId"],
        placement_hash=seam_places[0]["placementHash"],
        engineering_hash=cab2.engineering_hash(),
    )
    bj_path = Path(__file__).resolve().parents[2] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("fox3d_blender_job_art", bj_path)
    bj = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bj)
    door_layout = bj.door_layout_from_engineering(cab4.model_dump(mode="json"))
    payload = factory.blender_job_payload(
        tenant_id=tenant_a,
        engineering=cab4.model_dump(mode="json"),
        placements=places4,
        artwork_path=str(path),
    )
    applied = bj.apply_canonical_artwork({p["objectName"]: {} for p in payload["artworkPlacements"]}, payload)
    ordered_uv = sorted(applied, key=lambda a: float((a.get("uvRect") or {}).get("u0") or 0))
    got_u = [(round(float(a["uvRect"]["u0"]), 6), round(float(a["uvRect"]["u1"]), 6)) for a in ordered_uv]
    split_w = int((productions[1].get("cropPx") or {}).get("w") or 0)
    single_w = int((single_prod.get("cropPx") or {}).get("w") or 0)
    logic_ok = (
        len(doors2) == 2
        and len(doors3) == 3
        and len(doors4) == 4
        and len(productions) == 4
        and all(p.get("productionArtworkFileReady") for p in productions)
        and applied
        and all(a.get("applied") is True for a in applied)
        and all(_shader_identity(a) for a in applied)
        and got_u == [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0)]
        and all(p.get("relation") == "MASTER_SPLIT" for p in places4)
        and single_place.get("relation") == "SINGLE_SURFACE"
        and single_prod.get("masterHash") in {None, ""}
        and int((single_prod.get("cropPx") or {}).get("x") or 0) == 0
        and single_w >= max(2 * split_w, 1)
        and len(door_layout) == 4
        and all(abs(door_layout[i]["widthMm"] - doors4[i]["widthMm"]) < MM_EPS for i in range(4))
        and abs(float((contain_prod.get("outputPhysicalMm") or {}).get("widthMm") or 0) - float(doors4[0]["widthMm"])) < MM_EPS
        and contain_prod.get("canvasPx", {}).get("w") == contain_prod.get("pixelWidth")
        and float((contain_prod.get("placedArtworkMm") or {}).get("heightMm") or 0) < float(doors4[0]["heightMm"])
        and int((cover_left.get("crop") or {}).get("sourceXPx") or 0) < int((cover_right.get("crop") or {}).get("sourceXPx") or 0)
        and rot_prod.get("rotationDeg") == 90.0
        and rot_prod.get("finalUvHash")
        and abs(float(seam_master.get("seamMm") or 0) - 25.0) < MM_EPS
        and seam_prod.get("productionArtworkFileReady") is True
        and all(row.get("artworkSha256") for row in payload.get("artworkPlacements") or [])
    )
    mock = bool(getattr(plat, "mock_blender", True))
    result = {
        "ok": False,
        "label": "FIXTURE/REAL_LOGIC",
        "surfaceDecorationLogicReady": False,
        "productionArtworkFileReady": False,
        "realArtworkPreviewReady": bool(preview.get("realArtworkPreviewReady")) and not mock,
        "physicalPrintValidated": False,
        "artworkContentAwarePlacementReady": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveMachineControl": False,
        "mockBlender": mock,
        "demandLabel": "MOCK",
        "printPreflight": "PARTIAL",
        "scenarios": {
            "cabinet2": {
                "surfaceIds": [d["surfaceId"] for d in doors2],
                "componentIds": [d["componentId"] for d in doors2],
                "panelCrops": [c["cropMm"] for c in crops2],
                "placementHash": place2["placementHash"],
                "placementHashes": [p["placementHash"] for p in places2],
            },
            "cabinet3": {
                "surfaceIds": [d["surfaceId"] for d in doors3],
                "componentIds": [d["componentId"] for d in doors3],
                "panelCrops": [c["cropMm"] for c in crops3],
                "placementHashes": [p["placementHash"] for p in places3],
            },
            "cabinet4": {
                "masterHash": master4["masterHash"],
                "widthMm": master4["widthMm"],
                "seamSource": master4.get("seamSource"),
                "surfaceIds": [d["surfaceId"] for d in doors4],
                "componentIds": [d["componentId"] for d in doors4],
                "panelCrops": [c["cropMm"] for c in crops4],
                "placementHashes": [p["placementHash"] for p in places4],
                "production": [
                    {
                        "sha256": p["sha256"],
                        "placementHash": p["placementHash"],
                        "surfaceHash": p["surfaceHash"],
                        "engineeringHash": p["engineeringHash"],
                        "artworkHash": p.get("artworkHash") or p.get("masterArtworkHash"),
                        "productionArtworkFileReady": p.get("productionArtworkFileReady"),
                    }
                    for p in productions
                ],
                "doorLayout": door_layout,
                "blenderDoors": [{"widthMm": d["widthMm"], "heightMm": d["heightMm"], "name": d["name"]} for d in door_layout],
                "appliedUv": applied,
            },
            "cabinet4Single": {
                "relation": single_place.get("relation"),
                "componentId": single_place.get("componentId") or doors4[1]["componentId"],
                "surfaceId": doors4[1]["surfaceId"],
                "masterHash": single_prod.get("masterHash"),
                "cropPx": single_prod.get("cropPx"),
                "placementHash": single_place.get("placementHash"),
                "outputPhysicalMm": single_prod.get("outputPhysicalMm"),
                "canvasPx": single_prod.get("canvasPx"),
            },
            "containCenter": {
                "anchor": contain_center.get("anchor"),
                "fit": contain_center.get("fit"),
                "placedMm": contain_prod.get("placedArtworkMm"),
                "outputPhysicalMm": contain_prod.get("outputPhysicalMm"),
                "pixelWidth": contain_prod.get("pixelWidth"),
                "pixelHeight": contain_prod.get("pixelHeight"),
                "transformHash": contain_prod.get("transformHash"),
                "finalUvHash": contain_prod.get("finalUvHash"),
            },
            "coverAnchor": {
                "leftSourceXPx": (cover_left.get("crop") or {}).get("sourceXPx"),
                "rightSourceXPx": (cover_right.get("crop") or {}).get("sourceXPx"),
            },
            "rotationParity": {
                "rotationDeg": rot_prod.get("rotationDeg"),
                "finalUvHash": rot_prod.get("finalUvHash"),
                "transformHash": rot_prod.get("transformHash"),
            },
            "masterSeam": {
                "seamMm": seam_master.get("seamMm"),
                "seamSource": seam_master.get("seamSource"),
                "ready": seam_prod.get("productionArtworkFileReady"),
            },
            "desk": {"surfaceIds": [s["surfaceId"] for s in s_desk]},
            "retail": {"surfaceIds": [s["surfaceId"] for s in s_retail]},
            "acrylic": {"surfaceIds": [s["surfaceId"] for s in s_acr]},
            "packaging": {"surfaceIds": [s["surfaceId"] for s in s_pkg]},
        },
        "preview": preview,
        "negatives": negatives,
        "lineage": {
            "engineeringHash": cab4.engineering_hash(),
            "surfaceHash": doors4[0]["surfaceHash"],
            "artworkHash": art["artworkHash"],
            "placementHash": places4[0]["placementHash"],
        },
    }
    if mock:
        result["realArtworkPreviewReady"] = False
    result["surfaceDecorationLogicReady"] = bool(logic_ok)
    result["productionArtworkFileReady"] = bool(logic_ok and all(p.get("productionArtworkFileReady") for p in productions))
    result["ok"] = not validate_artwork_acceptance_result(result)
    return result


def _tiny_png() -> bytes:
    rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])
    dest = Path("/tmp")
    # write via helper into bytes using a temp in-memory path through write_png
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as td:
        p = Path(td) / "t.png"
        write_png(p, 2, 2, rgb)
        return p.read_bytes()
