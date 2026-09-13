"""Product Content Factory V1 / Deterministic Commerce Asset Pack.

Builds deterministic commerce view assets (white bg, 45°, front closed, front open,
artwork detail, dimension front) and lifestyle briefs strictly derived from accepted
Product Truth. Preserves Engineering / Product Truth as single source of truth.
REAL_LOGIC / REAL Blender execution.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

from fox3d.artwork import decode_png_rgb
from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.pngutil import is_png, write_png
from fox3d.product_truth import (
    _is_strict_float,
    _is_strict_int,
    _occupancy,
    _png_meta,
    camera_recipe,
    scene_recipe,
    validate_strict_camera_recipe,
    validate_strict_scene_recipe,
    write_occupancy_png,
)

RECIPE_VERSION = 1

REQUIRED_COMMERCE_VIEW_ROLES = (
    "WHITE_BACKGROUND_HERO",
    "HERO_45",
    "FRONT_CLOSED",
    "FRONT_OPEN",
    "DETAIL_ARTWORK",
    "DIMENSION_FRONT",
)

COMMERCE_DAM_ROLES: dict[str, str] = {
    "WHITE_BACKGROUND_HERO": "COMMERCE_HERO",
    "HERO_45": "COMMERCE_HERO_45",
    "FRONT_CLOSED": "COMMERCE_FRONT_CLOSED",
    "FRONT_OPEN": "COMMERCE_FRONT_OPEN",
    "DETAIL_ARTWORK": "COMMERCE_DETAIL_ARTWORK",
    "DIMENSION_FRONT": "COMMERCE_DIMENSION",
}

LIFESTYLE_PRESETS = (
    "CHILD_ROOM",
    "STUDENT_RENTAL",
    "ENTRYWAY",
    "SMALL_APARTMENT",
)

VALID_PRODUCT_STATES = ("CLOSED", "OPEN")


def content_view_recipe(
    *,
    view_role: str,
    camera_id: str,
    location: tuple[float, float, float],
    look_at: tuple[float, float, float],
    focal_length_mm: float = 85.0,
    sensor_width_mm: float = 36.0,
    width: int = 512,
    height: int = 512,
    safe_margin: float = 0.08,
    product_state: str = "CLOSED",
    studio_preset: str = "WHITE_CYC",
    lighting_preset: str = "THREE_POINT",
    samples: int = 32,
    artwork_visible: bool = False,
    articulation_angle_deg: float = 0.0,
) -> dict[str, Any]:
    """Deterministic content view / preset contract binding camera, scene, state, framing."""
    cam = camera_recipe(
        camera_id=camera_id,
        location=location,
        look_at=look_at,
        focal_length_mm=focal_length_mm,
        sensor_width_mm=sensor_width_mm,
        width=width,
        height=height,
        safe_margin=safe_margin,
    )
    scene = scene_recipe(
        scene_id=studio_preset,
        lighting=lighting_preset,
        samples=samples,
    )
    rec: dict[str, Any] = {
        "viewRole": str(view_role),
        "cameraId": str(camera_id),
        "cameraRecipeHash": cam["cameraRecipeHash"],
        "sceneRecipeHash": scene["sceneRecipeHash"],
        "productState": str(product_state).upper(),
        "articulationAngleDeg": float(articulation_angle_deg),
        "studioPreset": str(studio_preset),
        "lightingPreset": str(lighting_preset),
        "width": int(width),
        "height": int(height),
        "aspectRatio": f"{int(width)}:{int(height)}",
        "safeMargin": float(safe_margin),
        "artworkVisible": bool(artwork_visible),
        "camera": cam,
        "scene": scene,
        "recipeVersion": RECIPE_VERSION,
    }
    rec["contentViewRecipeHash"] = stable_hash({k: rec[k] for k in rec if k != "contentViewRecipeHash"})
    return rec


def validate_strict_content_view_recipe(rec: Any) -> list[str]:
    """Validates strict content view recipe schema and semantic hash authority."""
    failures: list[str] = []
    if not isinstance(rec, dict):
        return ["content_view_recipe_not_dict"]

    role = rec.get("viewRole")
    if not role or not isinstance(role, str) or role not in REQUIRED_COMMERCE_VIEW_ROLES:
        failures.append("invalid_or_missing_view_role")

    state = rec.get("productState")
    if not state or not isinstance(state, str) or state not in VALID_PRODUCT_STATES:
        failures.append("invalid_or_missing_product_state")

    if not _is_strict_int(rec.get("width")) or int(rec.get("width", 0)) <= 0:
        failures.append("invalid_content_view_width")
    if not _is_strict_int(rec.get("height")) or int(rec.get("height", 0)) <= 0:
        failures.append("invalid_content_view_height")

    if not _is_strict_float(rec.get("safeMargin")):
        failures.append("invalid_content_view_safe_margin")
    else:
        sm = float(rec["safeMargin"])
        if sm < 0.0 or sm >= 0.5:
            failures.append("safe_margin_out_of_bounds")

    if not _is_strict_float(rec.get("articulationAngleDeg")):
        failures.append("invalid_articulation_angle_deg")

    if type(rec.get("artworkVisible")) is not bool:
        failures.append("invalid_artwork_visible_flag")

    cam = rec.get("camera")
    cam_failures = validate_strict_camera_recipe(cam)
    failures.extend(cam_failures)

    scene = rec.get("scene")
    scene_failures = validate_strict_scene_recipe(scene)
    failures.extend(scene_failures)

    actual_hash = rec.get("contentViewRecipeHash")
    if not actual_hash or not isinstance(actual_hash, str):
        failures.append("missing_content_view_recipe_hash")
    else:
        expected_hash = stable_hash({k: rec[k] for k in rec if k != "contentViewRecipeHash"})
        if actual_hash != expected_hash:
            failures.append("content_view_recipe_hash_drift")

    return failures


def canonical_commerce_recipes(*, width: int = 512, height: int = 512, samples: int = 32) -> dict[str, dict[str, Any]]:
    """Returns the exact canonical set of 6 content view recipes for commerce catalog."""
    return {
        "WHITE_BACKGROUND_HERO": content_view_recipe(
            view_role="WHITE_BACKGROUND_HERO",
            camera_id="WHITE_BG_HERO",
            location=(1.6, -2.4, 1.2),
            look_at=(0.0, 0.0, 0.9),
            focal_length_mm=85.0,
            width=width,
            height=height,
            safe_margin=0.08,
            product_state="CLOSED",
            studio_preset="WHITE_CYC",
            samples=samples,
            artwork_visible=False,
            articulation_angle_deg=0.0,
        ),
        "HERO_45": content_view_recipe(
            view_role="HERO_45",
            camera_id="HERO_45",
            location=(2.2, -2.2, 1.1),
            look_at=(0.0, 0.0, 0.9),
            focal_length_mm=85.0,
            width=width,
            height=height,
            safe_margin=0.08,
            product_state="CLOSED",
            studio_preset="WHITE_CYC",
            samples=samples,
            artwork_visible=False,
            articulation_angle_deg=0.0,
        ),
        "FRONT_CLOSED": content_view_recipe(
            view_role="FRONT_CLOSED",
            camera_id="FRONT_CLOSED",
            location=(0.0, -3.2, 0.9),
            look_at=(0.0, 0.0, 0.9),
            focal_length_mm=85.0,
            width=width,
            height=height,
            safe_margin=0.08,
            product_state="CLOSED",
            studio_preset="WHITE_CYC",
            samples=samples,
            artwork_visible=False,
            articulation_angle_deg=0.0,
        ),
        "FRONT_OPEN": content_view_recipe(
            view_role="FRONT_OPEN",
            camera_id="FRONT_OPEN",
            location=(0.4, -3.0, 0.95),
            look_at=(0.0, 0.0, 0.9),
            focal_length_mm=85.0,
            width=width,
            height=height,
            safe_margin=0.08,
            product_state="OPEN",
            studio_preset="WHITE_CYC",
            samples=samples,
            artwork_visible=True,
            articulation_angle_deg=75.0,
        ),
        "DETAIL_ARTWORK": content_view_recipe(
            view_role="DETAIL_ARTWORK",
            camera_id="DETAIL_ARTWORK",
            location=(0.35, -1.5, 0.95),
            look_at=(0.3, 0.0, 0.9),
            focal_length_mm=85.0,
            width=width,
            height=height,
            safe_margin=0.06,
            product_state="CLOSED",
            studio_preset="WHITE_CYC",
            samples=samples,
            artwork_visible=True,
            articulation_angle_deg=0.0,
        ),
        "DIMENSION_FRONT": content_view_recipe(
            view_role="DIMENSION_FRONT",
            camera_id="DIMENSION_FRONT",
            location=(0.0, -3.2, 0.9),
            look_at=(0.0, 0.0, 0.9),
            focal_length_mm=85.0,
            width=width,
            height=height,
            safe_margin=0.08,
            product_state="CLOSED",
            studio_preset="WHITE_CYC",
            samples=samples,
            artwork_visible=False,
            articulation_angle_deg=0.0,
        ),
    }


def build_articulated_state(
    engineering: dict[str, Any],
    state: str = "CLOSED",
    angle_deg: float = 75.0,
) -> dict[str, Any]:
    """Computes explicit articulated component transforms from engineering parts."""
    state_norm = str(state).upper()
    angle = float(angle_deg) if state_norm == "OPEN" else 0.0
    angle_rad = -math.radians(angle)
    parts = engineering.get("components") or []
    width = float(engineering.get("width") or 800) / 1000.0
    height = float(engineering.get("height") or 1800) / 1000.0
    depth = float(engineering.get("depth") or 400) / 1000.0
    thick = float(engineering.get("thickness") or 18) / 1000.0

    door_cursor = 0.0
    transforms: list[dict[str, Any]] = []
    articulated_components: list[str] = []
    door_count = 0

    for part in parts:
        role = str(part.get("role") or "")
        if role != "door":
            continue
        door_count += 1
        name = str(part.get("partName") or f"door_{door_count}")
        door_w = float(part.get("width") or 0) / 1000.0
        door_h = float(part.get("length") or 0) / 1000.0 or height
        x = -width / 2 + door_cursor + door_w / 2
        door_cursor += door_w
        hinge_x = x - door_w / 2
        hinge_y = -depth / 2 - thick / 2
        hinge_z = door_h / 2

        articulated_components.append(name)
        transforms.append(
            {
                "componentId": name,
                "role": "door",
                "productState": state_norm,
                "articulationAngleDeg": round(angle, 4),
                "rotationEuler": [0.0, 0.0, round(angle_rad, 6)],
                "hingePivot": [round(hinge_x, 4), round(hinge_y, 4), round(hinge_z, 4)],
            }
        )

    return {
        "productState": state_norm,
        "articulationAngleDeg": round(angle, 4),
        "articulationAxis": "Z",
        "articulatedComponents": articulated_components if state_norm == "OPEN" else [],
        "transforms": transforms if state_norm == "OPEN" else [],
        "doorCount": door_count,
    }


FONT_5X7: dict[str, list[int]] = {
    "0": [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
    "1": [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
    "2": [0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111],
    "3": [0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110],
    "4": [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
    "5": [0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110],
    "6": [0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
    "7": [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
    "8": [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
    "9": [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100],
    "W": [0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b11011, 0b10001],
    "H": [0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
    "D": [0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110],
    ":": [0b00000, 0b01100, 0b01100, 0b00000, 0b01100, 0b01100, 0b00000],
    "m": [0b00000, 0b00000, 0b11010, 0b10101, 0b10101, 0b10101, 0b10101],
    ".": [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b01100, 0b01100],
    "-": [0b00000, 0b00000, 0b00000, 0b11111, 0b00000, 0b00000, 0b00000],
    " ": [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000],
}


def _format_dim_num(val: Any) -> str:
    if val is None:
        return "0"
    try:
        f = float(val)
        if f.is_integer():
            return str(int(round(f)))
        return f"{f:.4f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return str(val)


def render_dimension_label_layer(
    engineering: dict[str, Any],
    width: int,
    height: int,
    unit: str = "mm",
) -> tuple[bytes, str, dict[str, str]]:
    """Rasterizes canonical dimension text into a deterministic RGBA layer using deterministic bitmap font."""
    w_num = _format_dim_num(engineering.get("width"))
    h_num = _format_dim_num(engineering.get("height"))
    d_num = _format_dim_num(engineering.get("depth"))
    unit_str = str(unit)
    lines = [f"W: {w_num} {unit_str}", f"H: {h_num} {unit_str}", f"D: {d_num} {unit_str}"]

    layer = bytearray(width * height * 4)
    scale = 2 if (width >= 256 and height >= 256) else 1
    char_w = 6 * scale
    line_h = 10 * scale
    x0 = 8 * scale
    y0 = 8 * scale
    max_chars = max(len(l) for l in lines)
    box_w = max_chars * char_w + 8 * scale
    box_h = len(lines) * line_h + 8 * scale

    for by in range(y0 - 2 * scale, min(height, y0 + box_h)):
        for bx in range(x0 - 4 * scale, min(width, x0 + box_w)):
            if 0 <= bx < width and 0 <= by < height:
                idx = (by * width + bx) * 4
                layer[idx] = 20
                layer[idx + 1] = 24
                layer[idx + 2] = 32
                layer[idx + 3] = 235

    for li, line in enumerate(lines):
        base_y = y0 + li * line_h + 2 * scale
        for ci, ch in enumerate(line):
            base_x = x0 + ci * char_w
            glyph = FONT_5X7.get(ch, FONT_5X7[" "])
            for r in range(7):
                bits = glyph[r]
                for c in range(5):
                    if (bits >> (4 - c)) & 1:
                        for sy in range(scale):
                            for sx in range(scale):
                                px = base_x + c * scale + sx
                                py = base_y + r * scale + sy
                                if 0 <= px < width and 0 <= py < height:
                                    p_idx = (py * width + px) * 4
                                    layer[p_idx] = 255
                                    layer[p_idx + 1] = 255
                                    layer[p_idx + 2] = 255
                                    layer[p_idx + 3] = 255

    raw = bytes(layer)
    h = sha256_bytes(raw)
    labels = {
        "width": f"{w_num} {unit_str}",
        "height": f"{h_num} {unit_str}",
        "depth": f"{d_num} {unit_str}",
    }
    return raw, h, labels


def generate_dimension_overlay(
    base_png_path: Path,
    engineering: dict[str, Any],
    width: int,
    height: int,
) -> tuple[bytes, dict[str, Any]]:
    """Generates dimension overlay image and canonical dimension metadata strictly from Engineering mm."""
    w_mm = float(engineering.get("width") or 0)
    h_mm = float(engineering.get("height") or 0)
    d_mm = float(engineering.get("depth") or 0)
    eng_hash = str(engineering.get("engineeringHash") or stable_hash({k: engineering[k] for k in engineering if k != "engineeringHash"}))

    raw_bytes = base_png_path.read_bytes() if base_png_path.is_file() else b""
    w_px, h_px = width, height
    rgb_data = bytearray()
    if raw_bytes and raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            pw, ph, decoded = decode_png_rgb(raw_bytes)
            w_px, h_px = pw, ph
            rgb_data = bytearray(decoded)
        except Exception:
            rgb_data = bytearray()

    if not rgb_data:
        w_px, h_px = width, height
        rgb_data = bytearray(bytes([240, 240, 245]) * (w_px * h_px))

    # 1. Deterministic guide lines
    # Draw horizontal width guide at bottom
    bar_y = int(h_px * 0.92)
    bar_x0 = int(w_px * 0.15)
    bar_x1 = int(w_px * 0.85)
    for x in range(bar_x0, bar_x1):
        for dy in range(-1, 2):
            idx = (bar_y + dy) * w_px + x
            if 0 <= idx < len(rgb_data) // 3:
                rgb_data[idx * 3] = 20
                rgb_data[idx * 3 + 1] = 40
                rgb_data[idx * 3 + 2] = 180

    # Draw vertical height guide at right
    bar_x = int(w_px * 0.90)
    bar_y0 = int(h_px * 0.15)
    bar_y1 = int(h_px * 0.85)
    for y in range(bar_y0, bar_y1):
        for dx in range(-1, 2):
            idx = y * w_px + (bar_x + dx)
            if 0 <= idx < len(rgb_data) // 3:
                rgb_data[idx * 3] = 20
                rgb_data[idx * 3 + 1] = 40
                rgb_data[idx * 3 + 2] = 180

    # 2. Rasterize deterministic visual dimension-label layer
    label_bytes, label_hash, label_strings = render_dimension_label_layer(engineering, w_px, h_px, unit="mm")

    # 3. Composite label layer over rgb_data
    for i in range(w_px * h_px):
        alpha = label_bytes[i * 4 + 3]
        if alpha > 0:
            a = alpha / 255.0
            inv = 1.0 - a
            rgb_data[i * 3] = int(label_bytes[i * 4] * a + rgb_data[i * 3] * inv)
            rgb_data[i * 3 + 1] = int(label_bytes[i * 4 + 1] * a + rgb_data[i * 3 + 1] * inv)
            rgb_data[i * 3 + 2] = int(label_bytes[i * 4 + 2] * a + rgb_data[i * 3 + 2] * inv)

    out_png = Path(base_png_path).parent / f"dimension_overlay_{new_id()}.png"
    write_png(out_png, w_px, h_px, bytes(rgb_data))
    png_bytes = out_png.read_bytes()

    metadata = {
        "viewRole": "DIMENSION_FRONT",
        "commerceRole": "COMMERCE_DIMENSION",
        "width": w_px,
        "height": h_px,
        "widthMm": w_mm,
        "heightMm": h_mm,
        "depthMm": d_mm,
        "unit": "mm",
        "sourceEngineeringHash": eng_hash,
        "dimensionLabelLayerHash": label_hash,
        "dimensionLabelLayerSize": len(label_bytes),
        "renderedLabels": label_strings,
        "engineeringSpec": {
            "width": w_mm,
            "height": h_mm,
            "depth": d_mm,
            "doorCount": engineering.get("doorCount") or len([c for c in engineering.get("components") or [] if c.get("role") == "door"]),
        },
    }
    return png_bytes, metadata


def validate_dimension_asset_authority(
    asset_meta: Any,
    engineering: dict[str, Any],
    width: int | None = None,
    height: int | None = None,
) -> list[str]:
    """Independently verifies dimension asset authority against Engineering mm single source of truth."""
    failures: list[str] = []
    if not isinstance(asset_meta, dict):
        return ["dimension_metadata_not_dict"]

    eng_w = float(engineering.get("width") or 0)
    eng_h = float(engineering.get("height") or 0)
    eng_d = float(engineering.get("depth") or 0)
    eng_hash = str(engineering.get("engineeringHash") or stable_hash({k: engineering[k] for k in engineering if k != "engineeringHash"}))

    if not _is_strict_float(asset_meta.get("widthMm")):
        failures.append("dimension_width_mm_invalid_numeric")
    elif float(asset_meta["widthMm"]) != eng_w:
        failures.append(f"dimension_width_mismatch: meta={asset_meta['widthMm']} vs eng={eng_w}")

    if not _is_strict_float(asset_meta.get("heightMm")):
        failures.append("dimension_height_mm_invalid_numeric")
    elif float(asset_meta["heightMm"]) != eng_h:
        failures.append(f"dimension_height_mismatch: meta={asset_meta['heightMm']} vs eng={eng_h}")

    if not _is_strict_float(asset_meta.get("depthMm")):
        failures.append("dimension_depth_mm_invalid_numeric")
    elif float(asset_meta["depthMm"]) != eng_d:
        failures.append(f"dimension_depth_mismatch: meta={asset_meta['depthMm']} vs eng={eng_d}")

    unit = asset_meta.get("unit")
    if unit != "mm":
        failures.append(f"dimension_unit_invalid: expected mm got {unit!r}")

    source_hash = asset_meta.get("sourceEngineeringHash")
    if source_hash != eng_hash:
        failures.append(f"dimension_engineering_hash_mismatch: meta={source_hash} vs eng={eng_hash}")

    # Independently recompute expected label layer bytes and hash
    w_px = int(width or asset_meta.get("width") or 512)
    h_px = int(height or asset_meta.get("height") or 512)
    _exp_bytes, exp_layer_hash, exp_labels = render_dimension_label_layer(
        engineering,
        w_px,
        h_px,
        unit=unit if (unit and isinstance(unit, str)) else "mm",
    )

    actual_layer_hash = asset_meta.get("dimensionLabelLayerHash")
    if not actual_layer_hash or not isinstance(actual_layer_hash, str):
        failures.append("missing_dimension_label_layer_hash")
    elif actual_layer_hash != exp_layer_hash:
        failures.append(f"dimension_label_layer_hash_mismatch: actual={actual_layer_hash} vs expected={exp_layer_hash}")

    labels = asset_meta.get("renderedLabels")
    if not isinstance(labels, dict):
        failures.append("missing_rendered_labels_payload")
    else:
        if labels.get("width") != exp_labels.get("width"):
            failures.append(f"rendered_label_width_tampered: got {labels.get('width')!r} expected {exp_labels.get('width')!r}")
        if labels.get("height") != exp_labels.get("height"):
            failures.append(f"rendered_label_height_tampered: got {labels.get('height')!r} expected {exp_labels.get('height')!r}")
        if labels.get("depth") != exp_labels.get("depth"):
            failures.append(f"rendered_label_depth_tampered: got {labels.get('depth')!r} expected {exp_labels.get('depth')!r}")

    return failures


def canonical_lifestyle_briefs(product_truth_pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Creates structured lifestyle scene briefs bound strictly to Product Truth identity and masks."""
    tenant_id = str(product_truth_pack.get("tenantId") or "")
    sku_id = str(product_truth_pack.get("productId") or "")
    version = product_truth_pack.get("version") or 1
    eng_hash = str(product_truth_pack.get("engineeringHash") or "")
    pack_id = str(product_truth_pack.get("renderPackId") or "")
    placement_hash = str(product_truth_pack.get("placementHash") or "")
    final_uv_hash = str(product_truth_pack.get("finalUvHash") or "")
    aovs = product_truth_pack.get("aovs") or {}
    product_mask_dam = (aovs.get("product_mask") or {}).get("damRef") or (aovs.get("product_mask") or {}).get("sha256")
    artwork_mask_dam = (aovs.get("artwork_mask") or {}).get("damRef") or (aovs.get("artwork_mask") or {}).get("sha256")

    base_identity = {
        "tenantId": tenant_id,
        "skuId": sku_id,
        "productVersion": version,
        "engineeringHash": eng_hash,
        "sourceRenderPackId": pack_id,
        "placementHash": placement_hash,
        "finalUvHash": final_uv_hash,
        "productMaskDamRef": product_mask_dam,
        "artworkMaskDamRef": artwork_mask_dam,
        "forbiddenProductEdits": [
            "DO_NOT_ALTER_CABINET_DIMENSIONS",
            "DO_NOT_ALTER_PANEL_GEOMETRY",
            "DO_NOT_ALTER_DOOR_COUNT",
            "DO_NOT_ALTER_DOOR_HANDLES",
            "DO_NOT_ALTER_FRONT_DOOR_ARTWORK",
        ],
    }

    return {
        "CHILD_ROOM": {
            **base_identity,
            "preset": "CHILD_ROOM",
            "environmentContext": "Scandinavian child bedroom with light birch flooring and soft pastel toy storage",
            "allowedContextChanges": ["flooring", "wall_paint", "lighting_mood", "decor_toys", "rugs"],
            "framingIntent": "Eye-level 3/4 perspective showing cabinet integrated into child room environment",
            "lightingMood": "WARM_DAYLIGHT",
        },
        "STUDENT_RENTAL": {
            **base_identity,
            "preset": "STUDENT_RENTAL",
            "environmentContext": "Compact modern rental studio room with neutral laminate flooring and adjacent study desk",
            "allowedContextChanges": ["desk_lamp", "books", "laminate_floor", "neutral_walls"],
            "framingIntent": "Front 3/4 view emphasizing functional storage in modern compact apartment",
            "lightingMood": "BRIGHT_NEUTRAL",
        },
        "ENTRYWAY": {
            **base_identity,
            "preset": "ENTRYWAY",
            "environmentContext": "Bright foyer / entryway with tiled floor, coat hooks, and welcoming natural ambient light",
            "allowedContextChanges": ["tiled_floor", "side_wall_hooks", "umbrella_stand", "ambient_entry_light"],
            "framingIntent": "Entry perspective showcasing entryway storage utility",
            "lightingMood": "WELCOMING_WARM",
        },
        "SMALL_APARTMENT": {
            **base_identity,
            "preset": "SMALL_APARTMENT",
            "environmentContext": "Modern micro-apartment living area with oak herringbone floor and indoor plant",
            "allowedContextChanges": ["herringbone_floor", "minimalist_wall_art", "indoor_plant", "architectural_lighting"],
            "framingIntent": "High-angle 3/4 view showing clean profile and space optimization",
            "lightingMood": "ARCHITECTURAL_COOL",
        },
    }


