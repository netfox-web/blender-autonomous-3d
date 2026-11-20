"""Prototype validation HTTP API and admin page contracts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform
from fox3d.portfolio import run_portfolio_scenario
from tests.test_prototype import GOOD_QC, _dam_ref, _ops, _pack_obs, _seed_lot, _vals


def _portfolio_setup(plat: Platform, tenant_a: str = "pa", tenant_b: str = "pb") -> dict:
    portfolio = run_portfolio_scenario(plat, tenant_a=tenant_a, tenant_b=tenant_b)
    ranking = plat.portfolio.rank(portfolio["portfolioId"], tenant_id=tenant_a)
    candidate_id = ranking["top10"][0]["candidateId"]
    pf = plat.prototype
    fixture, shift, _human, _human_shift = _ops(plat, tenant=tenant_a)
    selected = pf.select(
        tenant_id=tenant_a,
        candidate_id=candidate_id,
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        reason="api-test",
    )
    return {
        "portfolio": portfolio,
        "fixture": fixture,
        "shift": shift,
        "selection": selected,
    }


def test_read_paths_and_fixture_source_label(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    ctx = _portfolio_setup(plat)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "pa"}
    pid = ctx["portfolio"]["portfolioId"]
    cid = ctx["selection"]["candidateId"]

    board = client.get("/api/prototypes/board", params={"portfolioId": pid}, headers=headers)
    assert board.status_code == 200
    assert board.json()["portfolioId"] == pid
    assert board.json()["liveMachineControl"] is False
    for row in board.json()["rows"]:
        assert row.get("evidenceSourceLabel") != "REAL"

    readiness = client.get(f"/api/prototypes/candidates/{cid}/readiness", headers=headers)
    assert readiness.status_code == 200
    assert readiness.json()["candidateId"] == cid
    assert "launchDecisionRecord" in readiness.json()

    create = client.post(
        "/api/prototypes/units",
        headers=headers,
        json={
            "selectionId": ctx["selection"]["selectionId"],
            "operatorId": ctx["fixture"]["operatorId"],
            "shiftId": ctx["shift"]["shiftId"],
            "idempotencyKey": "create-1",
        },
    )
    assert create.status_code == 200
    unit_id = create.json()["prototypeUnitId"]

    listing = client.get("/api/prototypes/units", headers=headers)
    assert listing.status_code == 200 and listing.json()["total"] >= 1
    assert "matrixRow" in listing.json()["items"][0]

    detail = client.get(f"/api/prototypes/units/{unit_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["matrixRow"]["prototypeUnitId"] == unit_id
    assert detail.json()["evidenceSourceLabel"] in {None, "FIXTURE", "REAL_LOGIC", "MANUAL_EVIDENCE", "IMPORTED_EVIDENCE"}


def test_cross_tenant_isolation(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    ctx = _portfolio_setup(plat)
    client = TestClient(create_app(plat))
    headers_a = {"X-Tenant-Id": "pa"}
    headers_b = {"X-Tenant-Id": "pb"}
    pid = ctx["portfolio"]["portfolioId"]
    cid = ctx["selection"]["candidateId"]

    created = client.post(
        "/api/prototypes/units",
        headers=headers_a,
        json={
            "selectionId": ctx["selection"]["selectionId"],
            "operatorId": ctx["fixture"]["operatorId"],
            "shiftId": ctx["shift"]["shiftId"],
            "idempotencyKey": "iso-create",
        },
    ).json()
    unit_id = created["prototypeUnitId"]

    assert client.get(f"/api/prototypes/units/{unit_id}", headers=headers_b).status_code == 404
    assert client.get(f"/api/prototypes/candidates/{cid}/readiness", headers=headers_b).status_code == 404
    assert client.get("/api/prototypes/units", headers=headers_b).json()["total"] == 0

    board_b = client.get("/api/prototypes/board", params={"portfolioId": pid}, headers=headers_b)
    assert board_b.status_code == 404


def test_missing_shift_rejected(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    ctx = _portfolio_setup(plat)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "pa"}
    unit = client.post(
        "/api/prototypes/units",
        headers=headers,
        json={
            "selectionId": ctx["selection"]["selectionId"],
            "operatorId": ctx["fixture"]["operatorId"],
            "shiftId": ctx["shift"]["shiftId"],
            "idempotencyKey": "shift-test",
        },
    ).json()

    bad = client.post(
        f"/api/prototypes/units/{unit['prototypeUnitId']}/start",
        headers=headers,
        json={"operatorId": ctx["fixture"]["operatorId"], "shiftId": "no-such-shift", "idempotencyKey": "x1"},
    )
    assert bad.status_code == 403
    assert "KeyError" not in bad.text


def test_material_consume_idempotent_no_double_deduct(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    ctx = _portfolio_setup(plat)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "pa"}
    unit = client.post(
        "/api/prototypes/units",
        headers=headers,
        json={
            "selectionId": ctx["selection"]["selectionId"],
            "operatorId": ctx["fixture"]["operatorId"],
            "shiftId": ctx["shift"]["shiftId"],
            "idempotencyKey": "mat-unit",
        },
    ).json()
    uid = unit["prototypeUnitId"]
    client.post(
        f"/api/prototypes/units/{uid}/start",
        headers=headers,
        json={
            "operatorId": ctx["fixture"]["operatorId"],
            "shiftId": ctx["shift"]["shiftId"],
            "idempotencyKey": "mat-start",
        },
    )
    lot = _seed_lot(plat, "pa", plat.prototype.units[uid], sheets=4)
    body = {
        "operatorId": ctx["fixture"]["operatorId"],
        "shiftId": ctx["shift"]["shiftId"],
        "consumesInventory": True,
        "sheets": 2,
        "lotId": lot["lotId"],
        "idempotencyKey": "mat-consume-1",
    }
    first = client.post(f"/api/prototypes/units/{uid}/material", headers=headers, json=body)
    assert first.status_code == 200 and first.json().get("materialConsumed") is True
    qty_after = plat.lots.quantities(lot["lotId"], tenant_id="pa")["available"]

    retry = client.post(f"/api/prototypes/units/{uid}/material", headers=headers, json=body)
    assert retry.status_code == 200
    assert plat.lots.quantities(lot["lotId"], tenant_id="pa")["available"] == qty_after

    conflict = client.post(
        f"/api/prototypes/units/{uid}/material",
        headers=headers,
        json={**body, "sheets": 3, "idempotencyKey": "mat-consume-1"},
    )
    assert conflict.status_code == 409


def test_as_built_fixture_source_not_real(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    ctx = _portfolio_setup(plat)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "pa"}
    cand = plat.portfolio.candidates[ctx["selection"]["candidateId"]]
    unit = client.post(
        "/api/prototypes/units",
        headers=headers,
        json={
            "selectionId": ctx["selection"]["selectionId"],
            "operatorId": ctx["fixture"]["operatorId"],
            "shiftId": ctx["shift"]["shiftId"],
            "idempotencyKey": "asb-unit",
        },
    ).json()
    uid = unit["prototypeUnitId"]
    for key, idem in (("start", "asb-start"), ("complete", "asb-complete")):
        client.post(
            f"/api/prototypes/units/{uid}/{key}",
            headers=headers,
            json={
                "operatorId": ctx["fixture"]["operatorId"],
                "shiftId": ctx["shift"]["shiftId"],
                "idempotencyKey": idem,
            },
        )
    dam = [_dam_ref(plat, "pa", "asbuilt.bin", "AS_BUILT")]
    res = client.post(
        f"/api/prototypes/units/{uid}/as-built",
        headers=headers,
        json={
            "operatorId": ctx["fixture"]["operatorId"],
            "shiftId": ctx["shift"]["shiftId"],
            "source": "FIXTURE",
            "values": _vals(cand),
            "damRefs": dam,
            "observations": GOOD_QC,
            "idempotencyKey": "asb-1",
        },
    )
    assert res.status_code == 200
    assert res.json()["evidenceSourceLabel"] == "FIXTURE"
    assert res.json()["truthLabel"] == "FIXTURE"


def test_evidence_package_finalize_idempotent(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    ctx = _portfolio_setup(plat)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "pa"}
    cand = plat.portfolio.candidates[ctx["selection"]["candidateId"]]
    uid = client.post(
        "/api/prototypes/units",
        headers=headers,
        json={
            "selectionId": ctx["selection"]["selectionId"],
            "operatorId": ctx["fixture"]["operatorId"],
            "shiftId": ctx["shift"]["shiftId"],
            "idempotencyKey": "pkg-unit",
        },
    ).json()["prototypeUnitId"]
    ops = {
        "operatorId": ctx["fixture"]["operatorId"],
        "shiftId": ctx["shift"]["shiftId"],
    }
    client.post(f"/api/prototypes/units/{uid}/start", headers=headers, json={**ops, "idempotencyKey": "p1"})
    client.post(f"/api/prototypes/units/{uid}/complete", headers=headers, json={**ops, "idempotencyKey": "p2"})
    client.post(
        f"/api/prototypes/units/{uid}/as-built",
        headers=headers,
        json={
            **ops,
            "source": "FIXTURE",
            "values": _vals(cand),
            "damRefs": [_dam_ref(plat, "pa", "as.bin", "AS_BUILT")],
            "observations": GOOD_QC,
            "idempotencyKey": "p3",
        },
    )
    plat.prototype.record_actual_cost(
        uid,
        tenant_id="pa",
        operator_id=ops["operatorId"],
        shift_id=ops["shiftId"],
        source="FIXTURE",
        components={"sheetsConsumed": 1, "materialAmount": 1, "hardwareAmount": 1, "laborAmount": 1, "packagingAmount": 1},
    )
    plat.prototype.packaging_checklist(
        uid,
        tenant_id="pa",
        operator_id=ops["operatorId"],
        shift_id=ops["shiftId"],
        source="FIXTURE",
        observed=_pack_obs(plat, cand),
        dam_refs=[_dam_ref(plat, "pa", "pack.bin", "PACKAGING")],
    )
    pkg = client.post(
        f"/api/prototypes/units/{uid}/evidence-packages",
        headers=headers,
        json={**ops, "source": "FIXTURE", "idempotencyKey": "pkg-create"},
    ).json()
    pkg_id = pkg["evidencePackageId"]
    body = {**ops, "idempotencyKey": "pkg-fin"}
    fin1 = client.post(f"/api/prototypes/units/{uid}/evidence-packages/{pkg_id}/finalize", headers=headers, json=body)
    fin2 = client.post(f"/api/prototypes/units/{uid}/evidence-packages/{pkg_id}/finalize", headers=headers, json=body)
    assert fin1.status_code == 200 and fin2.status_code == 200
    assert fin1.json()["state"] == "FINALIZED"


@pytest.mark.parametrize("header", (None, "", "  "))
def test_header_validation(platform, header):  # noqa: ANN001
    headers = {} if header is None else {"X-Tenant-Id": header}
    client = TestClient(create_app(platform))
    assert client.get("/api/prototypes/units", headers=headers).status_code == 400