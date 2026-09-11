"""Phase 781–840 artwork placement. MOCK/unit + REAL_LOGIC — not physical print."""

from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

from fox3d.artwork import (
    ArtworkError,
    FIT_CONTAIN,
    FIT_COVER,
    FIT_STRETCH,
    canonical_final_sampling,
    canonical_orientation_expected,
    checkerboard_rgb,
    decode_png_rgb,
    derived_master_id,
    derive_printable_surfaces,
    effective_dpi,
    final_uv_identity,
    landmark_grid_rgb,
    master_canvas,
    master_relation_hash,
    measure_orientation_parity,
    oracle_quality,
    mm_to_uv,
    placement_payload,
    preview_ready_from_job,
    probe_canonical_geometry_tampers,
    probe_coordinated_oracle_tampers,
    probe_near_tolerance_oracle_tampers,
    probe_serialized_orientation_tampers,
    probe_strict_type_tampers,
    quarter_turn_local_corners,
    roundtrip_ok,
    run_artwork_scenario,
    split_master,
    uv_corners_in_rect,
    uv_to_mm,
    validate_artwork_acceptance_result,
)
from fox3d.ids import sha256_bytes, stable_hash
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
        "artworkSha256": sha256_bytes(art.read_bytes()),
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


def test_canonical_uv_is_single_transform_and_identity_shader():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_uv_auth", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    expected = [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0)]
    for u0, u1 in expected:
        mapping = bj.canonical_uv_mapping({"u0": u0, "v0": 0.0, "u1": u1, "v1": 1.0})
        assert mapping["mappingMode"] == "MESH_UV"
        assert mapping["shaderMapping"]["location"] == (0.0, 0.0, 0.0)
        assert mapping["shaderMapping"]["scale"] == (1.0, 1.0, 1.0)
        assert mapping["shaderMapping"]["rotation"] == (0.0, 0.0, 0.0)
        assert mapping["finalSampling"] == mapping["corners"]
        assert mapping["corners"] == [(u0, 0.0), (u1, 0.0), (u1, 1.0), (u0, 1.0)]
        assert bj.final_uv_sampling(mapping) == mapping["corners"]
    rotated = bj.canonical_uv_mapping({"u0": 0.0, "v0": 0.0, "u1": 0.25, "v1": 1.0}, rotation_deg=90)
    assert rotated["shaderMapping"]["rotation"] == (0.0, 0.0, 0.0)
    assert rotated["corners"] != [(0.0, 0.0), (0.25, 0.0), (0.25, 1.0), (0.0, 1.0)]
    mirrored = bj.canonical_uv_mapping({"u0": 0.0, "v0": 0.0, "u1": 0.25, "v1": 1.0}, mirrored=True)
    assert mirrored["corners"][0][0] == pytest.approx(0.25)


def test_artwork_applies_only_unique_front_face(tmp_path):
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_front", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    art = tmp_path / "a.png"
    write_png(art, 8, 8, checkerboard_rgb(8, 8, cell=2))
    mesh = {
        "materials": ["base"],
        "polygons": bj.cube_polygons_local(),
        "uv_loops": [(0.0, 0.0)] * 24,
    }
    item = {
        "objectName": "DOOR_1",
        "imagePath": str(art),
        "artworkSha256": sha256_bytes(art.read_bytes()),
        "uvRect": {"u0": 0.25, "v0": 0.0, "u1": 0.5, "v1": 1.0},
        "rotationDeg": 0,
        "engineeringHash": "e",
        "surfaceHash": "s",
        "artworkHash": "a",
        "placementHash": "p1",
        "face": "FRONT",
    }
    applied = bj.apply_canonical_artwork({"DOOR_1": mesh}, {"artworkPlacements": [item]})
    assert applied[0]["applied"] is True
    assert applied[0]["frontFaceIndex"] == 0
    assert mesh["polygons"][0]["material_index"] == 1
    assert mesh["polygons"][0]["uv"] == applied[0]["finalSampling"]
    for poly in mesh["polygons"][1:]:
        assert poly["material_index"] == 0
        assert not poly.get("uv")
    dup = {
        "materials": ["base"],
        "polygons": bj.cube_polygons_local() + [{"index": 9, "normal": (0.0, -1.0, 0.0), "loop_start": 24, "loop_total": 4, "material_index": 0}],
    }
    with pytest.raises(bj.ArtworkApplyError, match="unique FRONT"):
        bj.apply_canonical_artwork({"DOOR_1": dup}, {"artworkPlacements": [item]})
    empty = {"materials": ["base"], "polygons": [p for p in bj.cube_polygons_local() if p["index"] != 0]}
    with pytest.raises(bj.ArtworkApplyError, match="unique FRONT"):
        bj.apply_canonical_artwork({"DOOR_1": empty}, {"artworkPlacements": [item]})


def _preview_identity(**overrides):
    uv = {"u0": 0.0, "v0": 0.0, "u1": 0.25, "v1": 1.0}
    ident = final_uv_identity(
        placement_id="pl-1",
        object_name="DOOR_1",
        component_id="DOOR_1",
        face="FRONT",
        relation="SINGLE_SURFACE",
        uv_rect=uv,
        rotation_deg=0.0,
        mirrored=False,
    )
    row = {
        "applied": True,
        "placementId": "pl-1",
        "objectName": "DOOR_1",
        "componentId": "DOOR_1",
        "face": "FRONT",
        "relation": "SINGLE_SURFACE",
        "engineeringHash": "e",
        "surfaceHash": "s",
        "artworkHash": "a",
        "placementHash": "p",
        "finalUvHash": ident["finalUvHash"],
        "finalSampling": ident["finalSampling"],
        "uvRect": ident["uvRect"],
    }
    row.update(overrides)
    return row


def _preview_job(applied, **overrides):
    job = {
        "status": "succeeded",
        "artworkApplied": True,
        "appliedPlacements": applied,
        "realBlender": True,
        "usedMock": False,
        "blenderVersion": "5.2.1",
        "jobId": "job-1",
        "device": "OPTIX",
        "outputHash": "b" * 64,
        "outputSize": 4096,
    }
    job.update(overrides)
    return job


