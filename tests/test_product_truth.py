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

    def execute_negative(name, scenario_fn):
        docs = tmp_path / f"docs_{name}"
        docs.mkdir(parents=True, exist_ok=True)
        acc = tmp_path / f"acc_{name}"
        rc = mod.main(
            ["--docs-root", str(docs), "--expected-commit", sha],
            hooks={
                "inspect": inspect,
                "platform": lambda root: Platform(root=root, mock_blender=True),
                "scenario": scenario_fn,
                "acceptance_root": acc,
            },
        )
        assert rc == 1, f"Case {name} failed to exit with code 1, got {rc}"
        assert not (docs / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists(), (
            f"Case {name} published acceptance artifact on failure"
        )

    # 1. engineeringHash
    def case_1(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["pack"]["engineeringHash"] = "9" * 64
        res["pack"]["workerEvidence"]["engineeringHash"] = "9" * 64
        res["pack"]["expectedIdentity"]["engineeringHash"] = "9" * 64
        return res
    execute_negative("1_engineering_hash", case_1)

    # 2. placementHash
    def case_2(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["pack"]["placementHash"] = "8" * 64
        res["pack"]["workerEvidence"]["placementHash"] = "8" * 64
        res["pack"]["expectedIdentity"]["placementHash"] = "8" * 64
        return res
    execute_negative("2_placement_hash", case_2)

    # 3. surfaceHash
    def case_3(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["pack"]["surfaceHash"] = "7" * 64
        res["pack"]["workerEvidence"]["surfaceHash"] = "7" * 64
        res["pack"]["expectedIdentity"]["surfaceHash"] = "7" * 64
        return res
    execute_negative("3_surface_hash", case_3)

    # 4. finalUvHash
    def case_4(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["pack"]["finalUvHash"] = "6" * 64
        res["pack"]["workerEvidence"]["finalUvHash"] = "6" * 64
        res["pack"]["expectedIdentity"]["finalUvHash"] = "6" * 64
        return res
    execute_negative("4_final_uv_hash", case_4)

    # 5. componentId
    def case_5(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["pack"]["componentId"] = "TAMPERED_COMP"
        res["pack"]["workerEvidence"]["componentId"] = "TAMPERED_COMP"
        res["pack"]["expectedIdentity"]["componentId"] = "TAMPERED_COMP"
        return res
    execute_negative("5_component_id", case_5)

    # 6. objectName
    def case_6(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["pack"]["objectName"] = "TAMPERED_OBJ"
        res["pack"]["workerEvidence"]["objectName"] = "TAMPERED_OBJ"
        res["pack"]["expectedIdentity"]["objectName"] = "TAMPERED_OBJ"
        return res
    execute_negative("6_object_name", case_6)

    # 7. face
    def case_7(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["pack"]["face"] = "BACK"
        res["pack"]["workerEvidence"]["face"] = "BACK"
        res["pack"]["expectedIdentity"]["face"] = "BACK"
        return res
    execute_negative("7_face", case_7)

    # 8. artwork artworkHash
    def case_8(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["pack"]["artworkHash"] = "5" * 64
        res["pack"]["workerEvidence"]["artworkHash"] = "5" * 64
        res["pack"]["expectedIdentity"]["artworkHash"] = "5" * 64
        return res
    execute_negative("8_artwork_hash", case_8)

    # 9. artwork SHA / authoritative artwork bytes
    def case_9(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        art_id = res["frozenAuthorityContext"]["artworkId"]
        art_rec = plat.artwork.artworks[art_id]
        Path(art_rec["path"]).write_bytes(b"tampered_corrupt_artwork_bytes")
        res["pack"]["artworkSha256"] = "4" * 64
        res["pack"]["workerEvidence"]["artworkSha256"] = "4" * 64
        res["pack"]["expectedIdentity"]["artworkSha256"] = "4" * 64
        return res
    execute_negative("9_artwork_sha", case_9)

    # 10. main cameraRecipe / cameraRecipeHash
    def case_10(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        tampered_c = camera_recipe(camera_id="TAMPERED_CAM", focal_length_mm=24.0)
        t_hash = tampered_c["cameraRecipeHash"]
        res["pack"]["cameraRecipe"] = tampered_c
        res["pack"]["cameraRecipeHash"] = t_hash
        res["pack"]["workerEvidence"]["cameraRecipeHash"] = t_hash
        res["pack"]["expectedIdentity"]["cameraRecipeHash"] = t_hash
        return res
    execute_negative("10_camera_recipe", case_10)

    # 11. sceneRecipe / sceneRecipeHash
    def case_11(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        tampered_s = scene_recipe(samples=99)
        s_hash = tampered_s["sceneRecipeHash"]
        res["pack"]["sceneRecipe"] = tampered_s
        res["pack"]["sceneRecipeHash"] = s_hash
        res["pack"]["workerEvidence"]["sceneRecipeHash"] = s_hash
        res["pack"]["expectedIdentity"]["sceneRecipeHash"] = s_hash
        return res
    execute_negative("11_scene_recipe", case_11)

    # 12. DOOR_DETAIL requested camera recipe/hash
    def case_12(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        tampered_view_cam = camera_recipe(camera_id="DOOR_DETAIL", focal_length_mm=20.0, width=64, height=64)
        v_hash = tampered_view_cam["cameraRecipeHash"]
        res["pack"]["views"]["DOOR_DETAIL"]["cameraRecipe"] = tampered_view_cam
        res["pack"]["views"]["DOOR_DETAIL"]["cameraRecipeHash"] = v_hash
        res["pack"]["views"]["DOOR_DETAIL"]["workerView"]["cameraRecipeHash"] = v_hash
        res["pack"]["views"]["DOOR_DETAIL"]["workerView"]["focalLengthMm"] = 20.0
        res["pack"]["workerViews"]["DOOR_DETAIL"]["cameraRecipeHash"] = v_hash
        res["pack"]["workerViews"]["DOOR_DETAIL"]["focalLengthMm"] = 20.0
        res["pack"]["expectedIdentity"]["viewRecipes"]["DOOR_DETAIL"] = v_hash
        return res
    execute_negative("12_door_detail_recipe", case_12)

    # 13. ASSEMBLED_FRONT requested camera recipe/hash
    def case_13(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        tampered_front_cam = camera_recipe(camera_id="ASSEMBLED_FRONT", focal_length_mm=20.0, width=64, height=64)
        v_hash = tampered_front_cam["cameraRecipeHash"]
        res["pack"]["views"]["ASSEMBLED_FRONT"]["cameraRecipe"] = tampered_front_cam
        res["pack"]["views"]["ASSEMBLED_FRONT"]["cameraRecipeHash"] = v_hash
        res["pack"]["views"]["ASSEMBLED_FRONT"]["workerView"]["cameraRecipeHash"] = v_hash
        res["pack"]["views"]["ASSEMBLED_FRONT"]["workerView"]["focalLengthMm"] = 20.0
        res["pack"]["workerViews"]["ASSEMBLED_FRONT"]["cameraRecipeHash"] = v_hash
        res["pack"]["workerViews"]["ASSEMBLED_FRONT"]["focalLengthMm"] = 20.0
        res["pack"]["expectedIdentity"]["viewRecipes"]["ASSEMBLED_FRONT"] = v_hash
        return res
    execute_negative("13_assembled_front_recipe", case_13)

    # 14. delete canonical placement record
    def case_14(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        p_id = res["frozenAuthorityContext"]["placementId"]
        plat.artwork.placements.pop(p_id, None)
        return res
    execute_negative("14_delete_placement", case_14)

    # 15. delete canonical PrintableSurface / required surface record
    def case_15(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        s_id = res["frozenAuthorityContext"]["surfaceId"]
        plat.artwork.surfaces.pop(s_id, None)
        return res
    execute_negative("15_delete_surface", case_15)

    # 16. delete canonical artwork/DAM authority record or replace its bytes
    def case_16(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        art_id = res["frozenAuthorityContext"]["artworkId"]
        plat.artwork.artworks.pop(art_id, None)
        return res
    execute_negative("16_delete_artwork", case_16)

    # 17. remove only frozen engineering authority
    def case_17(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"].pop("engineering", None)
        res["frozenAuthorityContext"].pop("engineeringHash", None)
        return res
    execute_negative("17_remove_frozen_engineering", case_17)

    # 18. remove only frozen placement identity
    def case_18(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"].pop("placementId", None)
        res["frozenAuthorityContext"].pop("placement", None)
        return res
    execute_negative("18_remove_frozen_placement", case_18)

    # 19. remove only frozen main camera authority
    def case_19(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"].pop("camera", None)
        return res
    execute_negative("19_remove_frozen_camera", case_19)

    # 20. remove only frozen scene authority
    def case_20(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"].pop("scene", None)
        return res
    execute_negative("20_remove_frozen_scene", case_20)

    # 21. remove only frozen DOOR_DETAIL request recipe
    def case_21(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["view_recipes"].pop("DOOR_DETAIL", None)
        return res
    execute_negative("21_remove_frozen_door_detail", case_21)

    # 22. remove only frozen ASSEMBLED_FRONT request recipe
    def case_22(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["view_recipes"].pop("ASSEMBLED_FRONT", None)
        return res
    execute_negative("22_remove_frozen_assembled_front", case_22)

    # 23. leave final pack/worker/serialized copies mutually consistent while frozen authority is absent for one required field -> still FAIL
    def case_23(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"].pop("tenant_id", None)
        return res
    execute_negative("23_frozen_missing_tenant_consistent_pack", case_23)


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

    # 11. damRef changed to another valid asset
    other_dam = plat.dam.put(
        tenant_id=cab.tenantId,
        kind="product_truth_view",
        name="other_view.png",
        data=b"other_png_bytes",
        metadata={
            "view": "OTHER",
            "renderPackId": pack["renderPackId"],
            "sourcePath": str(tmp_path / "other.png"),
            "sourceJobId": pack["blenderJobId"],
        },
    )
    bad_dref = copy.deepcopy(pack)
    bad_dref["views"]["DOOR_DETAIL"]["damRef"] = other_dam.asset_id
    bad_dref["views"]["DOOR_DETAIL"]["artifactId"] = other_dam.asset_id
    fails_dref = validate_product_truth_render_pack(bad_dref, plat=plat)
    assert any(f in fails_dref for f in ("view_dam_role_mismatch_DOOR_DETAIL", "view_dam_sha_mismatch_DOOR_DETAIL"))

    # 12. DAM asset/source-lineage changed to another valid path while SHA/size remain copied/equal
    orig_sp = dam_obj.metadata.get("sourcePath")
    dam_obj.metadata["sourcePath"] = str(tmp_path / "tampered_source" / "door_detail.png")
    fails_sp = validate_product_truth_render_pack(pack, plat=plat)
    assert "view_dam_source_path_mismatch_DOOR_DETAIL" in fails_sp
    dam_obj.metadata["sourcePath"] = orig_sp

    # 13. Swap DOOR_DETAIL and ASSEMBLED_FRONT artifact identities
    swapped_dam = copy.deepcopy(pack)
    d_dam = pack["views"]["DOOR_DETAIL"]["damRef"]
    f_dam = pack["views"]["ASSEMBLED_FRONT"]["damRef"]
    swapped_dam["views"]["DOOR_DETAIL"]["damRef"] = f_dam
    swapped_dam["views"]["DOOR_DETAIL"]["artifactId"] = f_dam
    swapped_dam["views"]["ASSEMBLED_FRONT"]["damRef"] = d_dam
    swapped_dam["views"]["ASSEMBLED_FRONT"]["artifactId"] = d_dam
    fails_swap = validate_product_truth_render_pack(swapped_dam, plat=plat)
    assert "view_dam_role_mismatch_DOOR_DETAIL" in fails_swap
    assert "view_dam_role_mismatch_ASSEMBLED_FRONT" in fails_swap

    # 14. Same SHA/size with wrong source job
    orig_sj = dam_obj.metadata.get("sourceJobId")
    dam_obj.metadata["sourceJobId"] = "wrong_job_id"
    fails_sj = validate_product_truth_render_pack(pack, plat=plat)
    assert "view_dam_job_id_mismatch_DOOR_DETAIL" in fails_sj
    dam_obj.metadata["sourceJobId"] = orig_sj

    # 15. Copied bytes with wrong dimensions in worker view
    bad_dim_w = copy.deepcopy(pack)
    bad_dim_w["views"]["DOOR_DETAIL"]["workerView"]["width"] = 999
    bad_dim_w["workerViews"]["DOOR_DETAIL"]["width"] = 999
    fails_wdim = validate_product_truth_render_pack(bad_dim_w, plat=plat)
    assert "view_worker_dimension_mismatch_DOOR_DETAIL" in fails_wdim

    # 16. Nested worker view and top-level worker view agreement required
    no_top = copy.deepcopy(pack)
    no_top["workerViews"].pop("DOOR_DETAIL", None)
    fails_notop = validate_product_truth_render_pack(no_top, plat=plat)
    assert "view_missing_top_worker_view_DOOR_DETAIL" in fails_notop

    no_nested = copy.deepcopy(pack)
    no_nested["views"]["DOOR_DETAIL"].pop("workerView", None)
    fails_nonested = validate_product_truth_render_pack(no_nested, plat=plat)
    assert "view_missing_nested_worker_view_DOOR_DETAIL" in fails_nonested

    # 17. Missing / wrong / swapped blenderJobId
    no_pjob = copy.deepcopy(pack)
    no_pjob.pop("blenderJobId", None)
    fails_npjob = validate_product_truth_render_pack(no_pjob, plat=plat)
    assert "pack_missing_blenderJobId" in fails_npjob

    no_rjob = copy.deepcopy(pack)
    no_rjob["views"]["DOOR_DETAIL"].pop("blenderJobId", None)
    fails_nrjob = validate_product_truth_render_pack(no_rjob, plat=plat)
    assert "view_missing_jobId_DOOR_DETAIL" in fails_nrjob

    no_wjob = copy.deepcopy(pack)
    no_wjob["views"]["DOOR_DETAIL"]["workerView"].pop("blenderJobId", None)
    no_wjob["workerViews"]["DOOR_DETAIL"].pop("blenderJobId", None)
    fails_nwjob = validate_product_truth_render_pack(no_wjob, plat=plat)
    assert "view_worker_missing_jobId_DOOR_DETAIL" in fails_nwjob


def test_runner_frozen_recipe_semantic_authority_fails_closed(tmp_path):
    import importlib.util
    import sys
    from fox3d.evidence import prepare_evidence_lineage
    from fox3d.product_truth import run_phase_841_scenario

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_product_truth_render_e2e.py"
    spec = importlib.util.spec_from_file_location("run_pt_semantic_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_pt_semantic_test"] = mod
    spec.loader.exec_module(mod)
    sha = "d" * 40

    def inspect(root, allow_dirty=False):
        return prepare_evidence_lineage(head_sha=sha, porcelain="", allow_dirty=allow_dirty)

    def execute_negative(name, scenario_fn):
        docs = tmp_path / f"docs_{name}"
        docs.mkdir(parents=True, exist_ok=True)
        acc = tmp_path / f"acc_{name}"
        rc = mod.main(
            ["--docs-root", str(docs), "--expected-commit", sha],
            hooks={
                "inspect": inspect,
                "platform": lambda root: Platform(root=root, mock_blender=True),
                "scenario": scenario_fn,
                "acceptance_root": acc,
            },
        )
        assert rc == 1, f"Case {name} failed to exit with code 1, got {rc}"
        assert not (docs / "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json").exists(), (
            f"Case {name} published acceptance artifact on failure"
        )

    # 1. frozen main camera: change focalLengthMm but keep stale cameraRecipeHash
    def case_1(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["focalLengthMm"] = 50.0
        return res
    execute_negative("sem_1_main_camera_focal_stale_hash", case_1)

    # 2. frozen main camera: change location/lookAt/sensor/resolution/safeMargin while keeping stale hash
    def case_2_loc(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["location"] = [9.0, -9.0, 9.0]
        return res
    execute_negative("sem_2_main_camera_location_stale_hash", case_2_loc)

    def case_2_res(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["resolution"] = {"width": 1024, "height": 1024}
        return res
    execute_negative("sem_2_main_camera_resolution_stale_hash", case_2_res)

    def case_2_margin(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["safeMargin"] = 0.25
        return res
    execute_negative("sem_2_main_camera_margin_stale_hash", case_2_margin)

    # 3. frozen main camera: change only cameraRecipeHash while fields remain unchanged
    def case_3(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["cameraRecipeHash"] = "tampered_hash_00000000000000000000000000000000000000000000000000000000"
        return res
    execute_negative("sem_3_main_camera_hash_only_tamper", case_3)

    # 4. frozen scene: change samples/engine/lighting/scene identity while keeping stale sceneRecipeHash
    def case_4_samples(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["scene"]["samples"] = 99
        return res
    execute_negative("sem_4_scene_samples_stale_hash", case_4_samples)

    def case_4_lighting(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["scene"]["lightingPreset"] = "STUDIO_WARM"
        return res
    execute_negative("sem_4_scene_lighting_stale_hash", case_4_lighting)

    # 5. frozen scene: change only sceneRecipeHash while fields remain unchanged
    def case_5(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["scene"]["sceneRecipeHash"] = "tampered_scene_hash_00000000000000000000000000000000000000000000000000000000"
        return res
    execute_negative("sem_5_scene_hash_only_tamper", case_5)

    # 6. frozen DOOR_DETAIL: change semantic camera field but retain stale hash
    def case_6(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["view_recipes"]["DOOR_DETAIL"]["focalLengthMm"] = 35.0
        return res
    execute_negative("sem_6_door_detail_focal_stale_hash", case_6)

    # 7. frozen DOOR_DETAIL: hash-only tamper
    def case_7(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["view_recipes"]["DOOR_DETAIL"]["cameraRecipeHash"] = "tampered_door_hash_00000000000000000000000000000000000000000000000000"
        return res
    execute_negative("sem_7_door_detail_hash_only_tamper", case_7)

    # 8. frozen ASSEMBLED_FRONT: change semantic camera field but retain stale hash
    def case_8(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["view_recipes"]["ASSEMBLED_FRONT"]["focalLengthMm"] = 35.0
        return res
    execute_negative("sem_8_assembled_front_focal_stale_hash", case_8)

    # 9. frozen ASSEMBLED_FRONT: hash-only tamper
    def case_9(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["view_recipes"]["ASSEMBLED_FRONT"]["cameraRecipeHash"] = "tampered_assembled_hash_000000000000000000000000000000000000000000000"
        return res
    execute_negative("sem_9_assembled_front_hash_only_tamper", case_9)

    # 10. swap frozen DOOR_DETAIL and ASSEMBLED_FRONT recipe objects/hashes
    def case_10_swap_objects(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        d_rec = copy.deepcopy(res["frozenAuthorityContext"]["view_recipes"]["DOOR_DETAIL"])
        f_rec = copy.deepcopy(res["frozenAuthorityContext"]["view_recipes"]["ASSEMBLED_FRONT"])
        res["frozenAuthorityContext"]["view_recipes"]["DOOR_DETAIL"] = f_rec
        res["frozenAuthorityContext"]["view_recipes"]["ASSEMBLED_FRONT"] = d_rec
        return res
    execute_negative("sem_10_swap_view_recipe_objects", case_10_swap_objects)

    def case_10_swap_hashes(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        d_hash = res["frozenAuthorityContext"]["view_recipes"]["DOOR_DETAIL"]["cameraRecipeHash"]
        f_hash = res["frozenAuthorityContext"]["view_recipes"]["ASSEMBLED_FRONT"]["cameraRecipeHash"]
        res["frozenAuthorityContext"]["view_recipes"]["DOOR_DETAIL"]["cameraRecipeHash"] = f_hash
        res["frozenAuthorityContext"]["view_recipes"]["ASSEMBLED_FRONT"]["cameraRecipeHash"] = d_hash
        return res
    execute_negative("sem_10_swap_view_recipe_hashes", case_10_swap_hashes)

    # 11. malformed/missing required numeric recipe fields (bool/string/NaN/Inf)
    def case_11_bool(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["focalLengthMm"] = True
        return res
    execute_negative("sem_11_camera_focal_bool", case_11_bool)

    def case_11_str(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["focalLengthMm"] = "85.0"
        return res
    execute_negative("sem_11_camera_focal_str", case_11_str)

    def case_11_nan(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["focalLengthMm"] = float("nan")
        return res
    execute_negative("sem_11_camera_focal_nan", case_11_nan)

    def case_11_inf(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["camera"]["focalLengthMm"] = float("inf")
        return res
    execute_negative("sem_11_camera_focal_inf", case_11_inf)

    # 12. frozen engineering body/hash contradiction if both copies are present
    def case_12_hash_tamper(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["engineeringHash"] = "contradictory_eng_hash_00000000000000000000000000000000000000000000"
        return res
    execute_negative("sem_12_engineering_hash_contradiction", case_12_hash_tamper)

    def case_12_body_tamper(plat, **kw):
        res = run_phase_841_scenario(plat, evidence_code_commit=sha)
        res["frozenAuthorityContext"]["engineering"]["width"] = 1400.0
        return res
    execute_negative("sem_12_engineering_body_contradiction", case_12_body_tamper)


def test_instruction_commit_lineage_and_format():
    from fox3d.product_truth import inspect_instruction_sha
    sha = inspect_instruction_sha("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md")
    assert len(sha) == 40, f"Expected 40-char commit SHA, got {sha!r}"
    assert all(c in "0123456789abcdef" for c in sha), f"Invalid hex characters in {sha}"
    assert sha != "2b1b174092b3bc3983226782390885141154f243", "Instruction SHA must not match known typo"




