"""Shared admin shell and feature directory: every page reachable, every route catalogued."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.features import FEATURES, GROUPS, feature_index
from fox3d.product_dna import FAMILY_ID

STATIC = Path(__file__).resolve().parents[1] / "src" / "fox3d" / "static"
PAGES = [f for f in FEATURES if f["kind"] == "page"]


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def test_every_route_belongs_to_a_feature(client: TestClient) -> None:
    index = client.get("/api/admin/features").json()
    assert index["unclaimed"] == [], "new route has no entry in fox3d/features.py"
    api_only = [f for f in index["features"] if f["kind"] == "api"]
    assert api_only and all(f["routes"] for f in api_only)


def test_registry_is_consistent() -> None:
    ids = [f["id"] for f in FEATURES]
    assert len(ids) == len(set(ids))
    groups = {g["id"] for g in GROUPS}
    for f in FEATURES:
        assert f["group"] in groups and f["kind"] in {"page", "api", "blocked"}
        assert f["title"] and f["summary"]
        assert bool(f.get("href")) == (f["kind"] == "page")
        if f["kind"] == "blocked":
            assert f.get("waitingFor")
        else:
            assert f.get("prefixes")


@pytest.mark.parametrize("feature", PAGES, ids=[f["id"] for f in PAGES])
def test_every_page_loads_the_shared_shell(client: TestClient, feature: dict) -> None:
    res = client.get(feature["href"])
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in res.text
    # the old per-page navs are gone, the sidebar is the only navigation
    assert 'aria-label="工作台導覽"' not in res.text
    assert 'class="workbench-nav"' not in res.text


@pytest.mark.parametrize("name", ["fox3d-shell.js", "fox3d-shell.css", "features.js", "features.css"])
def test_shell_assets_are_served(client: TestClient, name: str) -> None:
    res = client.get(f"/admin/recipes/assets/{name}")
    assert res.status_code == 200 and res.content


def test_feature_index_longest_prefix_wins() -> None:
    class R:
        def __init__(self, path: str) -> None:
            self.path, self.methods = path, {"GET"}

    index = feature_index([R("/api/recipe-library/golden/x"), R("/api/recipe-library/products"), R("/admin"), R("/nowhere")])
    owner = {r["path"]: f["id"] for f in index["features"] for r in f["routes"]}
    assert owner["/api/recipe-library/golden/x"] == "golden"
    assert owner["/api/recipe-library/products"] == "recipes"
    assert owner["/admin"] == "control"
    assert index["unclaimed"] == [{"path": "/nowhere", "methods": "GET"}]


def test_golden_page_asks_for_the_real_dna_family() -> None:
    # The DNA panel always failed: the page sent a family id the API 404s on.
    assert f"familyId='{FAMILY_ID}'" in (STATIC / "golden-product.js").read_text(encoding="utf-8")


def test_print_page_has_no_missing_script() -> None:
    assert "three.min.js" not in (STATIC / "print-workspace.html").read_text(encoding="utf-8")


def test_plugin_page_assets_are_confined(client: TestClient) -> None:
    for bad in ["../features.py", "x.html", "..%2Ffox3d-shell.js", "missing.js"]:
        assert client.get(f"/admin/pages/assets/{bad}").status_code == 404


def test_plugin_page_claims_turn_api_groups_into_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    import fox3d.admin_pages as pages
    from fox3d.features import resolved_features

    monkeypatch.setattr(pages, "page_features", lambda: {"factory": "/admin/factory"})
    factory = next(f for f in resolved_features() if f["id"] == "factory")
    assert factory["kind"] == "page" and factory["href"] == "/admin/factory"
    assert "/admin/factory" in factory["prefixes"]
    monkeypatch.setattr(pages, "page_features", lambda: {"no-such-feature": "/admin/x"})
    with pytest.raises(ValueError):
        resolved_features()