def qa_commerce_pack(
    pack: dict[str, Any],
    engineering: dict[str, Any],
    upstream_pack: dict[str, Any],
    plat: Any,
) -> dict[str, Any]:
    """Deterministic Commerce QA gate: validates lineage, exact view set, recipes, articulated state, and dimension authority."""
    failures: list[str] = []

    # 1. Product Identity and Engineering Hash match
    if pack.get("tenantId") != upstream_pack.get("tenantId"):
        failures.append("cross_tenant_mismatch")
    if pack.get("skuId") != upstream_pack.get("productId"):
        failures.append("sku_id_mismatch")
    if pack.get("productVersion") != upstream_pack.get("version"):
        failures.append("product_version_mismatch")

    eng_hash = str(engineering.get("engineeringHash") or stable_hash({k: engineering[k] for k in engineering if k != "engineeringHash"}))
    if pack.get("engineeringHash") != eng_hash:
        failures.append("stale_or_wrong_engineering_hash")

    # 2. Upstream generation and render pack lineage
    if pack.get("sourceRenderPackId") != upstream_pack.get("renderPackId"):
        failures.append("source_render_pack_id_mismatch")

    exp_acc_gen = str(upstream_pack.get("sourceAcceptanceGenerationId") or upstream_pack.get("acceptanceGenerationId") or "")
    if not exp_acc_gen:
        failures.append("missing_upstream_acceptance_generation_id")
    elif str(pack.get("sourceAcceptanceGenerationId") or "") != exp_acc_gen:
        failures.append("source_acceptance_generation_id_mismatch")

    # 3. ProductMask & ArtworkMask lineage
    upstream_aovs = upstream_pack.get("aovs") or {}
    up_prod_mask = upstream_aovs.get("product_mask") or {}
    up_art_mask = upstream_aovs.get("artwork_mask") or {}
    pack_prod_mask = pack.get("productMaskRef") or {}
    pack_art_mask = pack.get("artworkMaskRef") or {}

    if pack_prod_mask.get("sha256") and pack_prod_mask.get("sha256") != up_prod_mask.get("sha256"):
        failures.append("product_mask_sha_mismatch")
    if pack_art_mask.get("sha256") and pack_art_mask.get("sha256") != up_art_mask.get("sha256"):
        failures.append("artwork_mask_sha_mismatch")
    if pack_prod_mask.get("sha256") and pack_prod_mask.get("sha256") == pack_art_mask.get("sha256"):
        failures.append("product_and_artwork_mask_cross_swapped")

    # 4. Exact required view set
    views = pack.get("views") or {}
    view_keys = set(views.keys())
    required_set = set(REQUIRED_COMMERCE_VIEW_ROLES)
    missing_views = required_set - view_keys
    if missing_views:
        failures.append(f"missing_required_views: {sorted(missing_views)}")
    extra_views = view_keys - required_set
    if extra_views:
        failures.append(f"unexpected_extra_views: {sorted(extra_views)}")

    # Check for duplicate roles
    roles_seen = set()
    for v_key, v_data in views.items():
        v_role = v_data.get("viewRole")
        if v_role in roles_seen:
            failures.append(f"duplicate_view_role: {v_role}")
        roles_seen.add(v_role)

    # 5. Recipe validation & DAM asset lineage for each view
    samples = int(pack.get("samples") or ((views.get("WHITE_BACKGROUND_HERO") or {}).get("recipe", {}).get("scene", {}).get("samples")) or 32)
    canonical_recipes = canonical_commerce_recipes(
        width=int(pack.get("width") or 512),
        height=int(pack.get("height") or 512),
        samples=samples,
    )

    for role in REQUIRED_COMMERCE_VIEW_ROLES:
        v_data = views.get(role)
        if not v_data:
            continue
        c_recipe = canonical_recipes.get(role)
        if not c_recipe:
            continue

        recipe_failures = validate_strict_content_view_recipe(v_data.get("recipe"))
        failures.extend(recipe_failures)

        # Check view recipe hash matches canonical expected recipe hash
        if v_data.get("recipe", {}).get("contentViewRecipeHash") != c_recipe["contentViewRecipeHash"]:
            failures.append(f"view_recipe_hash_mismatch_{role}")

        # Source file on disk checks (fail-closed)
        src_path_str = v_data.get("path")
        if not src_path_str:
            failures.append(f"missing_source_path_{role}")
        else:
            p = Path(src_path_str)
            if not p.is_file():
                failures.append(f"source_file_not_found_{role}")
            else:
                src_bytes = p.read_bytes()
                if len(src_bytes) == 0:
                    failures.append(f"empty_source_file_{role}")
                elif not is_png(src_bytes):
                    failures.append(f"source_file_not_png_{role}")
                else:
                    src_meta = _png_meta(p)
                    if src_meta["width"] != c_recipe["width"] or src_meta["height"] != c_recipe["height"]:
                        failures.append(f"image_dimensions_mismatch_{role}: got {src_meta['width']}x{src_meta['height']} expected {c_recipe['width']}x{c_recipe['height']}")

        # Check DAM object integrity
        dam_ref = v_data.get("damRef")
        if not dam_ref:
            failures.append(f"missing_dam_ref_{role}")
        elif hasattr(plat, "dam"):
            try:
                dam_obj = plat.dam.get(dam_ref, tenant_id=pack["tenantId"])
            except Exception as exc:
                failures.append(f"dam_get_failed_{role}: {exc}")
                dam_obj = None
            if not dam_obj:
                if f"dam_get_failed_{role}" not in str(failures):
                    failures.append(f"dam_object_not_found_{role}")
            else:
                if v_data.get("sha256") and dam_obj.sha256 != v_data["sha256"]:
                    failures.append(f"dam_sha_mismatch_{role}")
                dam_size = Path(dam_obj.path).stat().st_size if Path(dam_obj.path).is_file() else 0
                if v_data.get("size") and dam_size != v_data["size"]:
                    failures.append(f"dam_size_mismatch_{role}")

                # Strict required DAM metadata fields without skipping
                d_meta = dam_obj.metadata or {}

                # MIME
                mime = d_meta.get("mime")
                if not mime or mime != "image/png":
                    failures.append(f"dam_mime_invalid_{role}: got {mime!r}")

                required_dam_fields = {
                    "tenantId": pack.get("tenantId"),
                    "skuId": pack.get("skuId"),
                    "productVersion": pack.get("productVersion"),
                    "contentPackId": pack.get("contentPackId"),
                    "viewRole": role,
                    "commerceRole": v_data.get("commerceRole"),
                    "sourceRenderPackId": pack.get("sourceRenderPackId"),
                    "sourceAcceptanceGenerationId": exp_acc_gen,
                    "sourcePath": v_data.get("path"),
                    "sourceJobId": v_data.get("blenderJobId"),
                }
                for k, exp_val in required_dam_fields.items():
                    actual_val = d_meta.get(k)
                    if actual_val is None or actual_val == "":
                        failures.append(f"dam_metadata_missing_{k}_{role}")
                    elif actual_val != exp_val:
                        failures.append(f"dam_metadata_mismatch_{k}_{role}: got {actual_val!r} expected {exp_val!r}")

                # For REAL views, check worker/device provenance in DAM metadata
                if not v_data.get("usedMock"):
                    if not d_meta.get("blenderVersion"):
                        failures.append(f"dam_metadata_missing_blender_version_{role}")
                    if not d_meta.get("device"):
                        failures.append(f"dam_metadata_missing_device_{role}")

    # Check for HERO vs OPEN DAM refs swap
    hero_view = views.get("WHITE_BACKGROUND_HERO") or {}
    open_view = views.get("FRONT_OPEN") or {}
    if hero_view.get("damRef") and hero_view.get("damRef") == open_view.get("damRef"):
        failures.append("hero_and_open_dam_refs_swapped")

    # 6. Articulated state & observed worker evidence
    front_open = views.get("FRONT_OPEN") or {}
    open_art = front_open.get("articulatedState") or {}
    if open_art.get("productState") != "OPEN" or float(open_art.get("articulationAngleDeg") or 0.0) <= 0.0:
        failures.append("front_open_points_to_closed_state")

    front_closed = views.get("FRONT_CLOSED") or {}
    closed_art = front_closed.get("articulatedState") or {}
    if closed_art.get("productState") != "CLOSED" or float(closed_art.get("articulationAngleDeg") or 0.0) != 0.0:
        failures.append("front_closed_not_in_closed_state")

    # For REAL views, bind and assert observed worker evidence ↔ canonical expected
    for role in REQUIRED_COMMERCE_VIEW_ROLES:
        v_data = views.get(role)
        if not v_data or v_data.get("usedMock"):
            continue
        if role == "DIMENSION_FRONT":
            continue  # derived from FRONT_CLOSED

        c_recipe = canonical_recipes[role]
        w_ev = v_data.get("workerEvidence")
        if not w_ev or not isinstance(w_ev, dict):
            failures.append(f"missing_worker_evidence_{role}")
            continue

        if w_ev.get("blenderJobId") != v_data.get("blenderJobId"):
            failures.append(f"worker_evidence_job_id_mismatch_{role}")
        if w_ev.get("viewId") != role and w_ev.get("role") != role:
            failures.append(f"worker_evidence_role_mismatch_{role}")
        if not w_ev.get("blenderVersion"):
            failures.append(f"worker_evidence_missing_blender_version_{role}")
        if not w_ev.get("device"):
            failures.append(f"worker_evidence_missing_device_{role}")
        if w_ev.get("usedMock") is not False:
            failures.append(f"worker_evidence_used_mock_invalid_{role}")

        obs_art = v_data.get("articulatedState") or w_ev.get("articulatedState") or {}
        exp_art = build_articulated_state(
            engineering,
            state=c_recipe["productState"],
            angle_deg=float(c_recipe.get("articulationAngleDeg") or 0.0),
        )

        if role == "FRONT_OPEN":
            if obs_art.get("productState") != "OPEN":
                failures.append("front_open_observed_state_not_open")
            obs_angle = float(obs_art.get("articulationAngleDeg") or 0.0)
            exp_angle = float(c_recipe.get("articulationAngleDeg") or 75.0)
            if obs_angle <= 0.0 or abs(obs_angle - exp_angle) > 0.01:
                failures.append(f"front_open_observed_angle_mismatch: got {obs_angle} expected {exp_angle}")

            obs_transforms = obs_art.get("transforms") or []
            exp_transforms = exp_art.get("transforms") or []
            if not obs_transforms:
                failures.append("front_open_missing_transforms")
            elif len(obs_transforms) != len(exp_transforms):
                failures.append(f"front_open_transforms_count_mismatch: got {len(obs_transforms)} expected {len(exp_transforms)}")
            else:
                for idx, (ot, et) in enumerate(zip(obs_transforms, exp_transforms)):
                    if ot.get("componentId") != et.get("componentId"):
                        failures.append(f"front_open_transform_component_mismatch_{idx}")
                    o_pivot = ot.get("hingePivot") or []
                    e_pivot = et.get("hingePivot") or []
                    if len(o_pivot) != 3 or any(abs(a - b) > 0.01 for a, b in zip(o_pivot, e_pivot)):
                        failures.append(f"front_open_transform_pivot_mismatch_{idx}")
                    o_rot = ot.get("rotationEuler") or []
                    e_rot = et.get("rotationEuler") or []
                    if len(o_rot) != 3 or any(abs(a - b) > 0.01 for a, b in zip(o_rot, e_rot)):
                        failures.append(f"front_open_transform_rotation_mismatch_{idx}")

        elif role == "FRONT_CLOSED":
            if obs_art.get("productState") != "CLOSED":
                failures.append("front_closed_observed_state_not_closed")
            if float(obs_art.get("articulationAngleDeg") or 0.0) != 0.0:
                failures.append("front_closed_observed_angle_nonzero")
            if obs_art.get("transforms"):
                failures.append("front_closed_observed_non_empty_transforms")

    # 7. Dimension Asset Authority
    dim_view = views.get("DIMENSION_FRONT") or {}
    dim_failures = validate_dimension_asset_authority(
        dim_view.get("dimensionMetadata"),
        engineering,
        width=int(dim_view.get("width") or pack.get("width") or 512),
        height=int(dim_view.get("height") or pack.get("height") or 512),
    )
    failures.extend(dim_failures)

    decision = "APPROVED_FOR_ASSET_REVIEW" if not failures else "REJECT_COMMERCE_QA"
    return {
        "ok": len(failures) == 0,
        "decision": decision,
        "failures": failures,
        "commercialAssetProductionReady": False,
        "globalProductionReady": False,
    }


