"""Admin page /admin/kd — KD catalog and structure generation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.features import resolved_features

TENANT = "sonaqueen-home"
HDR = {"X-Tenant-Id": TENANT}
PAGES = Path(__file__).resolve().parents[1] / "src/fox3d/static/pages"


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def test_kd_plugin_claims_features() -> None:
    kd = next(f for f in resolved_features() if f["id"] == "kd")
    structures = next(f for f in resolved_features() if f["id"] == "structures")
    assert kd["kind"] == "page" and kd["href"] == "/admin/kd"
    assert structures["kind"] == "page" and structures["href"] == "/admin/kd#structures"
    assert "/admin/kd" in kd["prefixes"]


def test_kd_page_loads_shared_shell(client: TestClient) -> None:
    res = client.get("/admin/kd")
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in res.text
    assert "/admin/pages/assets/kd.js" in res.text
    assert "/admin/pages/assets/kd.css" in res.text
    assert 'aria-label="工作台導覽"' not in res.text


@pytest.mark.parametrize("asset", ["kd.js", "kd.css"])
def test_kd_page_assets(client: TestClient, asset: str) -> None:
    res = client.get(f"/admin/pages/assets/{asset}")
    assert res.status_code == 200
    assert res.content


def test_kd_get_apis(client: TestClient) -> None:
    types = client.get("/api/kd/product-types", headers=HDR)
    assert types.status_code == 200
    assert types.json()["items"]

    ready = client.get("/api/kd/readiness", headers=HDR)
    assert ready.status_code == 200
    body = ready.json()
    assert "productionReadyScope" in body


def test_kd_post_apis(client: TestClient) -> None:
    sku = client.post("/api/kd/skus", headers=HDR, json={"kind": "BEDSIDE_CABINET", "render": False})
    assert sku.status_code == 200
    assert sku.json().get("spec")

    catalog = client.post("/api/kd/catalog", headers=HDR, json={"count": 4, "render": False})
    assert catalog.status_code == 200
    assert catalog.json().get("catalog")

    cand = client.post("/api/kd/candidates", headers=HDR, json={"count": 2})
    assert cand.status_code == 200
    assert cand.json().get("candidates")

    retail = client.post(
        "/api/retail/fixtures",
        headers=HDR,
        json={"family": "COUNTER_DISPLAY", "facing": 2, "render": False},
    )
    assert retail.status_code == 200
    assert retail.json().get("fixtureId") or retail.json().get("spec")

    pack = client.post(
        "/api/packaging/structures",
        headers=HDR,
        json={"family": "RSC_CARTON", "productDims": {"width": 120, "height": 80, "depth": 40}, "render": False},
    )
    assert pack.status_code == 200

    acr = client.post(
        "/api/acrylic/products",
        headers=HDR,
        json={"kind": "MENU_STAND", "sheetSku": "ACR_CLEAR_5", "render": False},
    )
    assert acr.status_code == 200


def _js() -> str:
    return (PAGES / "kd.js").read_text(encoding="utf-8")


def _js_function(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    end = js.index("\n  }\n", start)
    return js[start:end]


def test_kd_js_tenant_frozen_until_reload() -> None:
    js = _js()
    assert "var activeTenant = DEFAULT_TENANT;" in js
    # headers() must use the frozen tenant and never read the editable field.
    hdr = _js_function(js, "headers")
    assert "activeTenant" in hdr
    assert "kd-tenant" not in hdr and "fieldTenant" not in hdr and ".value" not in hdr
    assert "function tenant()" not in js
    # Only the reload path adopts the field value, and it closes open confirms.
    assert js.count("activeTenant = fieldTenant()") == 1
    apply = _js_function(js, "applyTenant")
    assert "activeTenant = fieldTenant()" in apply
    assert "confirmResets.forEach" in apply
    assert "applyTenant();" in _js_function(js, "reloadOverview")
    assert "$('kd-refresh').addEventListener('click', reloadOverview)" in js
    # Typing in the field only toggles the hint.
    assert "$('kd-tenant').addEventListener('input', syncTenantHint)" in js
    assert "fieldTenant() === activeTenant" in _js_function(js, "syncTenantHint")
    html = (PAGES / "kd.html").read_text(encoding="utf-8")
    assert re.search(r'id="kd-tenant-hint"[^>]*hidden>按重新載入後才會切換租戶<', html)
    assert 'id="kd-tenant-active"' in html


def test_kd_js_confirms_show_and_pin_tenant() -> None:
    js = _js()
    assert "'租戶：' + tenantId" in _js_function(js, "previewText")
    # Each confirm form registers a reset and previews the tenant it will send to.
    assert js.count("confirmResets.push(reset)") == 2
    assert js.count("previewText(pending.tenant") == 2
    # Every POST is sent with the tenant captured when its confirm was opened.
    posts = re.findall(r"api\('POST'[^)]*\)", js)
    assert len(posts) == 2 and all("req.tenant" in p for p in posts)


def test_kd_js_post_guards_and_no_innerhtml() -> None:
    js = _js()
    assert "innerHTML" not in js
    for fn in ("wireConfirmForm", "wireStructureForm"):
        start = js.index(f"function {fn}(")
        body = js[start : js.index("\n  function ", start + 1)]
        assert "if (!pending) return;" in body
        assert "go.disabled = true;" in body
        assert ".catch(function (e)" in body
        assert "go.disabled = false;" in body


def test_kd_js_readiness_fields_match_api(client: TestClient) -> None:
    body = client.get("/api/kd/readiness", headers=HDR).json()
    assert isinstance(body["productionReady"], bool)
    assert isinstance(body["productionReadyScope"], str) and body["productionReadyScope"]
    assert body["commercialCostModelScope"] == "CONFIG_ESTIMATE_ONLY"
    assert isinstance(body["fullAutonomousFactoryReady"], bool)
    js = _js()
    line = _js_function(js, "readinessScopeLine")
    for key in ("productionReady", "productionReadyScope", "fullAutonomousFactoryReady", "commercialCostModelScope"):
        assert f"matrix.{key}" in line
    # Missing fields are reported as such, not silently shown as 否.
    assert "未回傳" in line


def test_kd_catalog_costs_labelled_as_estimates() -> None:
    js = _js()
    assert "var ESTIMATE_SCOPE = 'CONFIG_ESTIMATE_ONLY';" in js
    assert "estimateCell(row.landedCost)" in js
    assert "estimateCell(row.suggestedPrice)" in js
    assert "'估算'" in _js_function(js, "estimateCell")
    assert "String(row.landedCost)" not in js and "String(row.suggestedPrice)" not in js
    html = (PAGES / "kd.html").read_text(encoding="utf-8")
    assert "<th>到岸成本（估算）</th><th>建議售價（估算）</th>" in html