def test_preview_ready_fail_closed_without_artwork_applied():
    requested = _preview_identity()
    applied = [_preview_identity()]
    incomplete = {
        "status": "succeeded",
        "artworkApplied": True,
        "appliedPlacements": [{"engineeringHash": "e", "surfaceHash": "s", "artworkHash": "a", "placementHash": "p", "applied": True}],
        "realBlender": True,
        "usedMock": False,
        "blenderVersion": "5.2.1",
        "jobId": "job-1",
    }
    assert preview_ready_from_job(incomplete, {"engineeringHash": "e", "surfaceHash": "s", "artworkHash": "a", "placementHash": "p"}, mock=False) is False
    ok = _preview_job(applied)
    assert preview_ready_from_job(ok, requested, mock=False) is True
    missing = dict(ok)
    missing.pop("artworkApplied")
    assert preview_ready_from_job(missing, requested, mock=False) is False
    assert preview_ready_from_job({**ok, "artworkApplied": False}, requested, mock=False) is False
    no_lineage = dict(ok)
    no_lineage["appliedPlacements"] = []
    assert preview_ready_from_job(no_lineage, requested, mock=False) is False
    wrong = dict(ok)
    wrong["appliedPlacements"] = [{**applied[0], "placementHash": "other"}]
    assert preview_ready_from_job(wrong, requested, mock=False) is False
    extra = dict(ok)
    extra["appliedPlacements"] = applied + [{**applied[0], "placementId": "pl-2", "placementHash": "p2", "finalUvHash": "x"}]
    assert preview_ready_from_job(extra, requested, mock=False) is False
    assert preview_ready_from_job({**ok, "device": None}, requested, mock=False) is False
    assert preview_ready_from_job({**ok, "device": ""}, requested, mock=False) is False
    assert preview_ready_from_job({**ok, "outputHash": None}, requested, mock=False) is False
    assert preview_ready_from_job({**ok, "outputSize": 0}, requested, mock=False) is False
    assert preview_ready_from_job(_preview_job([{**applied[0], "objectName": "OTHER"}], **{}), requested, mock=False) is False
    assert preview_ready_from_job(_preview_job([{**applied[0], "componentId": "DOOR_9"}]), requested, mock=False) is False
    assert preview_ready_from_job(_preview_job([{**applied[0], "face": "BACK"}]), requested, mock=False) is False
    assert preview_ready_from_job(_preview_job([{**applied[0], "relation": "MASTER_SPLIT"}]), requested, mock=False) is False
    assert preview_ready_from_job(_preview_job([{**applied[0], "finalUvHash": "not-the-hash"}]), requested, mock=False) is False
    tampered_uv = _preview_identity(finalSampling=[[0.9, 0.9], [1.0, 0.9], [1.0, 1.0], [0.9, 1.0]])
    assert preview_ready_from_job(_preview_job([tampered_uv]), requested, mock=False) is False
    dup = dict(ok)
    dup["appliedPlacements"] = [applied[0], dict(applied[0])]
    assert preview_ready_from_job(dup, requested, mock=False) is False
    missing_applied = dict(ok)
    missing_applied["appliedPlacements"] = []
    assert preview_ready_from_job(missing_applied, {"placements": [requested, {**requested, "placementId": "pl-2"}]}, mock=False) is False


def test_final_uv_hash_is_deterministic_not_repr():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_uv_hash", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    uv = {"u0": 0.0, "v0": 0.0, "u1": 0.25, "v1": 1.0}
    mapping = bj.canonical_uv_mapping(uv, rotation_deg=90, mirrored=True)
    item = {
        "placementId": "pl-1",
        "objectName": "DOOR_1",
        "componentId": "DOOR_1",
        "face": "FRONT",
        "relation": "SINGLE_SURFACE",
        "uvRect": uv,
    }
    digest = bj.compute_final_uv_hash(item, mapping)
    expected = final_uv_identity(
        placement_id="pl-1",
        object_name="DOOR_1",
        component_id="DOOR_1",
        face="FRONT",
        relation="SINGLE_SURFACE",
        uv_rect=uv,
        rotation_deg=90,
        mirrored=True,
    )
    assert digest == expected["finalUvHash"]
    assert digest != str(mapping.get("finalSampling"))
    assert len(digest) == 64


