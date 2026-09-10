"""Artwork Placement / Surface Decoration Engine V1.

Printable surfaces and millimetre placements are derived from existing
Engineering Definition. Blender and production files consume the same
placementHash. FIXTURE/REAL_LOGIC — not physical print, not Production Ready.
"""

from __future__ import annotations

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
            "face": "FRONT",
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


def effective_dpi(pixel_w: int | None, placed_width_mm: float) -> float | None:
    if not pixel_w or placed_width_mm <= 0:
        return None
    inches = placed_width_mm / 25.4
    if inches <= 0:
        return None
    return float(pixel_w) / inches


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
        "engineeringHash": row.get("engineeringHash"),
    }


def master_canvas(surfaces: list[dict[str, Any]], *, seam_mm: float | None = None) -> dict[str, Any]:
    if not surfaces:
        raise ArtworkError("BLOCKED", "master canvas requires surfaces")
    tenant = surfaces[0]["tenantId"]
    product = surfaces[0]["productId"]
    eng = surfaces[0]["engineeringHash"]
    ordered = list(surfaces)
    seam = 0.0 if seam_mm is None else _finite(seam_mm, "seamMm")
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
        "seamSource": "ENGINEERING" if seam_mm is None else "CONFIG",
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

    def register_surfaces(self, spec: Any, *, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        rows = derive_printable_surfaces(spec, tenant_id=tenant_id, **kwargs)
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

    def require_surface(self, surface_id: str, *, tenant_id: str, engineering_hash: str | None = None, product_id: str | None = None) -> dict[str, Any]:
        rec = self.surfaces.get(surface_id)
        if rec is None:
            raise ArtworkError("BLOCKED", "surface missing")
        if rec.get("tenantId") != tenant_id:
            raise ArtworkError("BLOCKED", "cross-tenant surface")
        if engineering_hash and rec.get("engineeringHash") != engineering_hash:
            raise ArtworkError("STALE", "stale engineeringHash")
        if product_id and rec.get("productId") != product_id:
            raise ArtworkError("BLOCKED", "cross-product surface")
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
        px_w, px_h = png_size(data)
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
        crop = {
            "xMm": 0.0,
            "yMm": 0.0,
            "widthMm": placed["widthMm"],
            "heightMm": placed["heightMm"],
            "fit": fit,
        }
        if fit == FIT_COVER and artwork.get("pixelWidth") and artwork.get("pixelHeight"):
            scale = artwork["pixelWidth"] / placed["widthMm"]
            src_w = min(artwork["pixelWidth"], int(round(box_w * scale)))
            src_h = min(artwork["pixelHeight"], int(round(box_h * scale)))
            src_x = max(0, (artwork["pixelWidth"] - src_w) // 2)
            src_y = max(0, (artwork["pixelHeight"] - src_h) // 2)
            crop.update({"sourceXPx": src_x, "sourceYPx": src_y, "sourceWPx": src_w, "sourceHPx": src_h})
        elif artwork.get("pixelWidth") and artwork.get("pixelHeight"):
            crop.update(
                {
                    "sourceXPx": 0,
                    "sourceYPx": 0,
                    "sourceWPx": artwork["pixelWidth"],
                    "sourceHPx": artwork["pixelHeight"],
                }
            )
        dpi = effective_dpi(artwork.get("pixelWidth"), placed["widthMm"])
        policy = evaluate_placement_policy(surface, placed, dpi=dpi, protected=protected_regions)
        if policy["blockers"]:
            raise ArtworkError("BLOCKED_PLACEMENT", "important region hits keep-out")
        rec = {
            "placementId": new_id(),
            "tenantId": tenant_id,
            "productId": surface["productId"],
            "candidateId": surface.get("candidateId"),
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
        master = master_canvas(surfaces, seam_mm=seam_mm)
        crops = split_master(master)
        rows: list[dict[str, Any]] = []
        for surf, crop in zip(surfaces, crops):
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
            rec["masterHash"] = master["masterHash"]
            rec["masterCropMm"] = crop["cropMm"]
            rec["placementHash"] = stable_hash(placement_payload(rec) | {"masterHash": rec["masterHash"], "masterCropMm": rec["masterCropMm"]})
            crop["placementHash"] = rec["placementHash"]
            self.placements[rec["placementId"]] = rec
            rows.append(rec)
        return master, crops, rows

    def require_placement(self, placement_id: str, *, tenant_id: str, engineering_hash: str | None = None) -> dict[str, Any]:
        rec = self.placements.get(placement_id)
        if rec is None:
            raise ArtworkError("BLOCKED", "placement missing")
        if rec.get("tenantId") != tenant_id:
            raise ArtworkError("BLOCKED", "cross-tenant placement")
        if engineering_hash and rec.get("engineeringHash") != engineering_hash:
            raise ArtworkError("STALE", "stale placement engineeringHash")
        live = self.require_surface(rec["surfaceId"], tenant_id=tenant_id, engineering_hash=engineering_hash)
        if live.get("surfaceHash") != rec.get("surfaceHash"):
            raise ArtworkError("STALE", "stale surfaceHash")
        art = self.require_artwork(rec["artworkId"], tenant_id=tenant_id)
        if art.get("artworkHash") != rec.get("artworkHash"):
            raise ArtworkError("STALE", "stale artworkHash")
        return rec

    def produce_panel(
        self,
        *,
        tenant_id: str,
        artwork_id: str,
        master: dict[str, Any],
        crop: dict[str, Any],
        placement_hash: str,
        engineering_hash: str,
        output_px_per_mm: float = 2.0,
    ) -> dict[str, Any]:
        art = self.require_artwork(artwork_id, tenant_id=tenant_id)
        data = Path(art["path"]).read_bytes()
        if sha256_bytes(data) != art["sha256"]:
            raise ArtworkError("BLOCKED", "tampered artwork bytes")
        src_w, src_h, rgb = decode_png_rgb(data)
        master_w = _finite(master["widthMm"], "master width", positive=True)
        master_h = _finite(master["heightMm"], "master height", positive=True)
        box = crop["cropMm"]
        x0 = int(round((_finite(box["xMm"], "crop x") / master_w) * src_w))
        y0 = int(round((1.0 - (_finite(box["yMm"], "crop y") + _finite(box["heightMm"], "crop h", positive=True)) / master_h) * src_h))
        w_px = max(1, int(round((_finite(box["widthMm"], "crop w", positive=True) / master_w) * src_w)))
        h_px = max(1, int(round((_finite(box["heightMm"], "crop h", positive=True) / master_h) * src_h)))
        y0 = max(0, min(src_h - 1, y0))
        x0 = max(0, min(src_w - 1, x0))
        w_px = min(w_px, src_w - x0)
        h_px = min(h_px, src_h - y0)
        cropped = crop_rgb(rgb, src_w, src_h, x0, y0, w_px, h_px)
        out_w = max(1, int(round(_finite(box["widthMm"], "w", positive=True) * output_px_per_mm)))
        out_h = max(1, int(round(_finite(box["heightMm"], "h", positive=True) * output_px_per_mm)))
        # Keep exact crop pixels as production bytes (no stretch).
        out_w, out_h = w_px, h_px
        dest = Path(self.platform.root) / "artwork-out" / f"{crop['surfaceId']}.png"
        write_png(dest, out_w, out_h, cropped)
        raw = dest.read_bytes()
        digest = sha256_bytes(raw)
        obj = self.platform.dam.put(
            tenant_id=tenant_id,
            kind="production_artwork",
            name=f"{crop['componentId']}.png",
            data=raw,
            metadata={
                "role": "PRODUCTION_ARTWORK",
                "engineeringHash": engineering_hash,
                "surfaceHash": crop["surfaceHash"],
                "artworkHash": art["artworkHash"],
                "placementHash": placement_hash,
                "masterHash": crop.get("masterHash") or master.get("masterHash"),
            },
        )
        dpi = effective_dpi(out_w, float(box["widthMm"]))
        policy = evaluate_placement_policy(self.surfaces[crop["surfaceId"]], box, dpi=dpi)
        manifest = {
            "tenantId": tenant_id,
            "productId": master.get("productId"),
            "engineeringHash": engineering_hash,
            "surfaceId": crop["surfaceId"],
            "surfaceHash": crop["surfaceHash"],
            "componentId": crop["componentId"],
            "masterArtworkHash": art["artworkHash"],
            "placementHash": placement_hash,
            "masterHash": crop.get("masterHash") or master.get("masterHash"),
            "cropMm": box,
            "cropPx": {"x": x0, "y": y0, "w": w_px, "h": h_px},
            "outputPhysicalMm": {"widthMm": box["widthMm"], "heightMm": box["heightMm"]},
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
            "productionArtworkFileReady": True,
            "physicalPrintValidated": False,
            "printPreflight": "PARTIAL",
        }
        if obj.sha256 != digest:
            raise ArtworkError("BLOCKED", "production hash mismatch")
        return manifest

    def blender_job_payload(
        self,
        *,
        tenant_id: str,
        engineering: dict[str, Any],
        placements: list[dict[str, Any]],
        artwork_path: str,
    ) -> dict[str, Any]:
        items = []
        for rec in placements:
            items.append(
                {
                    "objectName": rec.get("componentId") or rec.get("surfaceId"),
                    "imagePath": artwork_path,
                    "uvRect": rec.get("uv") or rec.get("uvRect"),
                    "engineeringHash": rec.get("engineeringHash"),
                    "surfaceHash": rec.get("surfaceHash"),
                    "artworkHash": rec.get("artworkHash"),
                    "placementHash": rec.get("placementHash"),
                }
            )
        return {
            "tenantId": tenant_id,
            "engineering": engineering,
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
        hashes = {
            "engineeringHash": placement.get("engineeringHash"),
            "surfaceHash": placement.get("surfaceHash"),
            "artworkHash": placement.get("artworkHash"),
            "placementHash": placement.get("placementHash"),
        }
        mock = bool(getattr(self.platform, "mock_blender", True))
        rec = {
            **hashes,
            "usedMock": mock,
            "realBlender": False,
            "realArtworkPreviewReady": False,
            "physicalPrintValidated": False,
            "label": "MOCK" if mock else "PARTIAL",
        }
        if production:
            for key in ("engineeringHash", "surfaceHash", "artworkHash", "placementHash"):
                if production.get(key) != hashes.get(key) and production.get(key) != hashes.get(key if key != "artworkHash" else "masterArtworkHash"):
                    if key == "artworkHash" and production.get("masterArtworkHash") == hashes.get("artworkHash"):
                        continue
                    raise ArtworkError("BLOCKED", "preview/production hash mismatch")
            rec["productionArtworkFileReady"] = True
        if mock:
            rec["realArtworkPreviewReady"] = False
            return rec
        try:
            job = {
                "tenantId": tenant_id,
                "jobType": "BLENDER_RENDER",
                "engineering": {"width": 800, "height": 1800, "depth": 400, "components": []},
                "artworkPlacements": [
                    {
                        **hashes,
                        "uvRect": placement.get("uv"),
                    }
                ],
            }
            done = self.platform.submit_job(job) if hasattr(self.platform, "submit_job") else job
            used_mock = bool(done.get("usedMock") if isinstance(done, dict) else True)
            rec["usedMock"] = used_mock
            rec["realBlender"] = bool(isinstance(done, dict) and done.get("realBlender") and not used_mock)
            rec["realArtworkPreviewReady"] = rec["realBlender"] is True
            rec["label"] = "REAL" if rec["realArtworkPreviewReady"] else "MOCK"
            rec["jobId"] = done.get("jobId") if isinstance(done, dict) else None
            rec["blenderVersion"] = (done.get("blenderVersion") if isinstance(done, dict) else None)
        except Exception:
            rec["realArtworkPreviewReady"] = False
            rec["label"] = "BLOCKED_ENVIRONMENT"
        if mock:
            rec["realArtworkPreviewReady"] = False
        return rec


def validate_artwork_acceptance_result(result: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if result.get("physicalPrintValidated") is True:
        failures.append("physical_print")
    if result.get("globalProductionReady") not in {None, False}:
        failures.append("globalProductionReady")
    if result.get("fullAutonomousFactoryReady") not in {None, False}:
        failures.append("fullAutonomousFactoryReady")
    if result.get("liveFactoryExecutionReady") not in {None, False}:
        failures.append("liveFactoryExecutionReady")
    if result.get("liveMachineControl") not in {None, False}:
        failures.append("liveMachineControl")
    if result.get("mockBlender") and result.get("realArtworkPreviewReady") is True:
        failures.append("mock_claimed_real_preview")
    if not result.get("scenarios"):
        failures.append("scenarios_missing")
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
    s2 = factory.register_surfaces(cab2, tenant_id=tenant_a)
    s4 = factory.register_surfaces(cab4, tenant_id=tenant_a)
    s_desk = factory.register_surfaces(desk, tenant_id=tenant_a)
    s_retail = factory.register_surfaces(retail, tenant_id=tenant_a)
    s_acr = factory.register_surfaces(acr, tenant_id=tenant_a)
    s_pkg = factory.register_surfaces(pkg, tenant_id=tenant_a, family="PACKAGING")
    doors2 = [s for s in s2 if str(s["componentId"]).upper().startswith("DOOR")]
    doors4 = [s for s in s4 if str(s["componentId"]).upper().startswith("DOOR")]
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
    productions = [
        factory.produce_panel(
            tenant_id=tenant_a,
            artwork_id=art["artworkId"],
            master=master4,
            crop=crop,
            placement_hash=crop["placementHash"],
            engineering_hash=cab4.engineering_hash(),
        )
        for crop in crops4
    ]
    place2 = factory.place(
        tenant_id=tenant_a,
        surface_id=doors2[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab2.engineering_hash(),
        product_id=cab2.productId,
    )
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
    mock = bool(getattr(plat, "mock_blender", True))
    result = {
        "ok": True,
        "label": "FIXTURE/REAL_LOGIC",
        "surfaceDecorationLogicReady": True,
        "productionArtworkFileReady": True,
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
            "cabinet2": {"surfaceIds": [d["surfaceId"] for d in doors2], "placementHash": place2["placementHash"]},
            "cabinet4": {
                "masterHash": master4["masterHash"],
                "widthMm": master4["widthMm"],
                "panelCrops": [c["cropMm"] for c in crops4],
                "placementHashes": [p["placementHash"] for p in places4],
                "production": [{"sha256": p["sha256"], "placementHash": p["placementHash"], "surfaceHash": p["surfaceHash"]} for p in productions],
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
    result["ok"] = not validate_artwork_acceptance_result(result) and negatives.get("keepout") == "BLOCKED_PLACEMENT" and negatives.get("stale") == "STALE"
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
