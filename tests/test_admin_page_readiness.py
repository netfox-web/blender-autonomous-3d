"""Admin /admin/readiness page and the APIs it calls."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.admin_pages import readiness as readiness_mod
from fox3d.api import create_app

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}
PAGE = "/admin/readiness"


@pytest.fixture()
def client(platform):  # noqa: ANN001
    return TestClient(create_app(platform))


def test_readiness_page_loads_shell(client: TestClient) -> None:
    res = client.get(PAGE)
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in res.text
    assert "/admin/pages/assets/readiness.js" in res.text
    assert "/admin/pages/assets/readiness.css" in res.text
    assert 'aria-label="工作台導覽"' not in res.text
    assert 'class="workbench-nav"' not in res.text


@pytest.mark.parametrize("name", ["readiness.js", "readiness.css"])
def test_readiness_assets(client: TestClient, name: str) -> None:
    res = client.get(f"/admin/pages/assets/{name}")
    assert res.status_code == 200
    assert res.content


def test_plugin_claims_readiness_features(client: TestClient) -> None:
    assert readiness_mod.FEATURES == {
        "readiness": PAGE,
        "physical-os": f"{PAGE}#physical-os",
        "commerce": f"{PAGE}#commerce",
    }
    index = client.get("/api/admin/features").json()
    for fid in ("readiness", "physical-os", "commerce"):
        feat = next(f for f in index["features"] if f["id"] == fid)
        assert feat["kind"] == "page"
        assert feat["href"] == readiness_mod.FEATURES[fid]


def test_readiness_page_api_calls(client: TestClient) -> None:
    assert client.get("/api/readiness", headers=HEADERS).status_code == 200
    assert client.get("/api/kpi", headers=HEADERS).status_code == 200
    assert client.get("/api/physical-os/families", headers=HEADERS).status_code == 200
    assert client.get("/api/physical-os/readiness", headers=HEADERS).status_code == 200
    ev = client.post(
        "/api/evidence/verify",
        json={"bundle": {"engineeringHash": "e", "bomHash": "b"}},
        headers=HEADERS,
    )
    assert ev.status_code == 200
    rel = client.post(
        "/api/release/advance",
        json={
            "entityId": "admin-readiness-test",
            "target": "ENGINEERING_VALID",
            "entity": {"skuId": "t1", "engineeringHash": "h1"},
        },
        headers=HEADERS,
    )
    assert rel.status_code == 200
    safety = client.post(
        "/api/safety/evaluate",
        json={
            "kind": "KD",
            "record": {"spec": {"width": 600, "depth": 400, "height": 1800, "boardThickness": 18}},
        },
        headers=HEADERS,
    )
    assert safety.status_code == 200
    imp = client.post(
        "/api/commerce/import",
        json={"kind": "logistics", "source": "MANUAL", "rows": [{"zone": "TW", "baseFee": 80, "perKg": 12}]},
        headers=HEADERS,
    )
    assert imp.status_code == 200
    assert imp.json()["liveProviderReady"] is False
    acr = client.post("/api/acrylic/products", json={"kind": "SIGN_HOLDER"}, headers=HEADERS)
    assert acr.status_code == 200
    app = client.post(
        "/api/physical-os/approve",
        json={"entityId": acr.json()["productId"], "actor": "pytest"},
        headers=HEADERS,
    )
    assert app.status_code == 200


def test_readiness_confirm_boxes_start_hidden_and_lock_inputs() -> None:
    import re
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "src/fox3d/static/pages"
    html = (base / "readiness.html").read_text(encoding="utf-8")
    boxes = re.findall(r'<[^>]*id="rd-[a-z-]+-confirm"[^>]*>', html)
    assert boxes and all(" hidden" in b for b in boxes)
    js = (base / "readiness.js").read_text(encoding="utf-8")
    assert "data-rd-lock" in js and "function lockIds" in js
    for snap in ("rd-evidence-snap", "rd-rel-snap", "rd-safe-snap", "rd-phys-snap", "rd-com-snap"):
        assert f'id="{snap}"' in html


def test_evidence_verify_empty_bundle_is_not_ok_and_real_file_is(client: TestClient, tmp_path: Path) -> None:
    """The page posts {bundle: ...}. HTTP stays 200; ok and errors carry the verdict."""
    empty = client.post("/api/evidence/verify", json={"bundle": {}}, headers=HEADERS)
    assert empty.status_code == 200
    body = empty.json()
    assert body["ok"] is False
    assert body["errors"] == ["missing_artifact_path", "missing_lineage"]

    artifact = tmp_path / "evidence.bin"
    artifact.write_bytes(b"bundle-bytes")
    ok = client.post(
        "/api/evidence/verify",
        json={"bundle": {"artifactPath": str(artifact), "engineeringHash": "eng-1"}},
        headers=HEADERS,
    )
    assert ok.status_code == 200
    passed = ok.json()
    assert passed["ok"] is True
    assert passed["errors"] == []


def test_readiness_js_gates_evidence_ok_and_one_confirm() -> None:
    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/readiness.js").read_text(encoding="utf-8")
    assert "out.ok === false" in js
    show = js[js.index("function blockedMessage") : js.index("function bindPost")]
    assert "驗證失敗" in show
    assert show.index("驗證失敗") < show.index("已阻擋")
    bind = js[js.index("function bindPost") :]
    assert "if (postBusy || held || activeConfirm) return;" in bind
    assert "activeConfirm !== box" in bind


def test_readiness_locks_tenant_and_handles_post_network_errors() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/readiness.js").read_text(encoding="utf-8")
    assert "$('rd-tenant')" in js and "els.push(tenantEl)" in js
    assert "連線失敗" in js and "call.catch" in js
    assert "shot.tenant" in js and "shot.body" in js
    assert "postBusy" in js and "run.disabled = true" in js and "ok.disabled = true" in js
    assert ".finally(" in js and "run.disabled = false" in js and "ok.disabled = false" in js
    assert "function isBlockedResult" in js and "veto === true" in js and "truthLabel" in js
    assert "out.status < 200 || out.status >= 300" in js
    assert "操作失敗" in js and "已阻擋" in js
    # Success text is not the branch taken for a blocked body.
    show = js[js.index("function showOut") : js.index("function bindPost")]
    assert show.index("操作完成") > show.index("isBlockedResult")
