"""Phase 841–900 Product Truth Render Pack + Generative Gateway. MOCK/unit — not Production Ready."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from fox3d.generative_gateway import qa_product_consistency, route_generative_request, validate_generative_result
from fox3d.parametric import CabinetEngine
from fox3d.platform import Platform
from fox3d.pngutil import write_png
from fox3d.product_truth import (
    camera_recipe,
    render_product_truth,
    scene_recipe,
    validate_product_truth_render_pack,
    write_occupancy_png,
)


def _plat(tmp_path):
    return Platform(root=tmp_path / "live", mock_blender=True)


def _fixture(tmp_path):
    plat = _plat(tmp_path)
    eng = CabinetEngine()
    cab, _ = eng.create("STORAGE_CABINET", tenant_id="ta", width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id="ta") if "DOOR" in s["componentId"].upper()]
    png = tmp_path / "art.png"
    write_png(png, 48, 32, bytes([40, 80, 120]) * (48 * 32))
    art = plat.artwork.register_artwork(tenant_id="ta", data=png.read_bytes(), name="art.png", source="GENERATED")
    place = plat.artwork.place(
        tenant_id="ta",
        surface_id=doors[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    pack = render_product_truth(
        plat,
        tenant_id="ta",
        placement=place,
        engineering=cab.model_dump(mode="json"),
        width=64,
        height=64,
    )
    return plat, cab, place, pack


def test_mock_pack_structure_cannot_claim_real(tmp_path):
    plat, cab, place, pack = _fixture(tmp_path)
    assert pack["usedMock"] is True
    assert pack["realArtworkPreviewReady"] is False
    assert pack["productTruthRenderPackReady"] is False
    assert pack["productTruthAovPackReady"] is True
    assert pack["physicalPrintValidated"] is False
    assert pack["globalProductionReady"] is False
    assert pack["ok"] is True
    assert validate_product_truth_render_pack(pack) == []
    cam = camera_recipe()
    drifted = camera_recipe(focal_length_mm=50.0)
    assert cam["cameraRecipeHash"] != drifted["cameraRecipeHash"]
    scene = scene_recipe()
    scene2 = scene_recipe(lighting="SOFTBOX")
    assert scene["sceneRecipeHash"] != scene2["sceneRecipeHash"]


def test_render_pack_negatives(tmp_path):
    plat, cab, place, pack = _fixture(tmp_path)
    wrong_eng = copy.deepcopy(pack)
    wrong_eng["aovs"]["beauty"]["engineeringHash"] = "forged"
    assert any("engineeringHash" in f for f in validate_product_truth_render_pack(wrong_eng))
    for key in ("artworkHash", "placementHash", "finalUvHash"):
        row = copy.deepcopy(pack)
        row["aovs"]["beauty"][key] = "forged"
        assert any(key in f for f in validate_product_truth_render_pack(row)), key
    mixed_cam = copy.deepcopy(pack)
    mixed_cam["aovs"]["depth"]["cameraRecipeHash"] = "other-cam"
    assert any("cameraRecipeHash" in f for f in validate_product_truth_render_pack(mixed_cam))
    missing = copy.deepcopy(pack)
    missing["aovs"].pop("normal")
    assert "missing_aov_normal" in validate_product_truth_render_pack(missing)
    tamper = copy.deepcopy(pack)
    path = Path(tamper["aovs"]["beauty"]["path"])
    path.write_bytes(path.read_bytes() + b"x")
    assert any("aov_hash_beauty" in f for f in validate_product_truth_render_pack(tamper))
    empty = copy.deepcopy(pack)
    empty_path = Path(empty["aovs"]["product_mask"]["path"])
    write_png(empty_path, 64, 64, bytes([0, 0, 0]) * (64 * 64))
    live = empty_path.read_bytes()
    from fox3d.ids import sha256_bytes

    empty["aovs"]["product_mask"]["sha256"] = sha256_bytes(live)
    empty["aovs"]["product_mask"]["size"] = len(live)
    assert any("occupancy_product_mask" in f for f in validate_product_truth_render_pack(empty))
    no_manifest = copy.deepcopy(pack)
    no_manifest["objectManifest"] = {"components": []}
    assert "object_manifest_identity" in validate_product_truth_render_pack(no_manifest)
    mock_real = copy.deepcopy(pack)
    mock_real["realArtworkPreviewReady"] = True
    assert "mock_claimed_real_preview" in validate_product_truth_render_pack(mock_real)


def test_regate_mask_identity_and_views(tmp_path):
    plat, cab, place, pack = _fixture(tmp_path)
    assert pack["aovs"]["artwork_mask"]["sha256"] != pack["aovs"]["product_mask"]["sha256"]
    assert "DOOR_DETAIL" in pack["views"]
    assert "ASSEMBLED_FRONT" in pack["views"]
    from fox3d.ids import sha256_bytes

    alias = copy.deepcopy(pack)
    src = Path(pack["aovs"]["product_mask"]["path"]).read_bytes()
    dest = tmp_path / "alias_artwork_mask.png"
    dest.write_bytes(src)
    alias["aovs"]["artwork_mask"]["path"] = str(dest)
    alias["aovs"]["artwork_mask"]["sha256"] = sha256_bytes(src)
    alias["aovs"]["artwork_mask"]["size"] = len(src)
    assert "artwork_mask_alias" in validate_product_truth_render_pack(alias)
    wrong_face = copy.deepcopy(pack)
    wrong_face["workerEvidence"]["face"] = "BACK"
    assert "worker_face" in validate_product_truth_render_pack(wrong_face)
    wrong_obj = copy.deepcopy(pack)
    wrong_obj["workerEvidence"]["objectName"] = "OTHER_DOOR"
    assert any("objectName" in f for f in validate_product_truth_render_pack(wrong_obj))
    wrong_sha = copy.deepcopy(pack)
    wrong_sha["workerEvidence"]["artworkSha256"] = "0" * 64
    assert any("artworkSha256" in f or "worker_mismatch" in f for f in validate_product_truth_render_pack(wrong_sha))
    for key in ("artworkHash", "placementHash", "finalUvHash", "surfaceHash"):
        row = copy.deepcopy(pack)
        row["workerEvidence"][key] = "forged-identity"
        assert any(key in f for f in validate_product_truth_render_pack(row)), key
    missing_comp = copy.deepcopy(pack)
    missing_comp["workerEvidence"]["componentId"] = "door_other"
    assert any("componentId" in f for f in validate_product_truth_render_pack(missing_comp))
    no_optix = copy.deepcopy(pack)
    no_optix["usedMock"] = False
    no_optix["realBlender"] = True
    no_optix["realOptix"] = False
    no_optix["realArtworkPreviewReady"] = True
    no_optix["productTruthRenderPackReady"] = True
    optix_fails = validate_product_truth_render_pack(no_optix)
    assert "real_realOptix" in optix_fails
    for val in ("true", 1, None):
        bad = copy.deepcopy(pack)
        bad["usedMock"] = val
        assert any("bool_schema_usedMock" in f or "real_usedMock" in f for f in validate_product_truth_render_pack(bad)), val
    missing_view = copy.deepcopy(pack)
    missing_view["views"].pop("DOOR_DETAIL")
    assert "missing_view_DOOR_DETAIL" in validate_product_truth_render_pack(missing_view)
    coord = copy.deepcopy(pack)
    coord["aovs"]["beauty"]["placementHash"] = "coordinated"
    assert "aov_worker_inconsistent" in validate_product_truth_render_pack(coord)


def test_generative_gateway_fixture_not_live(tmp_path):
    plat, cab, place, pack = _fixture(tmp_path)
    routing = route_generative_request({"mode": "IMAGE", "requiredControls": ["depth", "normal"]})
    assert routing["liveProviderAvailable"] is False
    assert routing["qualityClaim"] == "UNVERIFIED"
    assert routing["selectedProvider"] == "H3_MAX"
    vid = route_generative_request({"mode": "VIDEO"})
    assert vid["selectedProvider"] == "LTX_2_5"
    result = plat.generative.submit({"mode": "IMAGE", "renderPackId": pack["renderPackId"], "productLocked": True}, pack=pack)
    assert result["usedMock"] is True
    assert result["liveH3MaxProviderReady"] is False
    assert result["liveLtx25ProviderReady"] is False
    assert result["generativeRenderGatewayLogicReady"] is True
    assert result["ok"] is True
    wrong = plat.generative.submit({"mode": "IMAGE", "renderPackId": "other-pack"}, pack=pack)
    assert "wrong_render_pack" in validate_generative_result(wrong, pack=pack)
    fake_live = copy.deepcopy(result)
    fake_live["usedMock"] = False
    fake_live["liveProviderEvidence"] = {}
    assert "mock_claimed_live_provider" in validate_generative_result(fake_live, pack=pack)
    live_flag = copy.deepcopy(result)
    live_flag["liveH3MaxProviderReady"] = True
    assert "fixture_live_provider" in validate_generative_result(live_flag, pack=pack)
    mutated = copy.deepcopy(result)
    mutated["mutatedProductTruth"] = True
    assert "product_truth_mutated" in validate_generative_result(mutated, pack=pack)
    qa_ok = qa_product_consistency(
        pack=pack,
        generated={
            "inputRenderPackId": pack["renderPackId"],
            "masks": {
                "productOccupancy": pack["aovs"]["product_mask"]["occupancy"],
                "artworkOccupancy": pack["aovs"]["artwork_mask"]["occupancy"],
            },
        },
    )
    assert qa_ok["decision"] == "APPROVED_FOR_ASSET_REVIEW"
    assert qa_ok["productionAsset"] is False
    assert qa_ok["liveVisionJudgeReady"] is False
    qa_miss = qa_product_consistency(pack=pack, generated=None)
    assert qa_miss["decision"] == "REJECT_MISSING_EVIDENCE"
    qa_drift = qa_product_consistency(
        pack=pack,
        generated={"inputRenderPackId": pack["renderPackId"], "masks": {"productOccupancy": 0.99}},
    )
    assert qa_drift["decision"] == "REJECT_PRODUCT_DRIFT"
    qa_art = qa_product_consistency(
        pack=pack,
        generated={"inputRenderPackId": pack["renderPackId"], "masks": {"artworkOccupancy": 0.99}},
    )
    assert qa_art["decision"] == "REJECT_ARTWORK_DRIFT"


def test_occupancy_writer_not_empty(tmp_path):
    p = tmp_path / "m.png"
    write_occupancy_png(p, width=32, height=32, kind="product_mask")
    from fox3d.artwork import decode_png_rgb
    from fox3d.product_truth import _occupancy

    w, h, rgb = decode_png_rgb(p.read_bytes())
    occ = _occupancy(rgb, w, h)
    assert 0.02 < occ < 0.98


def test_product_truth_runner_publishes(tmp_path):
    import importlib.util
    import sys

    from fox3d.evidence import prepare_evidence_lineage
    from fox3d.product_truth import run_phase_841_scenario

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_product_truth_render_e2e.py"
    spec = importlib.util.spec_from_file_location("run_product_truth_render_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_product_truth_render_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    sha = "b" * 40
    docs = tmp_path / "docs"
    docs.mkdir()

    def inspect(root, allow_dirty=False):
        return prepare_evidence_lineage(head_sha=sha, porcelain="", allow_dirty=allow_dirty)

    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", sha],
        hooks={
            "inspect": inspect,
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": lambda plat, **kwargs: run_phase_841_scenario(plat, evidence_code_commit=sha),
            "acceptance_root": tmp_path / "acc",
        },
    )
    assert rc == 0
    body = json.loads((docs / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert body["realArtworkPreviewReady"] is False
    assert body["liveH3MaxProviderReady"] is False
    assert body["liveLtx25ProviderReady"] is False
    assert (docs / "GENERATIVE_RENDER_GATEWAY_ACCEPTANCE.json").exists()


def test_product_truth_runner_refuses_on_missing_canonical_authority(tmp_path):
    import importlib.util
    import sys

    from fox3d.evidence import prepare_evidence_lineage
    from fox3d.product_truth import run_phase_841_scenario

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_product_truth_render_e2e.py"
    spec = importlib.util.spec_from_file_location("run_product_truth_render_e2e_neg", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_product_truth_render_e2e_neg"] = mod
    spec.loader.exec_module(mod)
    sha = "b" * 40
    docs = tmp_path / "docs"
    docs.mkdir()

    def inspect(root, allow_dirty=False):
        return prepare_evidence_lineage(head_sha=sha, porcelain="", allow_dirty=allow_dirty)

    def forged_scenario(plat, **kwargs):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        # Delete canonical placement record from platform store
        p_id = res["pack"]["placementId"]
        plat.artwork.placements.pop(p_id, None)
        return res

    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", sha],
        hooks={
            "inspect": inspect,
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": forged_scenario,
            "acceptance_root": tmp_path / "acc",
        },
    )
    assert rc == 1
    assert not (docs / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists()


def test_independent_canonical_expected_authority_negatives(tmp_path):
    plat, cab, place, pack = _fixture(tmp_path)
    expected_auth = copy.deepcopy(pack["expectedIdentity"])
    assert expected_auth["engineeringHash"] == cab.engineering_hash()
    assert expected_auth["placementHash"] == place["placementHash"]
    assert expected_auth["finalUvHash"] == pack["finalUvHash"]

    # 1. Coordinated tamper across pack + workerEvidence + pack.expectedIdentity
    for key, forge_val in (
        ("engineeringHash", "0" * 64),
        ("placementHash", "1" * 64),
        ("finalUvHash", "2" * 64),
        ("surfaceHash", "3" * 64),
        ("artworkHash", "4" * 64),
        ("artworkSha256", "5" * 64),
        ("componentId", "forged_door_comp"),
        ("objectName", "FORGED_DOOR_OBJ"),
        ("face", "BACK"),
    ):
        forged = copy.deepcopy(pack)
        forged[key] = forge_val
        forged["workerEvidence"][key] = forge_val
        if "expectedIdentity" in forged and isinstance(forged["expectedIdentity"], dict):
            forged["expectedIdentity"][key] = forge_val
        fails = validate_product_truth_render_pack(forged, expected_identity=expected_auth)
        assert any(key in f or "worker_mismatch" in f or "worker_face" in f for f in fails), f"Failed to catch coordinated forge of {key}"

    # 2. Wrong worker engineeringHash alone
    bad_eng = copy.deepcopy(pack)
    bad_eng["workerEvidence"]["engineeringHash"] = "wrong_eng_sha"
    assert any("engineeringHash" in f for f in validate_product_truth_render_pack(bad_eng))

    # 3. Wrong artwork DAM bytes/SHA
    bad_art = copy.deepcopy(pack)
    bad_art["workerEvidence"]["artworkSha256"] = "0" * 64
    assert any("artworkSha256" in f for f in validate_product_truth_render_pack(bad_art))

    # 4. Wrong placementHash / surfaceHash / componentId / objectName / face
    for key in ("placementHash", "surfaceHash", "componentId", "objectName"):
        bad_k = copy.deepcopy(pack)
        bad_k["workerEvidence"][key] = "wrong_val"
        assert any(key in f for f in validate_product_truth_render_pack(bad_k)), key
    bad_face = copy.deepcopy(pack)
    bad_face["workerEvidence"]["face"] = "BACK"
    assert "worker_face" in validate_product_truth_render_pack(bad_face)


def test_worker_uv_hash_recompute_and_tamper_fails(tmp_path):
    import importlib.util
    from fox3d.artwork import ArtworkError

    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("bj_apply_tamper", path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)

    art = tmp_path / "art_black.png"
    write_png(art, 8, 8, bytes([0, 0, 0]) * (8 * 8))
    from fox3d.ids import sha256_bytes

    art_sha = sha256_bytes(art.read_bytes())
    uv = {"u0": 0.0, "v0": 0.0, "u1": 1.0, "v1": 1.0}
    item = {
        "objectName": "DOOR_1",
        "imagePath": str(art),
        "uvRect": uv,
        "engineeringHash": "e" * 64,
        "surfaceHash": "s" * 64,
        "artworkHash": "a" * 64,
        "placementHash": "p" * 64,
        "artworkSha256": art_sha,
        "face": "FRONT",
        "componentId": "DOOR_1",
        "placementId": "pl-1",
        "finalUvHash": "tampered_expected_hash",  # tampered!
    }
    mesh = {
        "polygons": [
            {"index": 0, "normal": (0.0, -1.0, 0.0), "loop_start": 0, "loop_total": 4},
            {"index": 1, "normal": (0.0, 1.0, 0.0), "loop_start": 4, "loop_total": 4},
        ],
        "uv_loops": [],
        "materials": [],
    }
    # Must fail closed with ArtworkApplyError when request finalUvHash is tampered
    with pytest.raises(bj.ArtworkApplyError, match="finalUvHash mismatch"):
        bj.apply_canonical_artwork({"DOOR_1": mesh}, {"artworkPlacements": [item]})

    # With correct or omitted finalUvHash, observed hash is returned
    item_valid = dict(item)
    item_valid.pop("finalUvHash")
    applied = bj.apply_canonical_artwork({"DOOR_1": mesh}, {"artworkPlacements": [item_valid]})
    assert applied[0]["finalUvHash"] != "tampered_expected_hash"
    assert len(applied[0]["finalUvHash"]) == 64


def test_worker_observed_camera_view_evidence_negatives(tmp_path):
    plat, cab, place, pack = _fixture(tmp_path)
    assert "DOOR_DETAIL" in pack["views"]
    assert "ASSEMBLED_FRONT" in pack["views"]

    # 1. Mutate workerView location alone while keeping hash unchanged -> FAIL
    mut_loc = copy.deepcopy(pack)
    mut_loc["views"]["DOOR_DETAIL"]["workerView"]["location"] = [9.9, -9.9, 9.9]
    fails_loc = validate_product_truth_render_pack(mut_loc)
    assert "view_worker_camera_hash_mismatch_DOOR_DETAIL" in fails_loc or "view_camera_mismatch_DOOR_DETAIL" in fails_loc

    # 2. Mutate workerView lookAt / target alone -> FAIL
    mut_target = copy.deepcopy(pack)
    mut_target["views"]["DOOR_DETAIL"]["workerView"]["lookAt"] = [5.0, 5.0, 5.0]
    mut_target["views"]["DOOR_DETAIL"]["workerView"]["target"] = [5.0, 5.0, 5.0]
    fails_target = validate_product_truth_render_pack(mut_target)
    assert "view_worker_camera_hash_mismatch_DOOR_DETAIL" in fails_target or "view_camera_mismatch_DOOR_DETAIL" in fails_target

    # 3. Mutate focalLengthMm alone -> FAIL
    mut_focal = copy.deepcopy(pack)
    mut_focal["views"]["DOOR_DETAIL"]["workerView"]["focalLengthMm"] = 35.0
    fails_focal = validate_product_truth_render_pack(mut_focal)
    assert "view_worker_camera_hash_mismatch_DOOR_DETAIL" in fails_focal or "view_camera_mismatch_DOOR_DETAIL" in fails_focal

    # 4. Mutate sensorWidthMm / safeMargin / width / height alone -> FAIL
    for key, val in (
        ("sensorWidthMm", 24.0),
        ("safeMargin", 0.25),
        ("width", 1024),
        ("height", 1024),
    ):
        mut_param = copy.deepcopy(pack)
        mut_param["views"]["DOOR_DETAIL"]["workerView"][key] = val
        fails_param = validate_product_truth_render_pack(mut_param)
        assert any("DOOR_DETAIL" in f for f in fails_param), f"Failed to catch workerView mutation of {key}"

    # 5. Coordinated mutate workerView fields + worker hash + serialized view hash + serialized cameraRecipe -> FAIL against independent request-side recipe
    expected_auth = copy.deepcopy(pack["expectedIdentity"])
    tamper_recipe = copy.deepcopy(pack)
    recomputed_tamper = camera_recipe(camera_id="DOOR_DETAIL", focal_length_mm=24.0, width=64, height=64)
    tamper_hash = recomputed_tamper["cameraRecipeHash"]
    tamper_recipe["views"]["DOOR_DETAIL"]["cameraRecipe"] = recomputed_tamper
    tamper_recipe["views"]["DOOR_DETAIL"]["cameraRecipeHash"] = tamper_hash
    tamper_recipe["views"]["DOOR_DETAIL"]["workerView"]["focalLengthMm"] = 24.0
    tamper_recipe["views"]["DOOR_DETAIL"]["workerView"]["cameraRecipeHash"] = tamper_hash
    fails_coord = validate_product_truth_render_pack(tamper_recipe, expected_identity=expected_auth)
    assert "view_canonical_camera_mismatch_DOOR_DETAIL" in fails_coord or "worker_view_canonical_camera_mismatch_DOOR_DETAIL" in fails_coord

    # 6. Wrong viewId / swapped DOOR_DETAIL and ASSEMBLED_FRONT -> FAIL
    swapped = copy.deepcopy(pack)
    swapped["views"]["DOOR_DETAIL"]["workerView"]["viewId"] = "ASSEMBLED_FRONT"
    fails_swap = validate_product_truth_render_pack(swapped)
    assert "view_worker_id_mismatch_DOOR_DETAIL" in fails_swap

    # 7. Invalid non-numeric types: bool, string, NaN, Inf in workerView camera fields -> FAIL
    for bad_loc in ([True, 1.0, 2.0], ["1.0", "2.0", "3.0"], [float("nan"), 1.0, 2.0], [float("inf"), 1.0, 2.0]):
        bad_type_loc = copy.deepcopy(pack)
        bad_type_loc["views"]["DOOR_DETAIL"]["workerView"]["location"] = bad_loc
        fails_type = validate_product_truth_render_pack(bad_type_loc)
        assert "view_worker_location_invalid_DOOR_DETAIL" in fails_type

    for bad_focal in (True, "85.0", float("nan"), float("inf"), -10.0, 0):
        bad_type_focal = copy.deepcopy(pack)
        bad_type_focal["views"]["DOOR_DETAIL"]["workerView"]["focalLengthMm"] = bad_focal
        fails_type = validate_product_truth_render_pack(bad_type_focal)
        assert "view_worker_focalLength_invalid_DOOR_DETAIL" in fails_type

    # 8. Missing worker view record for required views -> FAIL
    no_w_door = copy.deepcopy(pack)
    no_w_door["views"]["DOOR_DETAIL"].pop("workerView", None)
    no_w_door["workerViews"].pop("DOOR_DETAIL", None)
    assert "missing_worker_view_DOOR_DETAIL" in validate_product_truth_render_pack(no_w_door)

    no_w_front = copy.deepcopy(pack)
    no_w_front["views"]["ASSEMBLED_FRONT"].pop("workerView", None)
    no_w_front["workerViews"].pop("ASSEMBLED_FRONT", None)
    assert "missing_worker_view_ASSEMBLED_FRONT" in validate_product_truth_render_pack(no_w_front)

    # 9. Worker observed artifact SHA / size differs from pack view / live file -> FAIL
    bad_sha = copy.deepcopy(pack)
    bad_sha["views"]["DOOR_DETAIL"]["workerView"]["sha256"] = "0" * 64
    assert "view_worker_hash_DOOR_DETAIL" in validate_product_truth_render_pack(bad_sha)

    bad_sz = copy.deepcopy(pack)
    bad_sz["views"]["DOOR_DETAIL"]["workerView"]["size"] = 999999
    assert "view_worker_size_DOOR_DETAIL" in validate_product_truth_render_pack(bad_sz)

    # 10. REAL worker view with usedMock=True, realBlender=False, or realOptix=False -> FAIL
    real_pack = copy.deepcopy(pack)
    real_pack["usedMock"] = False
    real_pack["realBlender"] = True
    real_pack["realOptix"] = True
    real_pack["realArtworkPreviewReady"] = True
    real_pack["productTruthRenderPackReady"] = True
    real_pack["views"]["DOOR_DETAIL"]["workerView"]["usedMock"] = True
    fails_mock_real = validate_product_truth_render_pack(real_pack)
    assert "real_worker_view_usedMock_DOOR_DETAIL" in fails_mock_real


def test_runner_coordinated_tamper_fails_closed(tmp_path):
    import importlib.util
    import sys

    from fox3d.evidence import prepare_evidence_lineage
    from fox3d.product_truth import run_phase_841_scenario

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_product_truth_render_e2e.py"
    spec = importlib.util.spec_from_file_location("run_pt_tamper_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_pt_tamper_test"] = mod
    spec.loader.exec_module(mod)
    sha = "c" * 40

    def inspect(root, allow_dirty=False):
        return prepare_evidence_lineage(head_sha=sha, porcelain="", allow_dirty=allow_dirty)

    # 1. Coordinated tamper on engineeringHash across pack + worker + expectedIdentity
    def tamper_eng_scenario(plat, **kwargs):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        pack = res["pack"]
        pack["engineeringHash"] = "9" * 64
        pack["workerEvidence"]["engineeringHash"] = "9" * 64
        pack["expectedIdentity"]["engineeringHash"] = "9" * 64
        return res

    docs = tmp_path / "docs_eng"
    docs.mkdir()
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", sha],
        hooks={
            "inspect": inspect,
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": tamper_eng_scenario,
            "acceptance_root": tmp_path / "acc_eng",
        },
    )
    assert rc == 1
    assert not (docs / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists()

    # 2. Coordinated tamper on cameraRecipe across pack + worker + expectedIdentity
    def tamper_cam_scenario(plat, **kwargs):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        pack = res["pack"]
        tampered_c = camera_recipe(camera_id="TAMPERED_CAM", focal_length_mm=24.0)
        t_hash = tampered_c["cameraRecipeHash"]
        pack["cameraRecipe"] = tampered_c
        pack["cameraRecipeHash"] = t_hash
        pack["workerEvidence"]["cameraRecipeHash"] = t_hash
        pack["expectedIdentity"]["cameraRecipeHash"] = t_hash
        return res

    docs_cam = tmp_path / "docs_cam"
    docs_cam.mkdir()
    rc = mod.main(
        ["--docs-root", str(docs_cam), "--expected-commit", sha],
        hooks={
            "inspect": inspect,
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": tamper_cam_scenario,
            "acceptance_root": tmp_path / "acc_cam",
        },
    )
    assert rc == 1
    assert not (docs_cam / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists()

    # 3. Coordinated tamper on DOOR_DETAIL view camera recipe
    def tamper_view_cam_scenario(plat, **kwargs):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        pack = res["pack"]
        tampered_view_cam = camera_recipe(camera_id="DOOR_DETAIL", focal_length_mm=20.0, width=64, height=64)
        v_hash = tampered_view_cam["cameraRecipeHash"]
        pack["views"]["DOOR_DETAIL"]["cameraRecipe"] = tampered_view_cam
        pack["views"]["DOOR_DETAIL"]["cameraRecipeHash"] = v_hash
        pack["views"]["DOOR_DETAIL"]["workerView"]["cameraRecipeHash"] = v_hash
        pack["views"]["DOOR_DETAIL"]["workerView"]["focalLengthMm"] = 20.0
        pack["expectedIdentity"]["viewRecipes"]["DOOR_DETAIL"] = v_hash
        return res

    docs_view = tmp_path / "docs_view"
    docs_view.mkdir()
    rc = mod.main(
        ["--docs-root", str(docs_view), "--expected-commit", sha],
        hooks={
            "inspect": inspect,
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": tamper_view_cam_scenario,
            "acceptance_root": tmp_path / "acc_view",
        },
    )
    assert rc == 1
    assert not (docs_view / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists()

    # 4. Deleting canonical surface from plat.artwork.surfaces
    def delete_surface_scenario(plat, **kwargs):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        s_id = res["frozenAuthorityContext"]["surfaceId"]
        plat.artwork.surfaces.pop(s_id, None)
        return res

    docs_surf = tmp_path / "docs_surf"
    docs_surf.mkdir()
    rc = mod.main(
        ["--docs-root", str(docs_surf), "--expected-commit", sha],
        hooks={
            "inspect": inspect,
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": delete_surface_scenario,
            "acceptance_root": tmp_path / "acc_surf",
        },
    )
    assert rc == 1
    assert not (docs_surf / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists()

    # 5. Missing or tampered canonical artwork file
    def corrupt_artwork_scenario(plat, **kwargs):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        art_id = res["frozenAuthorityContext"]["artworkId"]
        art_rec = plat.artwork.artworks[art_id]
        Path(art_rec["path"]).write_bytes(b"tampered_corrupt_artwork_bytes")
        return res

    docs_art = tmp_path / "docs_art"
    docs_art.mkdir()
    rc = mod.main(
        ["--docs-root", str(docs_art), "--expected-commit", sha],
        hooks={
            "inspect": inspect,
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": corrupt_artwork_scenario,
            "acceptance_root": tmp_path / "acc_art",
        },
    )
    assert rc == 1
    assert not (docs_art / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists()

    # 6. Missing frozen_authority
    def missing_frozen_auth_scenario(plat, **kwargs):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res.pop("frozenAuthorityContext", None)
        return res

    docs_no_fa = tmp_path / "docs_no_fa"
    docs_no_fa.mkdir()
    rc = mod.main(
        ["--docs-root", str(docs_no_fa), "--expected-commit", sha],
        hooks={
            "inspect": inspect,
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": missing_frozen_auth_scenario,
            "acceptance_root": tmp_path / "acc_no_fa",
        },
    )
    assert rc == 1
    assert not (docs_no_fa / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists()


def test_worker_view_provenance_and_dam_negatives(tmp_path):
    plat, cab, place, pack = _fixture(tmp_path)

    # 1. Top-level pack.workerViews vs row.workerView conflict
    conflict_pack = copy.deepcopy(pack)
    conflict_pack["workerViews"]["DOOR_DETAIL"] = dict(conflict_pack["workerViews"]["DOOR_DETAIL"])
    conflict_pack["workerViews"]["DOOR_DETAIL"]["location"] = [9.0, 9.0, 9.0]
    fails_conf = validate_product_truth_render_pack(conflict_pack, plat=plat)
    assert "view_worker_view_conflict_DOOR_DETAIL" in fails_conf

    # 2. View filename mismatch (e.g. role DOOR_DETAIL with path pointing to assembled_front.png)
    bad_fn = copy.deepcopy(pack)
    bad_fn["views"]["DOOR_DETAIL"]["path"] = str(Path(pack["views"]["DOOR_DETAIL"]["path"]).parent / "assembled_front.png")
    fails_fn = validate_product_truth_render_pack(bad_fn, plat=plat)
    assert "view_filename_mismatch_DOOR_DETAIL" in fails_fn

    # 3. ViewId mismatch on view row
    bad_vid = copy.deepcopy(pack)
    bad_vid["views"]["DOOR_DETAIL"]["viewId"] = "WRONG_VIEW"
    fails_vid = validate_product_truth_render_pack(bad_vid, plat=plat)
    assert "view_id_mismatch_DOOR_DETAIL" in fails_vid

    # 4. Normalized path mismatch between row and workerView
    bad_path = copy.deepcopy(pack)
    bad_path["views"]["DOOR_DETAIL"]["workerView"]["path"] = str(tmp_path / "other" / "door_detail.png")
    fails_path = validate_product_truth_render_pack(bad_path, plat=plat)
    assert "view_path_mismatch_DOOR_DETAIL" in fails_path

    # 5. Dimension mismatch: row width vs PNG meta
    bad_dim = copy.deepcopy(pack)
    bad_dim["views"]["DOOR_DETAIL"]["width"] = 999
    fails_dim = validate_product_truth_render_pack(bad_dim, plat=plat)
    assert "view_dimension_mismatch_DOOR_DETAIL" in fails_dim

    # 6. Job ID mismatch: row vs pack
    bad_job = copy.deepcopy(pack)
    bad_job["views"]["DOOR_DETAIL"]["blenderJobId"] = "wrong_job_id"
    fails_job = validate_product_truth_render_pack(bad_job, plat=plat)
    assert "view_job_id_mismatch_DOOR_DETAIL" in fails_job or "view_job_id_conflict_DOOR_DETAIL" in fails_job

    # 7. Job ID conflict: row vs workerView
    conflict_job = copy.deepcopy(pack)
    conflict_job["views"]["DOOR_DETAIL"]["workerView"]["blenderJobId"] = "other_job_id"
    fails_cjob = validate_product_truth_render_pack(conflict_job, plat=plat)
    assert "view_job_id_conflict_DOOR_DETAIL" in fails_cjob

    # 8. Missing damRef / artifactId
    no_dam = copy.deepcopy(pack)
    no_dam["views"]["DOOR_DETAIL"].pop("damRef", None)
    no_dam["views"]["DOOR_DETAIL"].pop("artifactId", None)
    fails_nodam = validate_product_truth_render_pack(no_dam, plat=plat)
    assert "view_missing_dam_ref_DOOR_DETAIL" in fails_nodam

    # 9. damRef != artifactId
    mismatch_dam = copy.deepcopy(pack)
    mismatch_dam["views"]["DOOR_DETAIL"]["damRef"] = "different_dam_ref"
    fails_mdam = validate_product_truth_render_pack(mismatch_dam, plat=plat)
    assert "view_dam_ref_mismatch_DOOR_DETAIL" in fails_mdam

    # 10. DAM asset validation against plat.dam:
    # 10a. Tenant mismatch
    dam_ref = pack["views"]["DOOR_DETAIL"]["damRef"]
    dam_obj = plat.dam._index[dam_ref]
    orig_tenant = dam_obj.tenant_id
    dam_obj.tenant_id = "wrong_tenant"
    fails_tenant = validate_product_truth_render_pack(pack, plat=plat)
    assert "view_dam_tenant_mismatch_DOOR_DETAIL" in fails_tenant
    dam_obj.tenant_id = orig_tenant

    # 10b. SHA mismatch
    orig_sha = dam_obj.sha256
    dam_obj.sha256 = "0" * 64
    fails_dsha = validate_product_truth_render_pack(pack, plat=plat)
    assert "view_dam_sha_mismatch_DOOR_DETAIL" in fails_dsha
    dam_obj.sha256 = orig_sha

    # 10c. Role mismatch
    orig_meta = dict(dam_obj.metadata)
    dam_obj.metadata["view"] = "ASSEMBLED_FRONT"
    fails_role = validate_product_truth_render_pack(pack, plat=plat)
    assert "view_dam_role_mismatch_DOOR_DETAIL" in fails_role
    dam_obj.metadata = orig_meta

    # 10d. RenderPackId mismatch
    dam_obj.metadata["renderPackId"] = "other_pack_id"
    fails_packid = validate_product_truth_render_pack(pack, plat=plat)
    assert "view_dam_pack_mismatch_DOOR_DETAIL" in fails_packid
    dam_obj.metadata = orig_meta