def test_placement_hash_binds_uv_mirror_and_object(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    doors.sort(key=lambda s: float(s["origin"]["xMm"]))
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    place = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[1]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    pid = place["placementId"]
    rec = plat.artwork.placements[pid]
    orig = {
        "uv": dict(rec["uv"]),
        "mirrored": rec.get("mirrored"),
        "widthMm": rec["widthMm"],
        "objectName": rec.get("objectName"),
        "componentId": rec.get("componentId"),
        "placementHash": rec.get("placementHash"),
    }
    rec["uv"] = {**rec["uv"], "u0": 0.9}
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.require_placement(pid, tenant_id="ta")
    rec["uv"] = dict(orig["uv"])
    rec["mirrored"] = True
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.require_placement(pid, tenant_id="ta")
    rec["mirrored"] = orig["mirrored"]
    rec["uv"] = {"u0": 0.0, "v0": 0.0, "u1": 0.1, "v1": 0.1}
    rec["widthMm"] = float(orig["widthMm"]) * 0.1
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.require_placement(pid, tenant_id="ta")
    rec["uv"] = dict(orig["uv"])
    rec["widthMm"] = orig["widthMm"]
    rec["objectName"] = "OTHER_DOOR"
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.require_placement(pid, tenant_id="ta")
    rec["objectName"] = orig["objectName"]
    rec["componentId"] = "OTHER"
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.blender_job_payload(tenant_id="ta", placements=[{"placementId": pid}])
    rec["componentId"] = orig["componentId"]
    payload = plat.artwork.blender_job_payload(tenant_id="ta", placements=[{"placementId": pid}])
    assert payload["artworkPlacements"][0]["uvRect"] == orig["uv"]
    with pytest.raises(ArtworkError, match="placementId required"):
        plat.artwork.blender_job_payload(tenant_id="ta", placements=[{"uvRect": {"u0": 0}}])


def test_single_surface_door_is_not_master_quarter(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    doors.sort(key=lambda s: float(s["origin"]["xMm"]))
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    _master, _crops, places = plat.artwork.place_across_panels(
        tenant_id="ta",
        artwork_id=art["artworkId"],
        surfaces=doors,
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    split = plat.artwork.produce_panel(
        tenant_id="ta",
        placement_id=places[1]["placementId"],
        placement_hash=places[1]["placementHash"],
        engineering_hash=cab.engineering_hash(),
    )
    single = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[1]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    assert single["relation"] == "SINGLE_SURFACE"
    full = plat.artwork.produce_panel(
        tenant_id="ta",
        placement_id=single["placementId"],
        placement_hash=single["placementHash"],
        engineering_hash=cab.engineering_hash(),
    )
    assert full["masterHash"] is None
    assert full["cropPx"]["x"] == 0
    assert full["cropPx"]["w"] == 480
    assert split["cropPx"]["w"] == 120
    assert split["cropPx"]["x"] == 120
    with pytest.raises(ArtworkError, match="single-surface cannot use master"):
        plat.artwork.produce_panel(
            tenant_id="ta",
            placement_id=single["placementId"],
            master={"masterHash": places[1]["masterHash"]},
        )
    rec = plat.artwork.placements[places[1]["placementId"]]
    rec["masterCropMm"] = {"xMm": 0, "yMm": 0, "widthMm": 1, "heightMm": 1}
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.require_placement(places[1]["placementId"], tenant_id="ta")


def test_single_surface_crop_ignores_coordinated_stored_crop(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    doors.sort(key=lambda s: float(s["origin"]["xMm"]))
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    single = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[1]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    full = plat.artwork.produce_panel(
        tenant_id="ta",
        placement_id=single["placementId"],
        placement_hash=single["placementHash"],
        engineering_hash=cab.engineering_hash(),
    )
    assert full["cropPx"]["x"] == 0
    assert full["cropPx"]["w"] == 480
    rec = plat.artwork.placements[single["placementId"]]
    rec["crop"] = {**dict(rec.get("crop") or {}), "sourceXPx": 120, "sourceWPx": 120, "sourceYPx": 0, "sourceHPx": 360}
    rec["placementHash"] = stable_hash(placement_payload(rec))
    with pytest.raises(ArtworkError, match="forged source crop"):
        plat.artwork.produce_panel(
            tenant_id="ta",
            placement_id=single["placementId"],
            placement_hash=rec["placementHash"],
            engineering_hash=cab.engineering_hash(),
        )


def test_master_relation_blocks_coordinated_surface_set_tamper(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    doors.sort(key=lambda s: float(s["origin"]["xMm"]))
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    master, _crops, places = plat.artwork.place_across_panels(
        tenant_id="ta",
        artwork_id=art["artworkId"],
        surfaces=doors,
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    split = plat.artwork.produce_panel(
        tenant_id="ta",
        placement_id=places[1]["placementId"],
        placement_hash=places[1]["placementHash"],
        engineering_hash=cab.engineering_hash(),
    )
    assert split["cropPx"]["w"] == 120
    rec = plat.artwork.placements[places[1]["placementId"]]
    subset = doors[:2]
    forged_master = master_canvas(subset)
    rec["masterSurfaceIds"] = [s["surfaceId"] for s in subset]
    rec["masterHash"] = forged_master["masterHash"]
    rec["placementHash"] = stable_hash(placement_payload(rec))
    with pytest.raises(ArtworkError, match="master"):
        plat.artwork.produce_panel(
            tenant_id="ta",
            placement_id=places[1]["placementId"],
            placement_hash=rec["placementHash"],
            engineering_hash=cab.engineering_hash(),
        )
    rec2 = plat.artwork.placements[places[0]["placementId"]]
    orig_ids = list(rec2["masterSurfaceIds"])
    rec2["masterSurfaceIds"] = list(reversed(orig_ids))
    rec2["placementHash"] = stable_hash(placement_payload(rec2))
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.require_placement(places[0]["placementId"], tenant_id="ta")


def test_validator_fail_closed_on_count_and_uv(tmp_path):
    plat = _plat(tmp_path)
    result = run_artwork_scenario(plat, tenant_a="ta", tenant_b="tb")
    assert validate_artwork_acceptance_result(result) == []
    assert result["scenarios"]["cabinet4Single"]["relation"] == "SINGLE_SURFACE"
    crops_only = dict(result)
    crops_only["scenarios"] = dict(result["scenarios"])
    crops_only["scenarios"]["cabinet4"] = dict(result["scenarios"]["cabinet4"])
    crops_only["scenarios"]["cabinet4"]["panelCrops"] = result["scenarios"]["cabinet4"]["panelCrops"][:3]
    assert "split_4" in validate_artwork_acceptance_result(crops_only)
    ids_only = dict(result)
    ids_only["scenarios"] = dict(result["scenarios"])
    ids_only["scenarios"]["cabinet4"] = dict(result["scenarios"]["cabinet4"])
    ids_only["scenarios"]["cabinet4"]["surfaceIds"] = result["scenarios"]["cabinet4"]["surfaceIds"][:3]
    assert "split_4" in validate_artwork_acceptance_result(ids_only)
    dup = dict(result)
    dup["scenarios"] = dict(result["scenarios"])
    dup["scenarios"]["cabinet4"] = dict(result["scenarios"]["cabinet4"])
    hashes = list(result["scenarios"]["cabinet4"]["placementHashes"])
    hashes[3] = hashes[0]
    dup["scenarios"]["cabinet4"]["placementHashes"] = hashes
    assert "duplicate_placement" in validate_artwork_acceptance_result(dup)
    uv = dict(result)
    uv["scenarios"] = dict(result["scenarios"])
    uv["scenarios"]["cabinet4"] = dict(result["scenarios"]["cabinet4"])
    applied = [dict(row) for row in result["scenarios"]["cabinet4"]["appliedUv"]]
    applied[0] = dict(applied[0])
    applied[0]["uvRect"] = dict(applied[0]["uvRect"])
    applied[0]["uvRect"]["u0"] = 0.99
    uv["scenarios"]["cabinet4"]["appliedUv"] = applied
    assert "wrong_final_uv" in validate_artwork_acceptance_result(uv)
    preview = dict(result)
    preview["preview"] = dict(result["preview"])
    preview["preview"]["status"] = "succeeded"
    preview["preview"]["realBlender"] = True
    assert "preview_missing_artworkApplied" in validate_artwork_acceptance_result(preview)


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


def _rgb_at(data: bytes, x: int, y: int) -> tuple[int, int, int]:
    w, h, rgb = decode_png_rgb(data)
    i = (y * w + x) * 3
    return (rgb[i], rgb[i + 1], rgb[i + 2])


def test_preview_blocks_caller_forged_artwork_and_wrong_path(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    other = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 64, 48), name="other.png", source="GENERATED")
    place = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    forged = dict(place)
    forged["artworkId"] = other["artworkId"]
    with pytest.raises(ArtworkError, match="forged artworkId"):
        plat.artwork.preview(tenant_id="ta", placement=forged)
    forged_eng = dict(place)
    forged_eng["engineeringHash"] = "other-eng"
    with pytest.raises(ArtworkError, match="forged engineeringHash"):
        plat.artwork.preview(tenant_id="ta", placement=forged_eng)
    forged_prod = dict(place)
    forged_prod["productId"] = "other-product"
    with pytest.raises(ArtworkError, match="forged productId"):
        plat.artwork.preview(tenant_id="ta", placement=forged_prod)
    with pytest.raises(ArtworkError, match="digest"):
        plat.artwork.blender_job_payload(
            tenant_id="ta",
            placement_ids=[place["placementId"]],
            artwork_path=str(other["path"]),
        )
    payload = plat.artwork.blender_job_payload(tenant_id="ta", placement_ids=[place["placementId"]])
    assert payload["artworkPlacements"][0]["artworkSha256"] == art["sha256"]
    assert payload["artworkPlacements"][0]["imagePath"] == str(art["path"])
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_digest", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    item = dict(payload["artworkPlacements"][0])
    applied = bj.apply_canonical_artwork({item["objectName"]: {}}, {"artworkPlacements": [item]})
    assert applied[0]["applied"] is True
    assert applied[0]["artworkSha256"] == art["sha256"]
    Path(item["imagePath"]).write_bytes(Path(other["path"]).read_bytes())
    with pytest.raises(bj.ArtworkApplyError, match="digest"):
        bj.apply_canonical_artwork({item["objectName"]: {}}, {"artworkPlacements": [item]})


def test_contain_cover_anchor_rotation_production_parity(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    contain_center = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
        fit=FIT_CONTAIN,
        anchor="CENTER",
    )
    prod = plat.artwork.produce_panel(
        tenant_id="ta",
        placement_id=contain_center["placementId"],
        placement_hash=contain_center["placementHash"],
        engineering_hash=cab.engineering_hash(),
    )
    assert prod["outputPhysicalMm"]["widthMm"] == pytest.approx(doors[0]["widthMm"])
    assert prod["outputPhysicalMm"]["heightMm"] == pytest.approx(doors[0]["heightMm"])
    assert prod["canvasPx"]["w"] == prod["pixelWidth"]
    assert prod["placedArtworkMm"]["widthMm"] < doors[0]["widthMm"] or prod["placedArtworkMm"]["heightMm"] < doors[0]["heightMm"]
    raw = Path(plat.root / "artwork-out" / f"{doors[0]['surfaceId']}.png").read_bytes()
    w, h, rgb = decode_png_rgb(raw)
    assert w == prod["pixelWidth"] and h == prod["pixelHeight"]
    assert _rgb_at(raw, 2, 2) == (0, 0, 0)
    mid_x = int(round((prod["placedArtworkMm"]["xMm"] + prod["placedArtworkMm"]["widthMm"] / 2) * (w / doors[0]["widthMm"])))
    mid_y = int(round((doors[0]["heightMm"] - prod["placedArtworkMm"]["yMm"] - prod["placedArtworkMm"]["heightMm"] / 2) * (h / doors[0]["heightMm"])))
    assert _rgb_at(raw, mid_x, mid_y) != (0, 0, 0)
    top = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
        fit=FIT_CONTAIN,
        anchor="TOP_LEFT",
    )
    bottom = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
        fit=FIT_CONTAIN,
        anchor="BOTTOM_LEFT",
    )
    assert top["yMm"] > bottom["yMm"]
    cover_left = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[1]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
        fit=FIT_COVER,
        anchor="BOTTOM_LEFT",
    )
    cover_right = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[1]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
        fit=FIT_COVER,
        anchor="BOTTOM_RIGHT",
    )
    assert cover_left["crop"]["sourceXPx"] < cover_right["crop"]["sourceXPx"]
    rot = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
        fit=FIT_CONTAIN,
        anchor="CENTER",
        rotation_deg=90,
    )
    rot_prod = plat.artwork.produce_panel(
        tenant_id="ta",
        placement_id=rot["placementId"],
        placement_hash=rot["placementHash"],
        engineering_hash=cab.engineering_hash(),
    )
    ident = plat.artwork.applied_identity(plat.artwork.require_placement(rot["placementId"], tenant_id="ta"))
    assert rot_prod["finalUvHash"] == ident["finalUvHash"]
    assert rot_prod["rotationDeg"] == 90.0
    rec = plat.artwork.placements[contain_center["placementId"]]
    rec["anchor"] = "TOP_RIGHT"
    rec["placementHash"] = stable_hash(placement_payload(rec))
    with pytest.raises(ArtworkError, match="forged"):
        plat.artwork.produce_panel(
            tenant_id="ta",
            placement_id=contain_center["placementId"],
            placement_hash=rec["placementHash"],
            engineering_hash=cab.engineering_hash(),
        )


