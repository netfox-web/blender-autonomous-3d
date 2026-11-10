"""Admin page /admin/pilot-floor: shell, assets, pilot-floor APIs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.workorder import STRICT_STOCK
from fox3d.operator import make_token

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def _ready_wo(platform, tenant: str = TENANT):
    product = platform.kd.build_sku(tenant_id=tenant, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    nest = (rel.get("snapshot") or {}).get("nesting") or {}
    row = {
        "supplierLot": f"{tenant}-lot",
        "material": nest.get("sheetSku") or "PB_18_WHITE",
        "thickness": nest.get("thickness") or 18,
        "quantity": 20,
    }
    sheet_mm = nest.get("sheetMm") or []
    if len(sheet_mm) >= 2:
        row["length"] = float(sheet_mm[0])
        row["width"] = float(sheet_mm[1])
    platform.pilot.receiving.import_receipt(row, tenant_id=tenant, actor="recv", source="MANUAL", idempotency_key=f"{tenant}-lot")
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    platform.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    platform.pilot.workorders.reserve_materials(wo["workOrderId"], actor="ops", tenant_id=tenant, allocation_policy=STRICT_STOCK)
    return wo


def test_pilot_floor_page_and_assets(client: TestClient) -> None:
    page = client.get("/admin/pilot-floor")
    assert page.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in page.text
    assert "/admin/recipes/assets/fox3d-shell.css" in page.text
    assert "/admin/pages/assets/pilot-floor.js" in page.text
    assert "/admin/pages/assets/pilot-floor.css" in page.text
    assert 'aria-label="工作台導覽"' not in page.text

    for name in ("pilot-floor.js", "pilot-floor.css"):
        res = client.get(f"/admin/pages/assets/{name}")
        assert res.status_code == 200 and res.content


def test_pilot_floor_feature_becomes_page(client: TestClient) -> None:
    index = client.get("/api/admin/features").json()
    pf = next(f for f in index["features"] if f["id"] == "pilot-floor")
    assert pf["kind"] == "page"
    assert pf["href"] == "/admin/pilot-floor"
    assert "/admin/pilot-floor" in pf["prefixes"]


def test_pilot_floor_apis(client: TestClient, platform) -> None:
    wo = _ready_wo(platform)
    op = wo["traveler"]["steps"][0]["operation"]

    operator = client.get("/api/pilot/operator", headers=HEADERS)
    assert operator.status_code == 200
    assert operator.json()["tenantId"] == TENANT

    exceptions = client.get("/api/pilot/exceptions", headers=HEADERS)
    assert exceptions.status_code == 200
    assert "items" in exceptions.json()

    station = client.post(
        "/api/pilot/stations",
        headers=HEADERS,
        json={"capabilities": ["PANEL_CUTTING_MANUAL"], "actor": "test", "status": "ONLINE"},
    )
    assert station.status_code == 200
    station_id = station.json()["stationId"]

    heartbeat = client.post(f"/api/pilot/stations/{station_id}/heartbeat", headers=HEADERS, json={"actor": "test"})
    assert heartbeat.status_code == 200

    dispatch = client.post(
        "/api/pilot/dispatch",
        headers=HEADERS,
        json={
            "workOrderId": wo["workOrderId"],
            "operation": op,
            "stationId": station_id,
            "actor": "test",
        },
    )
    assert dispatch.status_code == 200
    lease_id = dispatch.json()["leaseId"]

    for suffix in ("ack", "start"):
        step = client.post(f"/api/pilot/leases/{lease_id}/{suffix}", headers=HEADERS, json={"actor": "test"})
        assert step.status_code == 200

    token = client.get(f"/api/pilot/scan-token/WO/{wo['workOrderId']}", headers=HEADERS)
    assert token.status_code == 200
    scan_token = token.json()["token"]
    assert scan_token == make_token("WO", wo["workOrderId"])

    scan = client.post("/api/pilot/scan", headers=HEADERS, json={"token": scan_token})
    assert scan.status_code == 200
    assert scan.json()["objectId"] == wo["workOrderId"]


def test_pilot_floor_never_parses_api_values_as_html() -> None:
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/pilot-floor.js").read_text(encoding="utf-8")
    assert "td.innerHTML" not in js
    assert "'<code>' +" not in js
    # every remaining innerHTML assignment is either static text or escaped
    for line in re.findall(r"innerHTML = (.+)", js):
        assert "+" not in line or "esc(" in line, line


def _pilot_floor_asset(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages" / name).read_text(encoding="utf-8")


def _js_function(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    nxt = js.find("\n  function ", start + 1)
    return js[start: nxt if nxt != -1 else len(js)]


def test_pilot_floor_actions_handle_errors_and_disable_while_in_flight() -> None:
    js = _pilot_floor_asset("pilot-floor.js")
    run = _js_function(js, "runAction")
    # in-flight lock, re-enable afterwards, visible failure notice for HTTP and network errors
    assert "el.disabled = true" in run and "el.disabled = false" in run
    assert "網路錯誤" in run and "notify(" in run and "r.res.ok" in run
    # every action endpoint goes through runAction (no bare api(...).then(...) without a rejection path)
    for endpoint in ("/heartbeat", "/api/pilot/leases/", "/api/pilot/scan-token/"):
        idx = js.index(endpoint)
        run_at = js.rfind("runAction({", 0, idx)
        assert run_at > js.rfind("\n  function ", 0, idx), endpoint
        assert "request: function" in js[run_at:idx], endpoint
    wire = _js_function(js, "wireConfirmForm")
    assert "runAction({" in wire and "disable: [ctl.btn, ctl.box]" in wire
    for key, path in (("station", "/api/pilot/stations'"), ("dispatch", "/api/pilot/dispatch"), ("scan", "/api/pilot/scan'")):
        assert f"wireConfirmForm('{key}'" in js and path in js
    html = _pilot_floor_asset("pilot-floor.html")
    assert 'id="pf-action-status"' in html and 'role="status"' in html


def test_pilot_floor_confirm_snapshots_and_locks_the_form() -> None:
    js = _pilot_floor_asset("pilot-floor.js")
    confirm = _js_function(js, "makeConfirm")
    assert "ctl.snapshot = { tenant: activeTenant, payload: payload }" in confirm
    assert "lockInputs(true)" in confirm and "lockInputs(false)" in confirm
    assert "summary.textContent = " in confirm and "租戶" in confirm
    assert "checkValidity()" in confirm
    wire = _js_function(js, "wireConfirmForm")
    # submit sends the snapshot (payload + tenant), never re-reads the form
    assert "if (!ctl || !ctl.snapshot) return;" in wire
    assert "JSON.stringify(snap.payload)" in wire and "tenant: snap.tenant" in wire
    assert "new FormData" not in wire
    # row clicks never rewrite a confirmed dispatch form
    prefill = _js_function(js, "prefillDispatch")
    assert "isLocked()" in prefill and "return;" in prefill
    assert "namedItem('workOrderId')" not in _js_function(js, "renderWorkOrders").split("prefillDispatch")[0]
    assert "df.stationId.value" not in js
    # successful dispatch resets the form and unticks its confirm
    forms = _js_function(js, "wireForms")
    dispatch_ok = forms[forms.index("'/api/pilot/dispatch'"):]
    assert dispatch_ok.index("ctl.clear();") < dispatch_ok.index("df.reset();")
    html = _pilot_floor_asset("pilot-floor.html")
    assert html.count('class="pf-confirm-summary"') == 3


def test_pilot_floor_tenant_is_frozen_until_reload() -> None:
    js = _pilot_floor_asset("pilot-floor.js")
    assert "var activeTenant = " in js
    assert "return activeTenant;" in _js_function(js, "tenant")
    # header field edits only update the hint; reload switches tenant and clears pending confirms
    init = _js_function(js, "init")
    assert "activeTenant = fieldTenant();" in init
    assert "addEventListener('change', function () { saveTenant(); loadOperator()" not in js
    assert "$('pf-refresh').addEventListener('click', reloadAll)" in init
    reload = _js_function(js, "reloadAll")
    assert "activeTenant = fieldTenant();" in reload and "clearPendingConfirms();" in reload
    assert "按重新載入後才會切換租戶" in _js_function(js, "updateTenantHint")
    assert js.count("activeTenant = ") == 3  # declaration, init, reload only
    assert "opts.tenant || tenant()" in js
    html = _pilot_floor_asset("pilot-floor.html")
    assert 'id="pf-tenant-hint"' in html
