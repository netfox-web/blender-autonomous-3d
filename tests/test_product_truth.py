"""Phase 841–900 Product Truth Render Pack + Generative Gateway. MOCK/unit — not Production Ready."""

from __future__ import annotations

import copy
import json
from pathlib import Path

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