def test_master_seam_round_trip_and_relation_integrity(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    doors.sort(key=lambda s: float(s["origin"]["xMm"]))
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    master, crops, places = plat.artwork.place_across_panels(
        tenant_id="ta",
        artwork_id=art["artworkId"],
        surfaces=doors,
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
        seam_mm=40.0,
    )
    assert master["seamMm"] == pytest.approx(40.0)
    assert master["seamSource"] == "CONFIG"
    out = plat.artwork.produce_panel(
        tenant_id="ta",
        placement_id=places[0]["placementId"],
        placement_hash=places[0]["placementHash"],
        engineering_hash=cab.engineering_hash(),
    )
    assert out["productionArtworkFileReady"] is True
    rel = plat.artwork.masters[master["masterHash"]]
    rel["seamMm"] = 99.0
    with pytest.raises(ArtworkError, match="relationHash|seam"):
        plat.artwork.require_placement(places[0]["placementId"], tenant_id="ta")
    rel["seamMm"] = 40.0
    rel["panelOrder"] = list(reversed(list(rel["panelOrder"])))
    with pytest.raises(ArtworkError, match="relationHash|panelOrder"):
        plat.artwork.require_placement(places[1]["placementId"], tenant_id="ta")
    rel["panelOrder"] = [p.get("componentId") for p in master["panels"]]
    rec = plat.artwork.placements[places[2]["placementId"]]
    rec["masterId"] = ""
    rec["placementHash"] = stable_hash(placement_payload(rec))
    with pytest.raises(ArtworkError, match="masterId"):
        plat.artwork.require_placement(places[2]["placementId"], tenant_id="ta")


def test_nonsquare_uv_quarter_turn_stays_in_bounds():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_local_uv", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    rects = [
        {"u0": 0.0, "v0": 0.375, "u1": 1.0, "v1": 0.625},
        {"u0": 0.0, "v0": 0.0, "u1": 0.25, "v1": 1.0},
    ]
    for uv in rects:
        for rot in (0.0, 90.0, 180.0, 270.0):
            for mirrored in (False, True):
                got = canonical_final_sampling(uv, rotation_deg=rot, mirrored=mirrored)
                assert uv_corners_in_rect(got, uv)
                worker = bj.canonical_uv_mapping(uv, rotation_deg=rot, mirrored=mirrored)
                for a, b in zip(got, worker["finalSampling"], strict=True):
                    assert a[0] == pytest.approx(b[0])
                    assert a[1] == pytest.approx(b[1])
        acc = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        for _ in range(4):
            acc = [(1.0 - t, s) for s, t in acc]
        assert acc == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        with pytest.raises(ArtworkError, match="unsupported rotation"):
            canonical_final_sampling(uv, rotation_deg=45)


