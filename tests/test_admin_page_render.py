"""Admin page /admin/render — shell, assets, and APIs used by the page."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app

TENANT = "sonaqueen-home"
H = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def test_render_page_loads_shell(client: TestClient) -> None:
    res = client.get("/admin/render")
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in res.text
    assert "/admin/pages/assets/render.js" in res.text
    assert "/admin/pages/assets/render.css" in res.text
    assert 'id="twins"' in res.text


def test_render_page_assets(client: TestClient) -> None:
    for name in ("render.js", "render.css"):
        res = client.get(f"/admin/pages/assets/{name}")
        assert res.status_code == 200 and res.content


def test_render_page_twins_list_api(client: TestClient) -> None:
    created = client.post(
        "/api/digital-twins",
        json={"sku": "RD-1", "dimensions": {"width": 400, "height": 800, "depth": 300}},
        headers=H,
    )
    assert created.status_code == 200
    twin_id = created.json()["twinId"]

    listed = client.get("/api/pages/render/twins", headers=H)
    assert listed.status_code == 200
    ids = {t["twinId"] for t in listed.json()["items"]}
    assert twin_id in ids


def test_render_page_job_flow(client: TestClient) -> None:
    job = client.post(
        "/api/3d/jobs",
        json={"jobType": "BLENDER_PREVIEW", "scene": "WHITE_STUDIO"},
        headers=H,
    )
    assert job.status_code == 200
    job_id = job.json()["jobId"]

    jobs = client.get("/api/3d/jobs", headers=H)
    assert jobs.status_code == 200
    assert any(j["jobId"] == job_id for j in jobs.json()["items"])

    detail = client.get(f"/api/3d/jobs/{job_id}", headers=H)
    assert detail.status_code == 200

    preview = client.post("/api/render/preview", json={"scene": "WHITE_STUDIO"}, headers=H)
    assert preview.status_code == 200

    cancel = client.post(f"/api/3d/jobs/{job_id}/cancel", headers=H)
    assert cancel.status_code == 200


def test_render_page_twin_actions(client: TestClient) -> None:
    twin = client.post(
        "/api/digital-twins",
        json={"sku": "RD-2", "dimensions": {"width": 200, "height": 200, "depth": 200}},
        headers=H,
    )
    twin_id = twin.json()["twinId"]

    got = client.get(f"/api/digital-twins/{twin_id}", headers=H)
    assert got.status_code == 200

    prev = client.post(f"/api/digital-twins/{twin_id}/preview", headers=H)
    assert prev.status_code == 200

    glb = b"glTF\x02\x00\x00\x00" + b"\x00" * 32
    up = client.post(
        "/api/digital-twins/upload",
        data={"sku": "RD-UP"},
        files={"file": ("x.glb", io.BytesIO(glb), "model/gltf-binary")},
        headers=H,
    )
    assert up.status_code == 200


def test_plugin_claims_jobs_and_twins_features() -> None:
    from fox3d.admin_pages import render as render_page
    from fox3d.features import resolved_features

    assert render_page.FEATURES == {"jobs": "/admin/render", "twins": "/admin/render#twins"}
    jobs = next(f for f in resolved_features() if f["id"] == "jobs")
    twins = next(f for f in resolved_features() if f["id"] == "twins")
    assert jobs["kind"] == "page" and jobs["href"] == "/admin/render"
    assert twins["kind"] == "page" and twins["href"] == "/admin/render#twins"
    assert "/api/pages/render" in jobs["prefixes"]


def test_render_page_twins_list_requires_tenant_header(client: TestClient) -> None:
    assert client.get("/api/pages/render/twins").status_code == 400
    assert client.get("/api/pages/render/twins", headers={"X-Tenant-Id": "  "}).status_code == 400


def test_render_page_twins_list_is_tenant_scoped(client: TestClient) -> None:
    created = client.post(
        "/api/digital-twins",
        json={"sku": "RD-SCOPE", "dimensions": {"width": 100, "height": 100, "depth": 100}},
        headers=H,
    )
    twin_id = created.json()["twinId"]
    other = client.get("/api/pages/render/twins", headers={"X-Tenant-Id": "other-tenant"})
    assert other.status_code == 200
    assert twin_id not in {t["twinId"] for t in other.json()["items"]}


def _render_js() -> str:
    from pathlib import Path

    js_path = Path(__file__).resolve().parents[1] / "src" / "fox3d" / "static" / "pages" / "render.js"
    return js_path.read_text(encoding="utf-8")


def test_render_js_handles_blocked_results() -> None:
    js = _render_js()
    assert "function isBlockedResult" in js
    assert "status === 'blocked'" in js
    assert "BLOCKED_" in js
    assert "已封鎖：沒有真實 Blender／OptiX，未產生成品" in js
    # Every e2e action checks the gate before claiming success.
    for call in (
        "blockedMessage('上傳', out)",
        "blockedMessage('預覽', out)",
        "blockedMessage('360 環繞', out)",
        "blockedMessage(label, out)",
    ):
        assert call in js
    assert js.count("isBlockedResult(out)") >= 5
    # Job status "blocked" is labelled BLOCKED; MOCK is reserved for discoverySource.
    badge = js[js.index("function statusBadge") : js.index("const confirms")]
    assert "st === 'blocked'" in badge and ">BLOCKED<" in badge
    assert "src === 'MOCK'" in badge
    mock_branch = badge[badge.index("src === 'MOCK'") :]
    assert "st-mock" in mock_branch and "st === 'blocked'" not in mock_branch


def test_render_js_never_sends_tenant_in_body() -> None:
    js = _render_js()
    assert "tenantId:" not in js
    assert "tenantId()" not in js
    assert "'X-Tenant-Id': tenant || activeTenant" in js
    assert "let activeTenant" in js
    assert "按重新載入後才會切換租戶" in js


def test_render_js_fetches_preview_asset_with_tenant_header() -> None:
    js = _render_js()
    assert "URL.createObjectURL" in js and "URL.revokeObjectURL" in js
    loader = js[js.index("async function loadPreviewImage") :]
    loader = loader[: loader.index("async function loadJobs")]
    assert "/api/assets/" in loader and "'X-Tenant-Id': tenant" in loader
    assert "res.blob()" in loader
    assert ".src = `/api/assets/" not in js


def test_render_js_confirm_dialog_single_slot() -> None:
    js = _render_js()
    assert "let pendingConfirm" in js
    assert "'Escape'" in js
    assert "tenant: activeTenant" in js  # captured when the dialog opens
    assert "p.onYes(p.tenant)" in js
    opener = js[js.index("function openConfirm") : js.index("function wireConfirmDialogs")]
    assert "addEventListener" not in opener
    assert ".focus()" in opener


def test_render_page_has_tenant_hint(client: TestClient) -> None:
    res = client.get("/admin/render")
    assert 'id="rd-tenant-hint"' in res.text
