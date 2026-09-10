"""Phase 781–840 artwork placement. MOCK/unit + REAL_LOGIC — not physical print."""

from __future__ import annotations

import math
from pathlib import Path

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
    eng_doors = [p for p in cab.components if p.get("role") == "door"]
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    doors.sort(key=lambda s: float(s["origin"]["xMm"]))
    assert len(doors) == 4
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_doors", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    layout = bj.door_layout_from_engineering(cab.model_dump(mode="json"))
    for i, door in enumerate(doors):
        assert door["widthMm"] == pytest.approx(eng_doors[i]["width"])
        assert door["heightMm"] == pytest.approx(eng_doors[i]["length"])
        assert layout[i]["widthMm"] == pytest.approx(door["widthMm"])
        assert layout[i]["heightMm"] == pytest.approx(door["heightMm"])
        assert abs(layout[i]["sizeM"][0] - 0.002) > 1e-9
    master = master_canvas(doors)
    assert master["widthMm"] == pytest.approx(sum(d["widthMm"] for d in doors))
    crops = split_master(master)
    rights = []
    for i, crop in enumerate(crops):
        assert crop["cropMm"]["widthMm"] == pytest.approx(eng_doors[i]["width"])
        if i:
            assert crop["cropMm"]["xMm"] == pytest.approx(rights[-1])
        rights.append(crop["cropMm"]["xMm"] + crop["cropMm"]["widthMm"])
    with pytest.raises(ArtworkError, match="stretch"):
        split_master(master, stretch=True)
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    _m, _c, places = plat.artwork.place_across_panels(
        tenant_id="ta",
        artwork_id=art["artworkId"],
        surfaces=doors,
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    assert [round(p["uv"]["u0"], 6) for p in places] == [0.0, 0.25, 0.5, 0.75]
    assert [round(p["uv"]["u1"], 6) for p in places] == [0.25, 0.5, 0.75, 1.0]


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
    cab2, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    cab3, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=1800, height=1800, doorCount=3)
    cab4, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    for cab, n in ((cab2, 2), (cab3, 3), (cab4, 4)):
        doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
        master = master_canvas(doors)
        crops = split_master(master)
        assert len(crops) == n
        assert master["widthMm"] == pytest.approx(sum(d["widthMm"] for d in doors))
        for i in range(1, n):
            assert crops[i]["cropMm"]["xMm"] == pytest.approx(crops[i - 1]["cropMm"]["xMm"] + crops[i - 1]["cropMm"]["widthMm"])


def test_rotation_changes_mapping_and_unsupported_is_blocked(tmp_path):
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_uv", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    uv = {"u0": 0.1, "v0": 0.2, "u1": 0.4, "v1": 0.8}
    a = bj.canonical_uv_mapping(uv, rotation_deg=0)
    b = bj.canonical_uv_mapping(uv, rotation_deg=90)
    assert a["corners"] != b["corners"]
    with pytest.raises(bj.ArtworkApplyError):
        bj.canonical_uv_mapping(uv, rotation_deg=45)
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    door = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()][0]
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path), source="GENERATED")
    with pytest.raises(ArtworkError, match="unsupported rotation"):
        plat.artwork.place(
            tenant_id="ta",
            surface_id=door["surfaceId"],
            artwork_id=art["artworkId"],
            engineering_hash=cab.engineering_hash(),
            product_id=cab.productId,
            rotation_deg=33,
        )


def test_blender_apply_consumes_uv_and_fails_closed(tmp_path):
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_apply", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    art = tmp_path / "a.png"
    write_png(art, 8, 8, checkerboard_rgb(8, 8, cell=2))
    item = {
        "objectName": "DOOR_1",
        "imagePath": str(art),
        "uvRect": {"u0": 0.0, "v0": 0.0, "u1": 0.25, "v1": 1.0},
        "rotationDeg": 0,
        "engineeringHash": "e",
        "surfaceHash": "s",
        "artworkHash": "a",
        "placementHash": "p1",
    }
    applied = bj.apply_canonical_artwork({"DOOR_1": {}}, {"artworkPlacements": [item]})
    assert applied[0]["applied"] is True
    item2 = dict(item)
    item2["uvRect"] = {"u0": 0.25, "v0": 0.0, "u1": 0.5, "v1": 1.0}
    item2["placementHash"] = "p2"
    applied2 = bj.apply_canonical_artwork({"DOOR_1": {}}, {"artworkPlacements": [item2]})
    assert applied[0]["corners"] != applied2[0]["corners"]
    with pytest.raises(bj.ArtworkApplyError):
        bj.apply_canonical_artwork({}, {"artworkPlacements": [item]})
    missing = dict(item)
    missing.pop("uvRect")
    with pytest.raises(bj.ArtworkApplyError):
        bj.apply_canonical_artwork({"DOOR_1": {}}, {"artworkPlacements": [missing]})


def test_forged_production_crop_blocks(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    _master, _crops, places = plat.artwork.place_across_panels(
        tenant_id="ta",
        artwork_id=art["artworkId"],
        surfaces=doors,
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.produce_panel(
            tenant_id="ta",
            placement_id=places[0]["placementId"],
            placement_hash=places[0]["placementHash"],
            crop={"cropMm": {"xMm": 12, "yMm": 0, "widthMm": 9, "heightMm": 9}, "surfaceHash": places[0]["surfaceHash"]},
            master={"masterHash": places[0].get("masterHash")},
        )
    with pytest.raises(ArtworkError):
        plat.artwork.produce_panel(tenant_id="ta", placement_id=places[0]["placementId"], placement_hash="forged-hash")


def test_dpi_uses_limiting_axis(tmp_path):
    assert effective_dpi(100, 25.4, 50, 50.8) == pytest.approx(25.0)
    assert effective_dpi(300, 25.4) == pytest.approx(300)


def test_cross_version_and_resize_invalidates_lineage(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    with pytest.raises(ArtworkError, match="cross-version"):
        plat.artwork.require_surface(doors[0]["surfaceId"], tenant_id="ta", version="nope")
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path), source="GENERATED")
    place = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    resized, _ = eng.resize(cab, width=1000)
    with pytest.raises(ArtworkError) as exc:
        plat.artwork.require_placement(place["placementId"], tenant_id="ta", engineering_hash=resized.engineering_hash())
    assert exc.value.code == "STALE"