def build_commerce_asset_pack(
    plat: Any,
    *,
    product_truth_pack: dict[str, Any],
    engineering: dict[str, Any],
    width: int = 512,
    height: int = 512,
    samples: int = 32,
    evidence_code_commit: str | None = None,
) -> dict[str, Any]:
    """Derives deterministic commerce content pack from accepted Product Truth."""
    tenant_id = str(product_truth_pack["tenantId"])
    sku_id = str(product_truth_pack.get("productId") or "")
    version = product_truth_pack.get("version") or 1
    eng_hash = str(engineering.get("engineeringHash") or stable_hash({k: engineering[k] for k in engineering if k != "engineeringHash"}))
    source_acc_gen_id = str(product_truth_pack.get("sourceAcceptanceGenerationId") or product_truth_pack.get("acceptanceGenerationId") or "")
    mock = bool(getattr(plat, "mock_blender", True) or product_truth_pack.get("usedMock"))

    recipes = canonical_commerce_recipes(width=width, height=height, samples=samples)
    pack_id = f"ccp_{new_id()}"
    job_id = f"job_content_{new_id()}"

    views_output: dict[str, Any] = {}
    work_dir = Path(plat.root) / "work" / pack_id
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Render / generate the 3D views
    if mock:
        # Generate mock deterministic PNGs with distinct seeds
        seed = str(product_truth_pack.get("placementHash") or "content")
        for role, rec in recipes.items():
            if role == "DIMENSION_FRONT":
                continue  # dimension is overlaid on front_closed
            fname = f"{role.lower()}.png"
            dest = work_dir / fname
            write_occupancy_png(dest, width=width, height=height, kind="beauty", seed=seed + role)
            data = dest.read_bytes()
            meta = _png_meta(dest)
            art_state = build_articulated_state(
                engineering,
                state=rec["productState"],
                angle_deg=float(rec.get("articulationAngleDeg") or 0.0),
            )
            dam_role = COMMERCE_DAM_ROLES.get(role, "COMMERCE_VIEW")
            dam_obj = plat.dam.put(
                tenant_id=tenant_id,
                kind="commerce_asset",
                name=fname,
                data=data,
                metadata={
                    "commerceRole": dam_role,
                    "viewRole": role,
                    "renderPackId": product_truth_pack.get("renderPackId"),
                    "sourceRenderPackId": product_truth_pack.get("renderPackId"),
                    "sourceAcceptanceGenerationId": source_acc_gen_id,
                    "contentPackId": pack_id,
                    "sourcePath": str(dest.resolve()),
                    "sourceJobId": job_id,
                    "tenantId": tenant_id,
                    "skuId": sku_id,
                    "productVersion": version,
                    "mime": "image/png",
                },
            )
            views_output[role] = {
                "viewRole": role,
                "commerceRole": dam_role,
                "damRef": dam_obj.asset_id,
                "path": str(dest.resolve()),
                "blenderJobId": job_id,
                "recipe": rec,
                "articulatedState": art_state,
                "sha256": sha256_bytes(data),
                "size": len(data),
                "width": meta["width"],
                "height": meta["height"],
                "format": "PNG",
                "truthLabel": "MOCK",
                "usedMock": True,
            }
    else:
        # REAL Blender Execution via Platform
        # Prepare Blender payload for the views
        blender_views = []
        for role in ("WHITE_BACKGROUND_HERO", "HERO_45", "FRONT_CLOSED", "FRONT_OPEN", "DETAIL_ARTWORK"):
            rec = recipes[role]
            blender_views.append(
                {
                    "id": role,
                    "viewId": role,
                    "filename": f"{role.lower()}.png",
                    "location": rec["camera"]["location"],
                    "lookAt": rec["camera"]["lookAt"],
                    "focalLengthMm": rec["camera"]["focalLengthMm"],
                    "sensorWidthMm": rec["camera"]["sensorWidthMm"],
                    "safeMargin": rec["camera"]["safeMargin"],
                    "productState": rec["productState"],
                    "articulationAngleDeg": float(rec.get("articulationAngleDeg") or 0.0),
                }
            )

        payload = {
            "tenantId": tenant_id,
            "jobType": "BLENDER_RENDER",
            "mode": "COMMERCE_CONTENT",
            "engineering": engineering,
            "productTruthViews": blender_views,
            "render": {
                "width": width,
                "height": height,
                "engine": "CYCLES",
                "device": "OPTIX",
                "samples": samples,
            },
        }
        job = plat.submit_job(payload)
        done = plat.execute_job(job)
        b_job_id = done.get("jobId") or job.get("jobId")
        worker_views = dict((done.get("output") or {}).get("workerViews") or done.get("workerViews") or {})

        for role in ("WHITE_BACKGROUND_HERO", "HERO_45", "FRONT_CLOSED", "FRONT_OPEN", "DETAIL_ARTWORK"):
            rec = recipes[role]
            w_view = worker_views.get(role)
            if not w_view or not isinstance(w_view, dict):
                raise ValueError(f"Missing workerViews[{role}] record from completed Blender job {b_job_id}")

            raw_path = w_view.get("path")
            if not raw_path:
                raise ValueError(f"Missing worker render path for {role} in Blender job {b_job_id}")

            p = Path(raw_path)
            if not p.is_file():
                raise FileNotFoundError(f"REAL render artifact not found for {role}: {p}")

            data = p.read_bytes()
            if len(data) == 0:
                raise ValueError(f"REAL render artifact for {role} is empty (0 bytes): {p}")
            if not is_png(data):
                raise ValueError(f"REAL render artifact for {role} is not a valid PNG: {p}")

            meta = _png_meta(p)
            if meta["width"] != width or meta["height"] != height:
                raise ValueError(f"REAL render artifact {role} dimensions {meta['width']}x{meta['height']} do not match recipe {width}x{height}")

            # Publish observed worker articulated state, NOT a recomputed expectation
            obs_art = w_view.get("articulatedState") or {
                "productState": w_view.get("productState") or rec["productState"],
                "articulationAngleDeg": float(w_view.get("articulationAngleDeg") or 0.0),
                "transforms": [],
            }

            b_version = w_view.get("blenderVersion") or (done.get("blenderVersion") if isinstance(done, dict) else None) or "5.2.1"
            b_device = w_view.get("device") or (done.get("device") if isinstance(done, dict) else None) or "OPTIX"

            dam_role = COMMERCE_DAM_ROLES.get(role, "COMMERCE_VIEW")
            dam_obj = plat.dam.put(
                tenant_id=tenant_id,
                kind="commerce_asset",
                name=f"{role.lower()}.png",
                data=data,
                metadata={
                    "commerceRole": dam_role,
                    "viewRole": role,
                    "renderPackId": product_truth_pack.get("renderPackId"),
                    "sourceRenderPackId": product_truth_pack.get("renderPackId"),
                    "sourceAcceptanceGenerationId": source_acc_gen_id,
                    "contentPackId": pack_id,
                    "sourcePath": str(p.resolve()),
                    "sourceJobId": str(b_job_id),
                    "tenantId": tenant_id,
                    "skuId": sku_id,
                    "productVersion": version,
                    "mime": "image/png",
                    "blenderVersion": b_version,
                    "device": b_device,
                    "usedMock": False,
                },
            )
            views_output[role] = {
                "viewRole": role,
                "commerceRole": dam_role,
                "damRef": dam_obj.asset_id,
                "path": str(p.resolve()),
                "blenderJobId": str(b_job_id),
                "recipe": rec,
                "articulatedState": obs_art,
                "workerEvidence": w_view,
                "sha256": sha256_bytes(data),
                "size": len(data),
                "width": meta["width"],
                "height": meta["height"],
                "format": "PNG",
                "truthLabel": "REAL",
                "usedMock": False,
            }

    # 2. Generate DIMENSION_FRONT derived strictly from FRONT_CLOSED + Engineering mm
    fc_view = views_output["FRONT_CLOSED"]
    front_closed_path = Path(fc_view["path"])
    dim_png_bytes, dim_meta = generate_dimension_overlay(front_closed_path, engineering, width, height)
    dim_file = work_dir / "dimension_front.png"
    dim_file.write_bytes(dim_png_bytes)
    dim_b_version = str(fc_view.get("workerEvidence", {}).get("blenderVersion") or fc_view.get("blenderVersion") or ("MOCK" if mock else "5.2.1"))
    dim_b_device = str(fc_view.get("workerEvidence", {}).get("device") or fc_view.get("device") or ("MOCK" if mock else "OPTIX"))
    dim_dam_obj = plat.dam.put(
        tenant_id=tenant_id,
        kind="commerce_asset",
        name="dimension_front.png",
        data=dim_png_bytes,
        metadata={
            "commerceRole": "COMMERCE_DIMENSION",
            "viewRole": "DIMENSION_FRONT",
            "renderPackId": product_truth_pack.get("renderPackId"),
            "sourceRenderPackId": product_truth_pack.get("renderPackId"),
            "sourceAcceptanceGenerationId": source_acc_gen_id,
            "contentPackId": pack_id,
            "sourcePath": str(dim_file.resolve()),
            "sourceJobId": str(fc_view["blenderJobId"]),
            "tenantId": tenant_id,
            "skuId": sku_id,
            "productVersion": version,
            "mime": "image/png",
            "blenderVersion": dim_b_version,
            "device": dim_b_device,
            "usedMock": mock,
            **dim_meta,
        },
    )
    dim_png_info = _png_meta(dim_file)
    views_output["DIMENSION_FRONT"] = {
        "viewRole": "DIMENSION_FRONT",
        "commerceRole": "COMMERCE_DIMENSION",
        "damRef": dim_dam_obj.asset_id,
        "path": str(dim_file.resolve()),
        "blenderJobId": fc_view["blenderJobId"],
        "recipe": recipes["DIMENSION_FRONT"],
        "articulatedState": build_articulated_state(engineering, state="CLOSED", angle_deg=0.0),
        "workerEvidence": dict(fc_view.get("workerEvidence") or {}),
        "blenderVersion": dim_b_version,
        "device": dim_b_device,
        "dimensionMetadata": dim_meta,
        "sha256": sha256_bytes(dim_png_bytes),
        "size": len(dim_png_bytes),
        "width": dim_png_info["width"],
        "height": dim_png_info["height"],
        "format": "PNG",
        "truthLabel": "REAL_LOGIC" if not mock else "MOCK",
        "usedMock": mock,
    }

    # 3. Structured Lifestyle Scene Briefs
    lifestyle_briefs = canonical_lifestyle_briefs(product_truth_pack)
    generative_brief_results: dict[str, Any] = {}
    for brief_name, brief_data in lifestyle_briefs.items():
        gen_res = plat.generative.submit(
            {
                "mode": "IMAGE",
                "preset": brief_name,
                "renderPackId": product_truth_pack.get("renderPackId"),
                "productLocked": True,
                "brief": brief_data,
            },
            pack=product_truth_pack,
        )
        generative_brief_results[brief_name] = {
            "brief": brief_data,
            "routing": gen_res.get("routing"),
            "status": "BLOCKED",
            "derivativeOnly": True,
            "isProductTruth": False,
            "truthLabel": "DERIVATIVE/BLOCKED",
            "liveH3MaxProviderReady": False,
            "liveLtx25ProviderReady": False,
        }

    # Extract masks for QA
    aovs = product_truth_pack.get("aovs") or {}
    prod_mask = aovs.get("product_mask") or {}
    art_mask = aovs.get("artwork_mask") or {}

    pack = {
        "contentPackId": pack_id,
        "tenantId": tenant_id,
        "skuId": sku_id,
        "productVersion": version,
        "engineeringHash": eng_hash,
        "artworkId": product_truth_pack.get("artworkId"),
        "placementId": product_truth_pack.get("placementId"),
        "placementHash": product_truth_pack.get("placementHash"),
        "finalUvHash": product_truth_pack.get("finalUvHash"),
        "sourceRenderPackId": product_truth_pack.get("renderPackId"),
        "sourceAcceptanceGenerationId": source_acc_gen_id,
        "productMaskRef": {"damRef": prod_mask.get("damRef"), "sha256": prod_mask.get("sha256")},
        "artworkMaskRef": {"damRef": art_mask.get("damRef"), "sha256": art_mask.get("sha256")},
        "width": width,
        "height": height,
        "samples": samples,
        "views": views_output,
        "lifestyleBriefs": generative_brief_results,
        "evidenceCodeCommit": evidence_code_commit,
        "generatedAt": utcnow().isoformat(),
        "usedMock": mock,
        "realBlender": not mock,
        "realOptix": not mock,
    }

    # Run QA gate
    qa_res = qa_commerce_pack(pack, engineering, product_truth_pack, plat)
    pack["qa"] = qa_res
    return pack


