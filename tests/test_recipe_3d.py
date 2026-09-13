"""Tests for Sonaqueen Recipe 3D modeling, assumption resolution, and API routes."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.recipe_3d import (
    build_recipe_bom,
    build_recipe_spec,
    generate_recipe_3d_product,
    get_recipe_3d_dir,
    get_recipe_3d_status,
    resolve_recipe_preview_assumptions,
)
from fox3d.recipe_admin_api import recipe_router
from fox3d.recipe_workbench import RecipeWorkbench

HEADERS = {"X-Tenant-Id": "sonaqueen-home"}


def test_resolve_recipe_preview_assumptions_staggered():
    draft = {
        "sku": "MY-012",
        "family": "STAGGERED_OPEN_CUBBY",
        "values": {
            "widthMm": {"value": 602.0},
            "depthMm": {"value": 300.0},
            "heightMm": {"value": 1802.0},
        },
    }
    result = resolve_recipe_preview_assumptions(draft)
    resolved = result["resolved"]
    assumptions = result["assumptions"]

    assert resolved["widthMm"] == 602.0
    assert resolved["depthMm"] == 300.0
    assert resolved["heightMm"] == 1802.0
    assert resolved["boardThicknessMm"] == 15.0
    assert resolved["backPanel"] is False

    fields = [a["field"] for a in assumptions]
    assert "boardThicknessMm" in fields
    assert "backPanel" in fields
    assert "staggerPattern" in fields

    thick_a = next(a for a in assumptions if a["field"] == "boardThicknessMm")
    assert thick_a["source"] == "PREVIEW_ASSUMPTION"
    assert thick_a["value"] == 15.0


def test_resolve_recipe_preview_assumptions_doors():
    draft = {
        "sku": "LI-D40",
        "family": "STACKED_HINGED_CABINET",
        "values": {
            "widthMm": {"value": 400.0},
            "depthMm": {"value": 350.0},
            "heightMm": {"value": 1800.0},
            "doorCount": {"value": 2},
        },
    }
    result = resolve_recipe_preview_assumptions(draft)
    assumptions = result["assumptions"]
    fields = [a["field"] for a in assumptions]
    assert "doorGapMm" in fields


def test_build_recipe_spec_staggered_cubby():
    draft = {
        "sku": "MY-012",
        "name": "日系禪風十二格書櫃",
        "family": "STAGGERED_OPEN_CUBBY",
        "values": {
            "widthMm": {"value": 602.0},
            "depthMm": {"value": 300.0},
            "heightMm": {"value": 1802.0},
            "rowCount": {"value": 6},
            "compartmentCount": {"value": 12},
            "labelledNarrowOpeningWidthMm": {"value": 181.5},
            "labelledWideOpeningWidthMm": {"value": 373.5},
        },
    }
    spec = build_recipe_spec(draft, tenant_id="sonaqueen-home")

    assert spec["sku"] == "MY-012"
    assert spec["width"] == 602.0
    assert spec["height"] == 1802.0
    assert spec["depth"] == 300.0
    assert spec["shelfCount"] == 5
    assert spec["compartmentCount"] == 12

    roles = [c["role"] for c in spec["components"]]
    assert roles.count("left") == 1
    assert roles.count("right") == 1
    assert roles.count("top") == 1
    assert roles.count("bottom") == 1
    assert roles.count("shelf") == 5
    assert roles.count("divider") == 6

    # Verify alternating divider x-positions
    dividers = [c for c in spec["components"] if c["role"] == "divider"]
    div0_x = dividers[0]["location"][0]
    div1_x = dividers[1]["location"][0]
    assert div0_x != div1_x  # Alternating stagger positions


def test_build_recipe_bom():
    draft = {
        "sku": "MY-012",
        "name": "日系禪風十二格書櫃",
        "family": "STAGGERED_OPEN_CUBBY",
        "values": {
            "widthMm": {"value": 602.0},
            "depthMm": {"value": 300.0},
            "heightMm": {"value": 1802.0},
        },
    }
    spec = build_recipe_spec(draft, tenant_id="sonaqueen-home")
    bom = build_recipe_bom(spec)

    assert bom["sku"] == "MY-012"
    assert bom["totalParts"] == len(spec["components"])
    assert len(bom["lines"]) == bom["totalParts"]
    first = bom["lines"][0]
    assert "partId" in first
    assert "partName" in first
    assert "lengthMm" in first
    assert "widthMm" in first
    assert "thicknessMm" in first


@pytest.fixture
def api_client(tmp_path):
    app = FastAPI()
    from fox3d.platform import Platform

    plat = Platform(root=tmp_path, mock_blender=True)
    app.include_router(recipe_router(lambda: plat))
    with TestClient(app) as client:
        yield client, tmp_path, plat


def test_recipe_3d_api_lifecycle(api_client):
    client, tmp_path, plat = api_client
    sku = "MY-012"

    # 1. Status before generation
    status_res = client.get(f"/api/recipe-library/products/{sku}/3d/status", headers=HEADERS)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["generated"] is False
    assert status_data["sku"] == sku

    # 2. Render image before generation returns 404
    render_res = client.get(f"/api/recipe-library/products/{sku}/3d/render", headers=HEADERS)
    assert render_res.status_code == 404

    # 3. Generate 3D
    gen_res = client.post(f"/api/recipe-library/products/{sku}/3d/generate", headers=HEADERS)
    assert gen_res.status_code == 200, gen_res.text
    gen_data = gen_res.json()
    assert gen_data["generated"] is True
    assert gen_data["assets"]["png"] is True
    assert gen_data["assets"]["blend"] is True
    assert gen_data["assets"]["glb"] is True
    assert len(gen_data["assumptions"]) > 0
    assert gen_data["bom"]["totalParts"] > 0

    # 4. Status after generation
    status_res2 = client.get(f"/api/recipe-library/products/{sku}/3d/status", headers=HEADERS)
    assert status_res2.status_code == 200
    assert status_res2.json()["generated"] is True

    # 5. Render image stream
    render_res2 = client.get(f"/api/recipe-library/products/{sku}/3d/render", headers=HEADERS)
    assert render_res2.status_code == 200
    assert render_res2.headers["content-type"] == "image/png"
    assert len(render_res2.content) > 0

    # 6. Download .blend
    blend_res = client.get(f"/api/recipe-library/products/{sku}/3d/download/blend", headers=HEADERS)
    assert blend_res.status_code == 200
    assert "attachment" in blend_res.headers.get("content-disposition", "")
    assert blend_res.content == b"BLENDER_MOCK_BLEND"

    # 7. Download .glb
    glb_res = client.get(f"/api/recipe-library/products/{sku}/3d/download/glb", headers=HEADERS)
    assert glb_res.status_code == 200
    assert "model/gltf-binary" in glb_res.headers.get("content-type", "")
    assert len(glb_res.content) > 0

    # 8. Download .png
    png_res = client.get(f"/api/recipe-library/products/{sku}/3d/download/png", headers=HEADERS)
    assert png_res.status_code == 200
    assert "image/png" in png_res.headers.get("content-type", "")

    # 9. Invalid format
    invalid_res = client.get(f"/api/recipe-library/products/{sku}/3d/download/obj", headers=HEADERS)
    assert invalid_res.status_code == 400
