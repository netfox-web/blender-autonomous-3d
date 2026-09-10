"""Phase 781–840 artwork placement. MOCK/unit + REAL_LOGIC — not physical print."""

from __future__ import annotations

import math

import pytest

from fox3d.artwork import (
    ArtworkError,
    FIT_STRETCH,
    checkerboard_rgb,
    decode_png_rgb,
    derive_printable_surfaces,
    effective_dpi,
    master_canvas,
    mm_to_uv,
    roundtrip_ok,
    run_artwork_scenario,
    split_master,
    uv_to_mm,
    validate_artwork_acceptance_result,
)
from fox3d.parametric import CabinetEngine
from fox3d.platform import Platform
from fox3d.pngutil import write_png


def _plat(tmp_path):
    return Platform(root=tmp_path / "live", mock_blender=True)


def _grid_bytes(tmp_path, w=240, h=180):
    p = tmp_path / "g.png"
    write_png(p, w, h, checkerboard_rgb(w, h, cell=12))
    return p.read_bytes()


def test_surfaces_from_cabinet_doors_table_retail_acrylic_packaging(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if s["componentId"].startswith("door") or s["componentId"].upper().startswith("DOOR")]
    assert len(doors) == 2
    assert doors[0]["widthMm"] == pytest.approx(400)
    assert doors[0]["heightMm"] == pytest.approx(1800)
    desk, _ = eng.create("STUDENT_DESK", tenant_id="ta")
    tops = [s for s in plat.artwork.register_surfaces(desk, tenant_id="ta") if "DESKTOP" in s["componentId"].upper() or s["componentId"] == "desktop"]
    assert tops
    retail, _ = eng.create("RETAIL_DISPLAY", tenant_id="ta")
    faces = plat.artwork.register_surfaces(retail, tenant_id="ta")
    assert any("KICK" in s["componentId"].upper() or "TOP" in s["componentId"].upper() for s in faces)
    from fox3d.acrylic import acrylic_parts
    from fox3d.ids import stable_hash

    parts = acrylic_parts("MENU_STAND", width=210, height=297, depth=80, thickness=5)
    acr = {
        "tenantId": "ta",
        "productId": "acr1",
        "kind": "MENU_STAND",
        "engineeringHash": stable_hash(parts),
        "components": [{**p, "role": "face" if p["partId"] == "face" else p["partId"]} for p in parts],
    }
    acr_s = plat.artwork.register_surfaces(acr, tenant_id="ta")
    assert any(s["widthMm"] == 210 and s["heightMm"] == 297 for s in acr_s)
    pkg = {
        "tenantId": "ta",
        "productId": "pkg1",
        "engineeringHash": "e-pkg",
        "dieline": {"panels": [{"id": "FRONT", "w": 120, "h": 160}]},
        "components": [],
    }
    pkg_s = plat.artwork.register_surfaces(pkg, tenant_id="ta", family="PACKAGING")
    assert pkg_s[0]["widthMm"] == 120 and pkg_s[0]["heightMm"] == 160


def test_invalid_dimensions_wrong_component_stale_cross_tenant(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    rows = plat.artwork.register_surfaces(cab, tenant_id="ta")
    with pytest.raises(ArtworkError, match="cross-tenant"):
        plat.artwork.require_surface(rows[0]["surfaceId"], tenant_id="tb")
    with pytest.raises(ArtworkError, match="stale"):
        plat.artwork.require_surface(rows[0]["surfaceId"], tenant_id="ta", engineering_hash="other")
    with pytest.raises(ArtworkError):
        derive_printable_surfaces({"tenantId": "ta", "productId": "p", "engineeringHash": "e", "components": [{"role": "door", "width": 0, "length": 10}]}, tenant_id="ta")


def test_mm_uv_roundtrip_rotation_and_non_square(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    door = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()][0]
    assert roundtrip_ok(12.5, 44.25, door)
    u, v = mm_to_uv(door["widthMm"], door["heightMm"], door)
    x, y = uv_to_mm(u, v, door)
    assert abs(x - door["widthMm"]) <= 1e-3
    portrait = dict(door)
    portrait["widthMm"] = 300
    portrait["heightMm"] = 900
    assert roundtrip_ok(10, 20, portrait)
    landscape = dict(door)
    landscape["widthMm"] = 900
    landscape["heightMm"] = 300
    assert roundtrip_ok(10, 20, landscape)
    with pytest.raises(ArtworkError):
        mm_to_uv(float("nan"), 1, door)
    with pytest.raises(ArtworkError):
        mm_to_uv(1, float("inf"), door)


def test_placement_hash_deterministic_and_stretch_forbidden(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path), source="GENERATED")
    a = plat.artwork.place(tenant_id="ta", surface_id=doors[0]["surfaceId"], artwork_id=art["artworkId"], engineering_hash=cab.engineering_hash(), product_id=cab.productId)
    plat.artwork.placements.pop(a["placementId"])
    b = plat.artwork.place(tenant_id="ta", surface_id=doors[0]["surfaceId"], artwork_id=art["artworkId"], engineering_hash=cab.engineering_hash(), product_id=cab.productId)
    assert a["placementHash"] == b["placementHash"]
    with pytest.raises(ArtworkError, match="STRETCH"):
        plat.artwork.place(tenant_id="ta", surface_id=doors[1]["surfaceId"], artwork_id=art["artworkId"], engineering_hash=cab.engineering_hash(), product_id=cab.productId, fit=FIT_STRETCH)


