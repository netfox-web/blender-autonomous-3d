"""Admin plug-in page: /admin/prototypes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.admin_pages import page_features
from fox3d.api import create_app

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001
    return TestClient(create_app(platform))


def test_prototypes_plugin_claims_feature() -> None:
    assert page_features().get("prototypes") == "/admin/prototypes"


def test_prototypes_page_serves_html_and_shell(client: TestClient) -> None:
    res = client.get("/admin/prototypes")
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/pages/assets/prototypes.js" in res.text
    assert "/admin/pages/assets/prototypes.css" in res.text


@pytest.mark.parametrize("asset", ["prototypes.js", "prototypes.css"])
def test_prototypes_assets(client: TestClient, asset: str) -> None:
    res = client.get(f"/admin/pages/assets/{asset}")
    assert res.status_code == 200
    assert res.content


def test_prototypes_js_safety_guards() -> None:
    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/prototypes.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js
    assert "textContent" in js
    assert "dlg.returnValue = ''" in js
    assert ".finally(" in js
    assert "proto-confirm" in js
    assert "disabled = true" in js or "disabled = on" in js