def test_orientation_pixel_oracle_contain(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    rgb = landmark_grid_rgb(48, 32)
    p = tmp_path / "lm.png"
    write_png(p, 48, 32, rgb)
    art = plat.artwork.register_artwork(tenant_id="ta", data=p.read_bytes(), source="GENERATED")
    for key, deg, mir in (("0", 0.0, False), ("90", 90.0, False), ("180", 180.0, False), ("270", 270.0, False), ("mirror", 0.0, True), ("mirror90", 90.0, True)):
        row = measure_orientation_parity(
            plat.artwork,
            tenant_id="ta",
            surface=doors[0],
            artwork=art,
            engineering_hash=cab.engineering_hash(),
            product_id=cab.productId,
            rotation_deg=deg,
            mirrored=mir,
            src_rgb=rgb,
            src_w=48,
            src_h=32,
        )
        assert row["status"] == "PASS", key
        assert row["boundsOk"] is True
        assert row["oracleDiscriminating"] is True
        assert row["uniqueSampleCount"] >= 3


def test_cover_center_oracle_discriminates_orientation(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    rgb = landmark_grid_rgb(48, 32)
    p = tmp_path / "lm.png"
    write_png(p, 48, 32, rgb)
    art = plat.artwork.register_artwork(tenant_id="ta", data=p.read_bytes(), source="GENERATED")
    rows = {}
    for key, deg, mir in (("0", 0.0, False), ("90", 90.0, False), ("180", 180.0, False), ("270", 270.0, False), ("mirror", 0.0, True), ("mirror90", 90.0, True)):
        rows[key] = measure_orientation_parity(
            plat.artwork,
            tenant_id="ta",
            surface=doors[0],
            artwork=art,
            engineering_hash=cab.engineering_hash(),
            product_id=cab.productId,
            rotation_deg=deg,
            mirrored=mir,
            src_rgb=rgb,
            src_w=48,
            src_h=32,
            fit=FIT_COVER,
            anchor="CENTER",
        )
        assert rows[key]["status"] == "PASS", key
        assert rows[key]["oracleDiscriminating"] is True
        assert rows[key]["uniqueSampleCount"] >= 3
        assert len(set(tuple(rows[key]["expected"][c]) for c in ("BL", "BR", "TR", "TL"))) >= 3
    assert rows["0"]["signature"] != rows["90"]["signature"]
    assert rows["0"]["signature"] != rows["180"]["signature"]
    assert rows["0"]["signature"] != rows["mirror"]["signature"]
    assert rows["90"]["signature"] != rows["mirror90"]["signature"]
    for corner in ("BL", "BR", "TR", "TL"):
        assert tuple(rows["0"]["expected"][corner]) != tuple(rows["90"]["observed"][corner]) or rows["0"]["signature"] != rows["90"]["signature"]
    gray = {"BL": [80, 80, 80], "BR": [80, 80, 80], "TR": [80, 80, 80], "TL": [80, 80, 80]}
    q = oracle_quality(gray)
    assert q["oracleDiscriminating"] is False
    assert q["uniqueSampleCount"] == 1


def test_cover_wrong_transform_is_caught(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=800, height=1800, doorCount=2)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    rgb = landmark_grid_rgb(48, 32)
    p = tmp_path / "lm.png"
    write_png(p, 48, 32, rgb)
    art = plat.artwork.register_artwork(tenant_id="ta", data=p.read_bytes(), source="GENERATED")

    def _one(anchor, deg, mir):
        return measure_orientation_parity(
            plat.artwork,
            tenant_id="ta",
            surface=doors[0],
            artwork=art,
            engineering_hash=cab.engineering_hash(),
            product_id=cab.productId,
            rotation_deg=deg,
            mirrored=mir,
            src_rgb=rgb,
            src_w=48,
            src_h=32,
            fit=FIT_COVER,
            anchor=anchor,
        )

    center0 = _one("CENTER", 0.0, False)
    center90 = _one("CENTER", 90.0, False)
    center_m = _one("CENTER", 0.0, True)
    left0 = _one("BOTTOM_LEFT", 0.0, False)
    left90 = _one("BOTTOM_LEFT", 90.0, False)
    right0 = _one("BOTTOM_RIGHT", 0.0, False)
    right_m = _one("BOTTOM_RIGHT", 0.0, True)
    assert center0["signature"] != center90["signature"]
    assert center0["signature"] != center_m["signature"]
    assert left0["signature"] != left90["signature"]
    assert right0["signature"] != right_m["signature"]
    mismatch = dict(center0)
    mismatch["observed"] = center90["observed"]
    mismatch["status"] = "PASS"
    fake = {"CONTAIN": {"CENTER": {"0": center0, "90": center0, "180": center0, "270": center0, "mirror": center0, "mirror90": center0}}, "COVER": {"LEFT": {"0": left0, "90": left0, "180": left0, "270": left0, "mirror": left0, "mirror90": left0}, "CENTER": {"0": mismatch, "90": mismatch, "180": mismatch, "270": mismatch, "mirror": mismatch, "mirror90": mismatch}, "RIGHT": {"0": right0, "90": right0, "180": right0, "270": right0, "mirror": right0, "mirror90": right0}}}
    # validator on a full result is heavy; check quality helper + signature inequality above
    assert oracle_quality(center0["expected"])["oracleDiscriminating"] is True


def test_master_id_bound_in_relation_hash(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    doors.sort(key=lambda s: float(s["origin"]["xMm"]))
    art = plat.artwork.register_artwork(tenant_id="ta", data=_grid_bytes(tmp_path, 480, 360), source="GENERATED")
    master, _crops, places = plat.artwork.place_across_panels(
        tenant_id="ta",
        artwork_id=art["artworkId"],
        surfaces=doors,
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    rel = plat.artwork.masters[master["masterHash"]]
    assert rel["masterId"] == derived_master_id(rel)
    plat.artwork.produce_panel(
        tenant_id="ta",
        placement_id=places[0]["placementId"],
        placement_hash=places[0]["placementHash"],
        engineering_hash=cab.engineering_hash(),
    )
    rel["masterId"] = "other-id"
    with pytest.raises(ArtworkError, match="masterId|relationHash"):
        plat.artwork.require_placement(places[0]["placementId"], tenant_id="ta")
    rel["masterId"] = "other-id"
    rel["relationHash"] = master_relation_hash(rel)
    for p in places:
        rec = plat.artwork.placements[p["placementId"]]
        rec["masterId"] = "other-id"
        rec["placementHash"] = stable_hash(placement_payload(rec))
    with pytest.raises(ArtworkError, match="masterId"):
        plat.artwork.require_placement(places[1]["placementId"], tenant_id="ta")


def test_validator_required_scenarios_fail_closed(tmp_path):
    plat = _plat(tmp_path)
    result = run_artwork_scenario(plat, tenant_a="ta", tenant_b="tb")
    assert validate_artwork_acceptance_result(result) == []
    for name in ("cabinet4Single", "containCenter", "coverAnchor", "orientationParity", "masterSeam"):
        missing = dict(result)
        missing["scenarios"] = dict(result["scenarios"])
        missing["scenarios"].pop(name, None)
        assert f"missing_{name}" in validate_artwork_acceptance_result(missing)
        empty = dict(result)
        empty["scenarios"] = dict(result["scenarios"])
        empty["scenarios"][name] = {}
        assert f"missing_{name}" in validate_artwork_acceptance_result(empty)
        badtype = dict(result)
        badtype["scenarios"] = dict(result["scenarios"])
        badtype["scenarios"][name] = []
        assert f"missing_{name}" in validate_artwork_acceptance_result(badtype)
    neg = dict(result)
    neg["negatives"] = dict(result["negatives"])
    neg["negatives"]["forged_preview_art"] = "passed"
    assert "negative_forged_preview_art" in validate_artwork_acceptance_result(neg)
    neg2 = dict(result)
    neg2["negatives"] = dict(result["negatives"])
    neg2["negatives"].pop("missing_masterId")
    assert "negative_missing_masterId" in validate_artwork_acceptance_result(neg2)
    orient = dict(result)
    orient["scenarios"] = dict(result["scenarios"])
    op = dict(result["scenarios"]["orientationParity"])
    contain = dict(op.get("CONTAIN") or {})
    center = dict(contain.get("CENTER") or {})
    center.pop("180", None)
    center.pop("270", None)
    center.pop("mirror", None)
    contain["CENTER"] = center
    op["CONTAIN"] = contain
    orient["scenarios"]["orientationParity"] = op
    fails = validate_artwork_acceptance_result(orient)
    assert "orientation_CONTAIN_CENTER_180" in fails
    assert "orientation_CONTAIN_CENTER_270" in fails
    assert "orientation_CONTAIN_CENTER_mirror" in fails
    deg = dict(result)
    deg["scenarios"] = dict(result["scenarios"])
    op2 = dict(result["scenarios"]["orientationParity"])
    cover = dict(op2.get("COVER") or {})
    center_c = dict(cover.get("CENTER") or {})
    gray_row = {
        "status": "PASS",
        "boundsOk": True,
        "expected": {"BL": [80, 80, 80], "BR": [80, 80, 80], "TR": [80, 80, 80], "TL": [80, 80, 80]},
        "observed": {"BL": [80, 80, 80], "BR": [80, 80, 80], "TR": [80, 80, 80], "TL": [80, 80, 80]},
        "uvRect": {"u0": 0.4, "v0": 0.0, "u1": 0.6, "v1": 1.0},
        "finalUvHash": "x",
        "oracleDiscriminating": False,
        "uniqueSampleCount": 1,
        "signature": "80,80,80|80,80,80|80,80,80|80,80,80",
    }
    for key, _d, _m in (("0", 0, False), ("90", 90, False), ("180", 180, False), ("270", 270, False), ("mirror", 0, True), ("mirror90", 90, True)):
        center_c[key] = dict(gray_row)
    cover["CENTER"] = center_c
    op2["COVER"] = cover
    deg["scenarios"]["orientationParity"] = op2
    deg_fails = validate_artwork_acceptance_result(deg)
    assert "orientation_COVER_CENTER_0_oracle_quality" in deg_fails
    assert "orientation_COVER_CENTER_not_discriminating" in deg_fails
    op_live = result["scenarios"]["orientationParity"]["COVER"]
    c0 = op_live["CENTER"]["0"]
    c90 = op_live["CENTER"]["90"]
    cm = op_live["CENTER"]["mirror"]
    l0 = op_live["LEFT"]["0"]
    l90 = op_live["LEFT"]["90"]
    r0 = op_live["RIGHT"]["0"]
    rm = op_live["RIGHT"]["mirror"]
    wrong_obs = copy.deepcopy(result)
    wrong_obs["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {**c0, "observed": c90["observed"], "status": "PASS"}
    assert any("pixel" in f or f.endswith("_pixel") for f in validate_artwork_acceptance_result(wrong_obs))
    wrong_mir = copy.deepcopy(result)
    wrong_mir["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {**c0, "observed": cm["observed"], "status": "PASS"}
    assert any("pixel" in f for f in validate_artwork_acceptance_result(wrong_mir))
    swapped = copy.deepcopy(result)
    swapped["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = dict(c90)
    swapped["scenarios"]["orientationParity"]["COVER"]["CENTER"]["90"] = dict(c0)
    swap_fails = validate_artwork_acceptance_result(swapped)
    assert any(f.endswith("_rotation") for f in swap_fails)
    left_wrong = copy.deepcopy(result)
    left_wrong["scenarios"]["orientationParity"]["COVER"]["LEFT"]["0"] = {**l0, "observed": l90["observed"], "status": "PASS"}
    assert any("pixel" in f for f in validate_artwork_acceptance_result(left_wrong))
    right_wrong = copy.deepcopy(result)
    right_wrong["scenarios"]["orientationParity"]["COVER"]["RIGHT"]["0"] = {**r0, "observed": rm["observed"], "status": "PASS"}
    assert any("pixel" in f for f in validate_artwork_acceptance_result(right_wrong))
    fake_meta = copy.deepcopy(result)
    fake_meta["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {**c0, "signature": "forged", "uniqueSampleCount": 99, "oracleDiscriminating": True, "status": "PASS"}
    fake_fails = validate_artwork_acceptance_result(fake_meta)
    assert any(f.endswith("_signature") or f.endswith("_unique") for f in fake_fails)
    bad_rot = copy.deepcopy(result)
    bad_rot["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {**c0, "rotationDeg": 90.0, "status": "PASS"}
    assert any(f.endswith("_rotation") for f in validate_artwork_acceptance_result(bad_rot))
    bad_fit = copy.deepcopy(result)
    bad_fit["scenarios"]["orientationParity"]["COVER"]["LEFT"]["0"] = {**l0, "fit": "CONTAIN", "status": "PASS"}
    assert any(f.endswith("_fit") for f in validate_artwork_acceptance_result(bad_fit))
    bad_anchor = copy.deepcopy(result)
    bad_anchor["scenarios"]["orientationParity"]["COVER"]["RIGHT"]["0"] = {**r0, "anchor": "CENTER", "status": "PASS"}
    assert any(f.endswith("_anchor") for f in validate_artwork_acceptance_result(bad_anchor))
    missing_gate = copy.deepcopy(result)
    missing_gate["serializedOrientationTamperBlocked"] = False
    assert "serialized_orientation_tamper" in validate_artwork_acceptance_result(missing_gate)
    assert result.get("serializedOrientationTamperBlocked") is True
    str_mirror = copy.deepcopy(result)
    str_mirror["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {**c0, "mirrored": "false", "status": "PASS"}
    assert any(f.endswith("_mirror") for f in validate_artwork_acceptance_result(str_mirror))
    int_mirror = copy.deepcopy(result)
    int_mirror["scenarios"]["orientationParity"]["COVER"]["CENTER"]["mirror"] = {**cm, "mirrored": 1, "status": "PASS"}
    assert any(f.endswith("_mirror") for f in validate_artwork_acceptance_result(int_mirror))
    str_rot = copy.deepcopy(result)
    str_rot["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {**c0, "rotationDeg": "0", "status": "PASS"}
    assert any(f.endswith("_rotation") for f in validate_artwork_acceptance_result(str_rot))
    bool_rot = copy.deepcopy(result)
    bool_rot["scenarios"]["orientationParity"]["COVER"]["CENTER"]["90"] = {**c90, "rotationDeg": True, "status": "PASS"}
    assert any(f.endswith("_rotation") for f in validate_artwork_acceptance_result(bool_rot))
    extra_ch = copy.deepcopy(result)
    extra_ch["scenarios"]["orientationParity"]["COVER"]["LEFT"]["0"] = {**l0, "expected": {**l0.get("expected", {}), "BL": [1, 2, 3, 4]}, "status": "PASS"}
    assert any(f.endswith("_rgb") for f in validate_artwork_acceptance_result(extra_ch))
    float_ch = copy.deepcopy(result)
    float_ch["scenarios"]["orientationParity"]["COVER"]["LEFT"]["0"] = {**l0, "expected": {**l0.get("expected", {}), "BL": [1.0, 2, 3]}, "status": "PASS"}
    assert any(f.endswith("_rgb") for f in validate_artwork_acceptance_result(float_ch))
    assert result.get("strictTypeTamperBlocked") is True
    assert result.get("coordinatedOracleTamperBlocked") is True
    for val in (0, "false", None):
        row = copy.deepcopy(result)
        row["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {**c0, "mirrored": val, "status": "PASS"}
        assert any(f.endswith("_mirror") for f in validate_artwork_acceptance_result(row)), val
    for val in (1, "true", "false"):
        row = copy.deepcopy(result)
        row["scenarios"]["orientationParity"]["COVER"]["CENTER"]["mirror"] = {**cm, "mirrored": val, "status": "PASS"}
        assert any(f.endswith("_mirror") for f in validate_artwork_acceptance_result(row)), val
    for val in ("0", "90", True, False, float("nan"), float("inf"), float("-inf")):
        row = copy.deepcopy(result)
        row["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {**c0, "rotationDeg": val, "status": "PASS"}
        assert any(f.endswith("_rotation") for f in validate_artwork_acceptance_result(row)), val

    def _rgb_case(target: str, corner_val):
        row = copy.deepcopy(result)
        base = dict(l0)
        corners = dict(base.get(target) or {})
        corners["BL"] = corner_val
        base[target] = corners
        base["status"] = "PASS"
        row["scenarios"]["orientationParity"]["COVER"]["LEFT"]["0"] = base
        return validate_artwork_acceptance_result(row)

    for target in ("expected", "observed"):
        for val in ([1, 2, 3, 4], [1.0, 2, 3], ["1", 2, 3], [True, 2, 3], [-1, 2, 3], [1, 2, 256]):
            assert any(f.endswith("_rgb") for f in _rgb_case(target, val)), (target, val)
    missing_type = copy.deepcopy(result)
    missing_type["strictTypeTamperBlocked"] = False
    assert "strict_type_tamper" in validate_artwork_acceptance_result(missing_type)
    missing_coord_flag = copy.deepcopy(result)
    missing_coord_flag["coordinatedOracleTamperBlocked"] = False
    assert "coordinated_oracle_tamper" in validate_artwork_acceptance_result(missing_coord_flag)
    surf = result["scenarios"]["orientationParity"]["canonicalSurfaces"]["COVER"]
    canon0 = canonical_orientation_expected(
        fit="COVER",
        slot_anchor="CENTER",
        rotation_deg=0.0,
        mirrored=False,
        surface_width_mm=float(surf["widthMm"]),
        surface_height_mm=float(surf["heightMm"]),
    )
    for corner in ("BL", "BR", "TR", "TL"):
        assert list(c0["expected"][corner]) == list(canon0[corner])
    fake = {"BL": [11, 22, 33], "BR": [44, 55, 66], "TR": [77, 88, 99], "TL": [12, 34, 56]}
    fake_q = oracle_quality(fake)
    coord = copy.deepcopy(result)
    coord["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {
        **c0,
        "expected": fake,
        "observed": dict(fake),
        "signature": fake_q["signature"],
        "uniqueSampleCount": fake_q["uniqueSampleCount"],
        "oracleDiscriminating": fake_q["oracleDiscriminating"],
        "status": "PASS",
    }
    coord_fails = validate_artwork_acceptance_result(coord)
    assert any("canonical_expected" in f or "canonical_pixel" in f for f in coord_fails)
    assert not any(f.endswith("_rgb") for f in coord_fails)
    copied_row = copy.deepcopy(result)
    kept = dict(c90)
    kept["rotationDeg"] = c0.get("rotationDeg")
    kept["anchor"] = c0.get("anchor")
    kept["fit"] = c0.get("fit")
    kept["mirrored"] = c0.get("mirrored")
    copied_row["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = kept
    copy_fails = validate_artwork_acceptance_result(copied_row)
    assert any("canonical_expected" in f or "canonical_pixel" in f for f in copy_fails)

    def _shift_ch(ch, delta):
        c = int(ch)
        if 0 <= c + delta <= 255:
            return c + delta
        if 0 <= c - delta <= 255:
            return c - delta
        return c

    for delta in (1, 8):
        near = copy.deepcopy(result)
        expected = {k: [_shift_ch(ch, delta) for ch in c0["expected"][k]] for k in ("BL", "BR", "TR", "TL")}
        observed = {k: [_shift_ch(ch, delta) for ch in c0["observed"][k]] for k in ("BL", "BR", "TR", "TL")}
        quality = oracle_quality(expected)
        near["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {
            **c0,
            "expected": expected,
            "observed": observed,
            "signature": quality["signature"],
            "uniqueSampleCount": quality["uniqueSampleCount"],
            "oracleDiscriminating": quality["oracleDiscriminating"],
            "status": "PASS",
        }
        near_fails = validate_artwork_acceptance_result(near)
        assert any("canonical_expected" in f for f in near_fails), delta
        assert not any(f.endswith("_rgb") for f in near_fails), delta

    for val in ("2", True, -1, 999):
        geo = copy.deepcopy(result)
        geo["scenarios"]["orientationParity"]["canonicalSurfaces"]["COVER"]["panelIndex"] = val
        geo_fails = validate_artwork_acceptance_result(geo)
        assert any("canonical_geometry" in f or "canonical_source" in f for f in geo_fails), val
        assert not any(f.endswith("_rgb") for f in geo_fails), val
    missing_idx = copy.deepcopy(result)
    missing_idx["scenarios"]["orientationParity"]["canonicalSurfaces"]["COVER"].pop("panelIndex", None)
    missing_idx_fails = validate_artwork_acceptance_result(missing_idx)
    assert any("canonical_geometry" in f or "canonical_source" in f for f in missing_idx_fails)
    width_only = copy.deepcopy(result)
    width_only["scenarios"]["orientationParity"]["canonicalSurfaces"]["COVER"]["widthMm"] = float(surf["widthMm"]) + 10.0
    width_fails = validate_artwork_acceptance_result(width_only)
    assert any("canonical_geometry" in f or "canonical_source" in f for f in width_fails)
    height_only = copy.deepcopy(result)
    height_only["scenarios"]["orientationParity"]["canonicalSurfaces"]["COVER"]["heightMm"] = float(surf["heightMm"]) + 10.0
    height_fails = validate_artwork_acceptance_result(height_only)
    assert any("canonical_geometry" in f or "canonical_source" in f for f in height_fails)
    coord_geo = copy.deepcopy(result)
    coord_geo["scenarios"]["orientationParity"]["canonicalSurfaces"]["COVER"] = {
        "widthMm": 500.0,
        "heightMm": 1700.0,
        "panelIndex": 0,
    }
    crops = list(coord_geo["scenarios"]["cabinet4"]["panelCrops"])
    crops[0] = {"xMm": 0.0, "yMm": 0.0, "widthMm": 500.0, "heightMm": 1700.0}
    coord_geo["scenarios"]["cabinet4"]["panelCrops"] = crops
    coord_geo["scenarios"]["cabinet4"]["widthMm"] = 2000.0
    attacker_exp = canonical_orientation_expected(
        fit="COVER",
        slot_anchor="CENTER",
        rotation_deg=0.0,
        mirrored=False,
        surface_width_mm=500.0,
        surface_height_mm=1700.0,
    )
    attacker_q = oracle_quality(attacker_exp)
    coord_geo["scenarios"]["orientationParity"]["COVER"]["CENTER"]["0"] = {
        **c0,
        "expected": attacker_exp,
        "observed": {k: list(v) for k, v in attacker_exp.items()},
        "signature": attacker_q["signature"],
        "uniqueSampleCount": attacker_q["uniqueSampleCount"],
        "oracleDiscriminating": attacker_q["oracleDiscriminating"],
        "status": "PASS",
    }
    coord_geo_fails = validate_artwork_acceptance_result(coord_geo)
    assert any("canonical_geometry" in f or "canonical_source" in f for f in coord_geo_fails)
    assert not any(f.endswith("_rgb") for f in coord_geo_fails)

    probes = (
        probe_serialized_orientation_tampers,
        probe_strict_type_tampers,
        probe_coordinated_oracle_tampers,
        probe_canonical_geometry_tampers,
        probe_near_tolerance_oracle_tampers,
    )
    assert len({id(fn) for fn in probes}) == 5
    assert probe_serialized_orientation_tampers(result) is True
    assert probe_strict_type_tampers(result) is True
    assert probe_coordinated_oracle_tampers(result) is True
    assert probe_canonical_geometry_tampers(result) is True
    assert probe_near_tolerance_oracle_tampers(result) is True
    assert result.get("canonicalGeometryTamperBlocked") is True
    assert result.get("nearToleranceOracleTamperBlocked") is True
    missing_geo_flag = copy.deepcopy(result)
    missing_geo_flag["canonicalGeometryTamperBlocked"] = False
    geo_flag_fails = validate_artwork_acceptance_result(missing_geo_flag)
    assert "canonical_geometry_tamper" in geo_flag_fails
    assert "serialized_orientation_tamper" not in geo_flag_fails
    missing_near_flag = copy.deepcopy(result)
    missing_near_flag["nearToleranceOracleTamperBlocked"] = False
    near_flag_fails = validate_artwork_acceptance_result(missing_near_flag)
    assert "near_tolerance_oracle_tamper" in near_flag_fails
    assert "strict_type_tamper" not in near_flag_fails
