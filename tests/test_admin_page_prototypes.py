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


def test_prototypes_confirm_listens_on_dialog_not_form() -> None:
    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/prototypes.js").read_text(encoding="utf-8")
    opener = js[js.index("function openConfirm") : js.index("function postAction")]
    assert "dlg.addEventListener('close'" in opener
    assert "form.addEventListener('close'" not in opener
    assert opener.index("dlg.returnValue = ''") < opener.index("dlg.showModal();")
    assert "onOkClick" in opener and "ev.preventDefault()" in opener


def test_prototypes_labor_inputs_wired() -> None:
    root = Path(__file__).resolve().parents[1] / "src/fox3d/static/pages"
    html = (root / "prototypes.html").read_text(encoding="utf-8")
    js = (root / "prototypes.js").read_text(encoding="utf-8")
    for field in ("proto-labor-minutes", "proto-labor-reason", "proto-labor-source"):
        assert field in html
    assert "proto-labor-minutes" in js and "proto-labor-reason" in js
    assert "body.minutes = mins" in js
    assert "body.minutes = 5" not in js
    assert "ui-labor" not in js