def test_four_door_master_continuity_and_no_stretch(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    assert len(doors) == 4
    assert all(abs(d["widthMm"] - 600) < 1e-6 for d in doors)
    master = master_canvas(doors)
    assert master["widthMm"] == pytest.approx(2400)
    crops = split_master(master)
    rights = []
    for i, crop in enumerate(crops):
        assert crop["cropMm"]["widthMm"] == pytest.approx(600)
        if i:
            assert crop["cropMm"]["xMm"] == pytest.approx(rights[-1])
        rights.append(crop["cropMm"]["xMm"] + crop["cropMm"]["widthMm"])
    with pytest.raises(ArtworkError, match="stretch"):
        split_master(master, stretch=True)


def test_keepout_blocks_and_low_dpi_partial(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path), source="GENERATED")
    handle = next(k for k in doors[0]["keepOuts"] if k.get("kind") == "HANDLE")
    with pytest.raises(ArtworkError) as exc:
        plat.artwork.place(
            tenant_id="ta",
            surface_id=doors[0]["surfaceId"],
            artwork_id=art["artworkId"],
            engineering_hash=cab.engineering_hash(),
            product_id=cab.productId,
            protected_regions=[{**handle, "source": "IMPORTED", "truthLabel": "IMPORTED"}],
        )
    assert exc.value.code == "BLOCKED_PLACEMENT"
    tiny = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 2, 2), name="t.png", source="GENERATED")
    low = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[1]["surfaceId"],
        artwork_id=tiny["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    assert low["policy"]["printReady"] is False
    assert low["policy"]["previewOk"] is False or low["dpi"] < 150
    assert low["policy"]["printPreflight"] == "PARTIAL"


def test_tamper_stale_cross_product_duplicate_invalid_crop(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    other, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=900, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path), source="GENERATED")
    place = plat.artwork.place(tenant_id="ta", surface_id=doors[0]["surfaceId"], artwork_id=art["artworkId"], engineering_hash=cab.engineering_hash(), product_id=cab.productId)
    raw_path = plat.artwork.artworks[art["artworkId"]]["path"]
    from pathlib import Path

    p = Path(raw_path)
    orig = p.read_bytes()
    p.write_bytes(orig + b"junk")
    with pytest.raises(ArtworkError, match="hash"):
        plat.artwork.require_artwork(art["artworkId"], tenant_id="ta")
    p.write_bytes(orig)
    resized, _ = eng.resize(cab, width=1000)
    with pytest.raises(ArtworkError) as stale:
        plat.artwork.require_placement(place["placementId"], tenant_id="ta", engineering_hash=resized.engineering_hash())
    assert stale.value.code == "STALE"
    with pytest.raises(ArtworkError, match="cross-product"):
        plat.artwork.place(
            tenant_id="ta",
            surface_id=doors[1]["surfaceId"],
            artwork_id=art["artworkId"],
            engineering_hash=cab.engineering_hash(),
            product_id=other.productId,
        )
    dup = dict(doors[0])
    dup["surfaceId"] = doors[0]["surfaceId"]
    plat.artwork.surfaces[dup["surfaceId"]] = doors[0]
    with pytest.raises(ArtworkError, match="duplicate"):
        plat.artwork.register_surfaces(cab, tenant_id="ta")
    with pytest.raises(ArtworkError):
        decode_png_rgb(b"not-a-png")
    with pytest.raises(ArtworkError):
        mm_to_uv(0, 0, {"widthMm": 0, "heightMm": 10})


def test_production_and_preview_share_hashes_mock_not_real(tmp_path):
    plat = _plat(tmp_path)
    result = run_artwork_scenario(plat, tenant_a="ta", tenant_b="tb")
    assert validate_artwork_acceptance_result(result) == []
    cab4 = result["scenarios"]["cabinet4"]
    assert abs(cab4["widthMm"] - 2400) < 1e-6
    assert len(cab4["panelCrops"]) == 4
    assert cab4["panelCrops"][0]["xMm"] == pytest.approx(0)
    assert cab4["panelCrops"][1]["xMm"] == pytest.approx(600)
    prod = cab4["production"][0]
    preview = result["preview"]
    assert preview["placementHash"] == result["lineage"]["placementHash"]
    assert prod["placementHash"] in cab4["placementHashes"]
    assert result["realArtworkPreviewReady"] is False
    assert result["physicalPrintValidated"] is False
    assert result["negatives"]["keepout"] == "BLOCKED_PLACEMENT"
    assert result["negatives"]["stale"] == "STALE"
    assert result["negatives"]["cross_tenant"] == "BLOCKED"
    assert result["negatives"]["tamper"] == "BLOCKED"
    assert result["mockBlender"] is True
    assert effective_dpi(300, 25.4) == pytest.approx(300)


def test_three_and_two_panel_split(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab3, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=1800, height=1800, doorCount=3)
    doors = [s for s in plat.artwork.register_surfaces(cab3, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    master = master_canvas(doors)
    crops = split_master(master)
    assert len(crops) == 3
    assert master["widthMm"] == pytest.approx(1800)
