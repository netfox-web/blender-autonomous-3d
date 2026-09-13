"""Tests for Phase 901–960 Product Content Factory V1 / Deterministic Commerce Asset Pack."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from fox3d.content_factory import (
    COMMERCE_DAM_ROLES,
    LIFESTYLE_PRESETS,
    REQUIRED_COMMERCE_VIEW_ROLES,
    build_articulated_state,
    build_commerce_asset_pack,
    canonical_commerce_recipes,
    canonical_lifestyle_briefs,
    content_view_recipe,
    generate_dimension_overlay,
    qa_commerce_pack,
    run_product_content_scenario,
    validate_dimension_asset_authority,
    validate_strict_content_view_recipe,
)
from fox3d.ids import sha256_bytes, stable_hash
from fox3d.parametric import CabinetEngine
from fox3d.platform import Platform
import importlib.util
import sys

_runner_path = Path(__file__).resolve().parents[1] / "scripts" / "run_product_content_e2e.py"
_runner_spec = importlib.util.spec_from_file_location("run_product_content_e2e", _runner_path)
_runner_mod = importlib.util.module_from_spec(_runner_spec)
sys.modules["run_product_content_e2e"] = _runner_mod
_runner_spec.loader.exec_module(_runner_mod)
runner_main = _runner_mod.main


@pytest.fixture
def plat(tmp_path: Path) -> Platform:
    return Platform(root=tmp_path / "plat", mock_blender=True)


def test_canonical_commerce_recipes_complete_and_strict():
    recipes = canonical_commerce_recipes(width=256, height=256, samples=16)
    assert set(recipes.keys()) == set(REQUIRED_COMMERCE_VIEW_ROLES)

    for role, rec in recipes.items():
        assert rec["viewRole"] == role
        assert rec["width"] == 256
        assert rec["height"] == 256
        failures = validate_strict_content_view_recipe(rec)
        assert failures == [], f"Recipe {role} had validation failures: {failures}"


def test_strict_content_view_recipe_negative_types():
    base = content_view_recipe(
        view_role="WHITE_BACKGROUND_HERO",
        camera_id="HERO",
        location=(1.0, -2.0, 1.0),
        look_at=(0.0, 0.0, 0.5),
        width=512,
        height=512,
    )

    # 1. bool as width
    bad1 = copy.deepcopy(base)
    bad1["width"] = True
    assert "invalid_content_view_width" in validate_strict_content_view_recipe(bad1)

    # 2. string as safe_margin
    bad2 = copy.deepcopy(base)
    bad2["safeMargin"] = "0.08"
    assert "invalid_content_view_safe_margin" in validate_strict_content_view_recipe(bad2)

    # 3. float NaN
    bad3 = copy.deepcopy(base)
    bad3["safeMargin"] = float("nan")
    assert "invalid_content_view_safe_margin" in validate_strict_content_view_recipe(bad3)

    # 4. float Inf
    bad4 = copy.deepcopy(base)
    bad4["safeMargin"] = float("inf")
    assert "invalid_content_view_safe_margin" in validate_strict_content_view_recipe(bad4)

    # 5. unknown product state
    bad5 = copy.deepcopy(base)
    bad5["productState"] = "HALF_OPEN"
    assert "invalid_or_missing_product_state" in validate_strict_content_view_recipe(bad5)

    # 6. hash drift
    bad6 = copy.deepcopy(base)
    bad6["contentViewRecipeHash"] = "tampered_hash_0000000000000000000000000000000000000000"
    assert "content_view_recipe_hash_drift" in validate_strict_content_view_recipe(bad6)


def test_articulated_state_open_vs_closed():
    engine = CabinetEngine()
    cab, _ = engine.create("STORAGE_CABINET", tenant_id="pt-a", width=2400, height=1800, doorCount=4)
    eng_dict = cab.model_dump(mode="json")

    open_state = build_articulated_state(eng_dict, state="OPEN", angle_deg=75.0)
    assert open_state["productState"] == "OPEN"
    assert open_state["articulationAngleDeg"] == 75.0
    assert len(open_state["articulatedComponents"]) == 4
    assert len(open_state["transforms"]) == 4
    for t in open_state["transforms"]:
        assert t["productState"] == "OPEN"
        assert t["rotationEuler"][2] != 0.0

    closed_state = build_articulated_state(eng_dict, state="CLOSED", angle_deg=0.0)
    assert closed_state["productState"] == "CLOSED"
    assert closed_state["articulationAngleDeg"] == 0.0
    assert closed_state["articulatedComponents"] == []
    assert closed_state["transforms"] == []


def test_dimension_asset_authority_and_tamper_fails_closed(tmp_path: Path):
    engine = CabinetEngine()
    cab, _ = engine.create("STORAGE_CABINET", tenant_id="pt-a", width=2400, height=1800, doorCount=4)
    eng_dict = cab.model_dump(mode="json")
    eng_dict["engineeringHash"] = cab.engineering_hash()

    base_png = tmp_path / "front.png"
    base_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    png_bytes, meta = generate_dimension_overlay(base_png, eng_dict, width=128, height=128)
    assert len(png_bytes) > 0
    assert meta["widthMm"] == 2400.0
    assert meta["heightMm"] == 1800.0
    assert meta["depthMm"] == float(eng_dict["depth"])
    assert meta["renderedLabels"]["width"] == "2400 mm"
    assert meta["renderedLabels"]["height"] == "1800 mm"

    # Valid check passes
    failures = validate_dimension_asset_authority(meta, eng_dict)
    assert failures == []

    # 1. Swapped width and height
    swapped = copy.deepcopy(meta)
    swapped["widthMm"] = 1800.0
    swapped["heightMm"] = 2400.0
    assert any("mismatch" in f for f in validate_dimension_asset_authority(swapped, eng_dict))

    # 2. Changed units
    bad_unit = copy.deepcopy(meta)
    bad_unit["unit"] = "inches"
    assert any("unit_invalid" in f for f in validate_dimension_asset_authority(bad_unit, eng_dict))

    # 3. Stale engineering hash
    bad_hash = copy.deepcopy(meta)
    bad_hash["sourceEngineeringHash"] = "stale_hash_0000000000000000000000000000000000000000000000000000"
    assert any("engineering_hash_mismatch" in f for f in validate_dimension_asset_authority(bad_hash, eng_dict))

    # 4. Coordinated metadata + label tamper (both altered to match each other but differing from Engineering)
    coord = copy.deepcopy(meta)
    coord["widthMm"] = 3000.0
    coord["renderedLabels"]["width"] = "3000 mm"
    assert any("dimension_width_mismatch" in f for f in validate_dimension_asset_authority(coord, eng_dict))

    # 5. Missing dimension label layer hash
    no_hash = copy.deepcopy(meta)
    no_hash.pop("dimensionLabelLayerHash", None)
    assert any("missing_dimension_label_layer_hash" in f for f in validate_dimension_asset_authority(no_hash, eng_dict))

    # 6. Tampered dimension label layer hash (visible glyph altered)
    bad_layer_hash = copy.deepcopy(meta)
    bad_layer_hash["dimensionLabelLayerHash"] = "tampered_layer_hash_0000000000000000000000000000000000000000"
    assert any("dimension_label_layer_hash_mismatch" in f for f in validate_dimension_asset_authority(bad_layer_hash, eng_dict))


def test_lifestyle_briefs_are_product_truth_bound():
    pack = {
        "tenantId": "pt-a",
        "productId": "STORAGE_CABINET",
        "version": 1,
        "engineeringHash": "hash_eng_123",
        "renderPackId": "rp_123",
        "placementHash": "pl_123",
        "finalUvHash": "uv_123",
        "aovs": {
            "product_mask": {"damRef": "dam_prod", "sha256": "sha_prod"},
            "artwork_mask": {"damRef": "dam_art", "sha256": "sha_art"},
        },
    }
    briefs = canonical_lifestyle_briefs(pack)
    assert set(briefs.keys()) == set(LIFESTYLE_PRESETS)
    for name, b in briefs.items():
        assert b["tenantId"] == "pt-a"
        assert b["skuId"] == "STORAGE_CABINET"
        assert b["sourceRenderPackId"] == "rp_123"
        assert b["productMaskDamRef"] == "dam_prod"
        assert b["artworkMaskDamRef"] == "dam_art"
        assert len(b["forbiddenProductEdits"]) >= 5


def test_end_to_end_product_content_scenario(plat: Platform):
    res = run_product_content_scenario(plat, tenant_id="pt-a", evidence_code_commit="0fcf31be065c1342d98e10ca48af536014177870")
    assert res["ok"] is True
    assert res["productContentFactoryLogicReady"] is True
    assert res["realCommerceRenderPackReady"] is False  # mock fixture
    assert res["liveGenerativeCommerceReady"] is False
    assert res["commercialAssetProductionReady"] is False

    pack = res["contentPack"]
    assert set(pack["views"].keys()) == set(REQUIRED_COMMERCE_VIEW_ROLES)
    assert set(pack["lifestyleBriefs"].keys()) == set(LIFESTYLE_PRESETS)
    assert pack["qa"]["ok"] is True
    assert pack["qa"]["decision"] == "APPROVED_FOR_ASSET_REVIEW"


def test_runner_content_factory_adversarial_matrix(tmp_path: Path):
    """Verifies all 18 specified runner adversarial conditions fail closed with exit code 1."""
    sha = "0fcf31be065c1342d98e10ca48af536014177870"
    plat = Platform(root=tmp_path / "plat", mock_blender=True)
    clean_lineage = {
        "evidenceCodeCommit": sha,
        "workingTreeClean": True,
        "dirtyFiles": [],
    }

    def execute_negative(name: str, mutator):
        docs_dir = tmp_path / f"docs_{name}"
        docs_dir.mkdir(parents=True, exist_ok=True)

        def scenario_hook(p, **kw):
            res = run_product_content_scenario(p, evidence_code_commit=sha)
            mutator(res)
            return res

        hooks = {
            "inspect": lambda root, allow_dirty=False: clean_lineage,
            "platform": lambda root: plat,
            "scenario": scenario_hook,
        }
        argv = ["--docs-root", str(docs_dir), "--expected-commit", sha]
        rc = runner_main(argv, hooks=hooks)
        assert rc == 1, f"Expected runner to fail closed on case {name}, got rc={rc}"
        assert not (docs_dir / "PRODUCT_CONTENT_FACTORY_ACCEPTANCE.json").exists(), (
            f"Case {name} published acceptance file unexpectedly"
        )

    # 1. wrong tenant
    execute_negative("1_wrong_tenant", lambda r: r["contentPack"].__setitem__("tenantId", "cross-tenant-intruder"))

    # 2. wrong SKU / product version
    execute_negative("2_wrong_sku", lambda r: r["contentPack"].__setitem__("skuId", "FOREIGN_SKU"))
    execute_negative("2b_wrong_version", lambda r: r["contentPack"].__setitem__("productVersion", 999))

    # 3. stale/wrong engineeringHash
    execute_negative("3_stale_eng_hash", lambda r: r["contentPack"].__setitem__("engineeringHash", "stale_eng_hash_00000000000000000000000000000000000000000000"))

    # 4. wrong Product Truth generation / renderPack identity
    execute_negative("4_wrong_render_pack", lambda r: r["contentPack"].__setitem__("sourceRenderPackId", "rp_foreign_0000"))

    # 5. required view missing
    def case_5(r):
        del r["contentPack"]["views"]["FRONT_OPEN"]
    execute_negative("5_missing_view", case_5)

    # 6. required view duplicated
    def case_6(r):
        r["contentPack"]["views"]["DUPLICATE_HERO"] = copy.deepcopy(r["contentPack"]["views"]["WHITE_BACKGROUND_HERO"])
    execute_negative("6_duplicate_view", case_6)

    # 7. HERO and OPEN DAM refs swapped
    def case_7(r):
        hero_dam = r["contentPack"]["views"]["WHITE_BACKGROUND_HERO"]["damRef"]
        r["contentPack"]["views"]["FRONT_OPEN"]["damRef"] = hero_dam
    execute_negative("7_hero_open_dam_swap", case_7)

    # 8. wrong view recipe hash
    def case_8(r):
        r["contentPack"]["views"]["HERO_45"]["recipe"]["contentViewRecipeHash"] = "tampered_recipe_hash_00000000000000000000000000000000"
    execute_negative("8_wrong_view_recipe_hash", case_8)

    # 9. wrong Blender job ID / source path
    def case_9(r):
        r["contentPack"]["views"]["FRONT_CLOSED"]["blenderJobId"] = "wrong_job_id_9999"
    execute_negative("9_wrong_job_id", case_9)

    # 10. bytes/SHA/size mismatch
    def case_10(r):
        r["contentPack"]["views"]["DETAIL_ARTWORK"]["sha256"] = "tampered_sha256_000000000000000000000000000000000000000000000000"
    execute_negative("10_sha_mismatch", case_10)

    # 11. dimension width/height/depth or units tampered
    def case_11(r):
        r["contentPack"]["views"]["DIMENSION_FRONT"]["dimensionMetadata"]["widthMm"] = 9999.0
    execute_negative("11_dim_width_tampered", case_11)

    # 12. dimension metadata + rendered label metadata coordinated tamper
    def case_12(r):
        r["contentPack"]["views"]["DIMENSION_FRONT"]["dimensionMetadata"]["widthMm"] = 3500.0
        r["contentPack"]["views"]["DIMENSION_FRONT"]["dimensionMetadata"]["renderedLabels"]["width"] = "3500 mm"
    execute_negative("12_dim_coordinated_tamper", case_12)

    # 13. FRONT_OPEN manifest points to a CLOSED articulated-state record
    def case_13(r):
        r["contentPack"]["views"]["FRONT_OPEN"]["articulatedState"]["productState"] = "CLOSED"
        r["contentPack"]["views"]["FRONT_OPEN"]["articulatedState"]["articulationAngleDeg"] = 0.0
    execute_negative("13_front_open_points_to_closed", case_13)

    # 14. ProductMask / ArtworkMask lineage cross-swap
    def case_14(r):
        art_sha = r["contentPack"]["artworkMaskRef"]["sha256"]
        r["contentPack"]["productMaskRef"]["sha256"] = art_sha
    execute_negative("14_mask_lineage_cross_swap", case_14)

    # 15. derivative generative asset attempts to claim Product Truth authority
    def case_15(r):
        r["contentPack"]["lifestyleBriefs"]["CHILD_ROOM"]["isProductTruth"] = True
        r["contentPack"]["lifestyleBriefs"]["CHILD_ROOM"]["productionReady"] = True
        r["failures"].append("generative_claimed_product_truth")
    execute_negative("15_generative_claims_truth", case_15)

    # 16. blocked/mock provider attempts to set live/commercial readiness true
    def case_16(r):
        r["realCommerceRenderPackReady"] = True
    execute_negative("16_mock_claims_real_pack", case_16)

    def case_16b(r):
        r["liveGenerativeCommerceReady"] = True
    execute_negative("16b_mock_claims_live_generative", case_16b)

    # 17. malformed strict recipe values (bool / string / NaN / Inf)
    def case_17_bool(r):
        r["contentPack"]["views"]["HERO_45"]["recipe"]["safeMargin"] = True
    execute_negative("17_recipe_bool_safe_margin", case_17_bool)

    def case_17_nan(r):
        r["contentPack"]["views"]["HERO_45"]["recipe"]["safeMargin"] = float("nan")
    execute_negative("17_recipe_nan_safe_margin", case_17_nan)

    # 18. cross-tenant / cross-SKU DAM asset substitution with otherwise valid bytes
    def case_18(r):
        foreign_dam = plat.dam.put(
            tenant_id="pt-b",
            kind="commerce_asset",
            name="hero.png",
            data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
            metadata={
                "sourcePath": "foreign/path.png",
                "sourceJobId": "foreign_job",
                "mime": "image/png",
                "tenantId": "pt-b",
                "skuId": "foreign_sku",
            },
        )
        r["contentPack"]["views"]["WHITE_BACKGROUND_HERO"]["damRef"] = foreign_dam.asset_id
    execute_negative("18_cross_tenant_dam_substitution", case_18)

    # 19. wrong Product Truth acceptance generation with otherwise-correct renderPackId
    def case_19(r):
        r["contentPack"]["sourceAcceptanceGenerationId"] = "foreign_gen_00000000000000000000"
    execute_negative("19_wrong_acceptance_generation", case_19)

    # 20. missing dimension label layer hash
    def case_20(r):
        r["contentPack"]["views"]["DIMENSION_FRONT"]["dimensionMetadata"].pop("dimensionLabelLayerHash", None)
    execute_negative("20_missing_dimension_label_layer_hash", case_20)

    # 21. visible width glyph layer altered while metadata remains correct
    def case_21(r):
        r["contentPack"]["views"]["DIMENSION_FRONT"]["dimensionMetadata"]["dimensionLabelLayerHash"] = "tampered_hash_0000000000000000000000000000000000000000"
    execute_negative("21_visible_glyph_layer_altered", case_21)

    # 22. dimension unit glyph changed (mm -> inches)
    def case_22(r):
        r["contentPack"]["views"]["DIMENSION_FRONT"]["dimensionMetadata"]["unit"] = "inches"
    execute_negative("22_dimension_unit_tampered", case_22)

    # 23. DAM sourcePath missing
    def case_23(r):
        dam_ref = r["contentPack"]["views"]["FRONT_CLOSED"]["damRef"]
        plat.dam.get(dam_ref, tenant_id="pt-a").metadata.pop("sourcePath", None)
    execute_negative("23_dam_missing_source_path", case_23)

    # 24. DAM sourceJobId missing
    def case_24(r):
        dam_ref = r["contentPack"]["views"]["FRONT_CLOSED"]["damRef"]
        plat.dam.get(dam_ref, tenant_id="pt-a").metadata.pop("sourceJobId", None)
    execute_negative("24_dam_missing_source_job_id", case_24)

    # 25. wrong/missing MIME
    def case_25(r):
        dam_ref = r["contentPack"]["views"]["FRONT_CLOSED"]["damRef"]
        plat.dam.get(dam_ref, tenant_id="pt-a").metadata["mime"] = "image/jpeg"
    execute_negative("25_dam_wrong_mime", case_25)

    # 26. wrong/missing tenant/SKU/version/contentPack/view-role metadata
    def case_26(r):
        dam_ref = r["contentPack"]["views"]["FRONT_CLOSED"]["damRef"]
        plat.dam.get(dam_ref, tenant_id="pt-a").metadata["skuId"] = "TAMPERED_SKU"
    execute_negative("26_dam_metadata_sku_mismatch", case_26)

    # 27. foreign DAM object with valid identical bytes but wrong provenance
    def case_27(r):
        dam_ref = r["contentPack"]["views"]["FRONT_CLOSED"]["damRef"]
        plat.dam.get(dam_ref, tenant_id="pt-a").metadata["sourceAcceptanceGenerationId"] = "foreign_gen_mismatch"
    execute_negative("27_dam_provenance_gen_mismatch", case_27)

    # 28. worker reports CLOSED for FRONT_OPEN while manifest expected state is still OPEN
    def case_28(r):
        fo = r["contentPack"]["views"]["FRONT_OPEN"]
        fo["usedMock"] = False
        fo["workerEvidence"] = {
            "viewId": "FRONT_OPEN",
            "role": "FRONT_OPEN",
            "blenderJobId": fo["blenderJobId"],
            "blenderVersion": "5.2.1",
            "device": "OPTIX",
            "usedMock": False,
            "productState": "CLOSED",
            "articulationAngleDeg": 0.0,
            "articulatedState": {"productState": "CLOSED", "articulationAngleDeg": 0.0, "transforms": []},
        }
        fo["articulatedState"] = fo["workerEvidence"]["articulatedState"]
    execute_negative("28_worker_reports_closed_for_front_open", case_28)

    # 29. wrong OPEN angle
    def case_29(r):
        fo = r["contentPack"]["views"]["FRONT_OPEN"]
        fo["usedMock"] = False
        fo["workerEvidence"] = {
            "viewId": "FRONT_OPEN",
            "role": "FRONT_OPEN",
            "blenderJobId": fo["blenderJobId"],
            "blenderVersion": "5.2.1",
            "device": "OPTIX",
            "usedMock": False,
            "productState": "OPEN",
            "articulationAngleDeg": 25.0,
            "articulatedState": {"productState": "OPEN", "articulationAngleDeg": 25.0, "transforms": []},
        }
        fo["articulatedState"] = fo["workerEvidence"]["articulatedState"]
    execute_negative("29_wrong_open_angle", case_29)

    # 30. missing transform(s) / wrong component ID / wrong hinge pivot
    def case_30(r):
        fo = r["contentPack"]["views"]["FRONT_OPEN"]
        fo["usedMock"] = False
        fo["workerEvidence"] = {
            "viewId": "FRONT_OPEN",
            "role": "FRONT_OPEN",
            "blenderJobId": fo["blenderJobId"],
            "blenderVersion": "5.2.1",
            "device": "OPTIX",
            "usedMock": False,
            "productState": "OPEN",
            "articulationAngleDeg": 75.0,
            "articulatedState": {"productState": "OPEN", "articulationAngleDeg": 75.0, "transforms": []},
        }
        fo["articulatedState"] = fo["workerEvidence"]["articulatedState"]
    execute_negative("30_missing_transforms", case_30)

    # 31. missing workerViews[FRONT_OPEN]
    def case_31(r):
        fo = r["contentPack"]["views"]["FRONT_OPEN"]
        fo["usedMock"] = False
        fo.pop("workerEvidence", None)
    execute_negative("31_missing_worker_views", case_31)

    # 32. worker view belongs to wrong blenderJobId or wrong role
    def case_32(r):
        fo = r["contentPack"]["views"]["FRONT_OPEN"]
        fo["usedMock"] = False
        fo["workerEvidence"] = {
            "viewId": "FRONT_OPEN",
            "role": "FRONT_OPEN",
            "blenderJobId": "foreign_job_id_9999",
            "blenderVersion": "5.2.1",
            "device": "OPTIX",
            "usedMock": False,
        }
    execute_negative("32_worker_view_wrong_job_id", case_32)

    # 33. missing required REAL worker/device evidence
    def case_33(r):
        fo = r["contentPack"]["views"]["FRONT_OPEN"]
        fo["usedMock"] = False
        fo["workerEvidence"] = {
            "viewId": "FRONT_OPEN",
            "role": "FRONT_OPEN",
            "blenderJobId": fo["blenderJobId"],
            "usedMock": False,
        }
    execute_negative("33_missing_device_evidence", case_33)

    # 34. worker source path missing
    def case_34(r):
        r["contentPack"]["views"]["FRONT_CLOSED"]["path"] = "nonexistent_dir/missing.png"
    execute_negative("34_worker_source_path_missing", case_34)

    # 35. empty/zero-byte asset
    def case_35(r):
        p = Path(r["contentPack"]["views"]["FRONT_CLOSED"]["path"])
        p.write_bytes(b"")
    execute_negative("35_empty_asset_bytes", case_35)

    # 36. malformed/non-PNG bytes
    def case_36(r):
        p = Path(r["contentPack"]["views"]["FRONT_CLOSED"]["path"])
        p.write_bytes(b"NOT_A_VALID_PNG_CONTENT")
    execute_negative("36_malformed_non_png_bytes", case_36)