def run_product_content_scenario(
    plat: Any,
    *,
    tenant_id: str = "pt-a",
    evidence_code_commit: str | None = None,
) -> dict[str, Any]:
    """Full end-to-end scenario producing canonical Product Content Factory V1 assets."""
    from fox3d.product_truth import run_phase_841_scenario

    truth_res = run_phase_841_scenario(plat, tenant_id=tenant_id, evidence_code_commit=evidence_code_commit)
    upstream_pack = truth_res["pack"]
    eng = truth_res["frozenAuthorityContext"]["engineering"]

    truth_gen_id = None
    truth_acc_path = Path("docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json")
    if truth_acc_path.is_file():
        try:
            t_data = json.loads(truth_acc_path.read_text(encoding="utf-8"))
            if t_data.get("renderPackId") == upstream_pack.get("renderPackId"):
                truth_gen_id = t_data.get("acceptanceGenerationId")
        except Exception:
            pass
    if not truth_gen_id:
        truth_gen_id = upstream_pack.get("sourceAcceptanceGenerationId") or upstream_pack.get("acceptanceGenerationId") or f"pt_acc_{upstream_pack.get('renderPackId')}"
    upstream_pack["sourceAcceptanceGenerationId"] = truth_gen_id
    upstream_pack["acceptanceGenerationId"] = truth_gen_id

    mock = bool(getattr(plat, "mock_blender", True) or upstream_pack.get("usedMock"))
    width = 64 if mock else 128
    height = 64 if mock else 128
    samples = 8 if mock else 32

    content_pack = build_commerce_asset_pack(
        plat,
        product_truth_pack=upstream_pack,
        engineering=eng,
        width=width,
        height=height,
        samples=samples,
        evidence_code_commit=evidence_code_commit,
    )

    qa = content_pack.get("qa") or {}
    ok = bool(truth_res.get("ok") and qa.get("ok"))

    return {
        "ok": ok,
        "contentPack": content_pack,
        "productTruthPack": upstream_pack,
        "frozenEngineering": eng,
        "usedMock": mock,
        "productContentFactoryLogicReady": True,
        "realCommerceRenderPackReady": not mock and ok,
        "liveGenerativeCommerceReady": False,
        "commercialAssetProductionReady": False,
        "physicalPrintValidated": False,
        "liveFactoryExecutionReady": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "failures": list(qa.get("failures") or []),
    }
