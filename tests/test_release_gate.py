"""ReleaseGate tenant isolation, sequential states, API error mapping."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.release import ReleaseGate


def _entity(product_id: str = "ent-1") -> dict:
    return {
        "spec": {"productId": product_id, "revision": 1},
        "engineeringHash": "eng-a",
        "lineage": {"engineeringHash": "eng-a", "bomHash": "bom-a"},
        "bom": {"bomHash": "bom-a"},
    }


def test_cross_tenant_same_entity_id_isolated():
    gate = ReleaseGate()
    ent = _entity("shared-id")
    gate.advance("shared-id", tenant_id="tenant-a", target="ENGINEERING_VALID", actor="ops", entity=ent)
    gate.advance(
        "shared-id",
        tenant_id="tenant-a",
        target="EVIDENCE_VERIFIED",
        actor="ops",
        entity=ent,
        evidence_ok=True,
    )
    gate.advance("shared-id", tenant_id="tenant-a", target="WAITING_APPROVAL", actor="ops", entity=ent)
    a_state = gate.approvals[("tenant-a", "shared-id")]["state"]

    b_ent = dict(ent)
    b_state = (gate.approvals.get(("tenant-b", "shared-id")) or {}).get("state", "PROTOTYPE")
    assert b_state == "PROTOTYPE"

    gate.advance("shared-id", tenant_id="tenant-b", target="ENGINEERING_VALID", actor="ops", entity=b_ent)
    assert gate.approvals[("tenant-b", "shared-id")]["state"] == "ENGINEERING_VALID"
    assert gate.approvals[("tenant-a", "shared-id")]["state"] == a_state


def test_skip_state_rejected():
    gate = ReleaseGate()
    ent = _entity()
    with pytest.raises(ValueError, match="cannot skip"):
        gate.advance("ent-1", tenant_id="t1", target="WAITING_APPROVAL", actor="ops", entity=ent)
    with pytest.raises(ValueError, match="cannot skip"):
        gate.advance("ent-1", tenant_id="t1", target="APPROVED_FOR_EXPORT", actor="ops", entity=ent)
    gate.advance("ent-1", tenant_id="t1", target="ENGINEERING_VALID", actor="ops", entity=ent)
    with pytest.raises(ValueError, match="cannot skip"):
        gate.advance("ent-1", tenant_id="t1", target="WAITING_APPROVAL", actor="ops", entity=ent)


def test_regress_and_invalid_target_are_value_error():
    gate = ReleaseGate()
    ent = _entity()
    gate.advance("ent-1", tenant_id="t1", target="ENGINEERING_VALID", actor="ops", entity=ent)
    with pytest.raises(ValueError, match="cannot regress"):
        gate.advance("ent-1", tenant_id="t1", target="PROTOTYPE", actor="ops", entity=ent)
    with pytest.raises(ValueError):
        gate.advance("ent-1", tenant_id="t1", target="NOT_A_STATE", actor="ops", entity=ent)


def test_live_cnc_laser_forbidden():
    gate = ReleaseGate()
    ent = _entity()
    with pytest.raises(PermissionError):
        gate.advance("x", tenant_id="t1", target="LIVE_CNC", actor="ops", entity=ent)
    with pytest.raises(PermissionError):
        gate.advance("x", tenant_id="t1", target="LIVE_LASER", actor="ops", entity=ent)


def test_refresh_stale_resets_to_prototype():
    gate = ReleaseGate()
    ent = _entity()
    eid = "ent-1"
    tid = "t1"
    gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="ops", entity=ent)
    gate.advance(eid, tenant_id=tid, target="EVIDENCE_VERIFIED", actor="ops", entity=ent, evidence_ok=True)
    mutated = dict(ent)
    mutated["engineeringHash"] = "eng-changed"
    mutated["lineage"] = {**(ent.get("lineage") or {}), "engineeringHash": "eng-changed"}
    stale = gate.refresh_stale(eid, tenant_id=tid, entity=mutated)
    assert stale["stale"] is True
    assert stale["state"] == "PROTOTYPE"
    assert gate.events[-1]["tenantId"] == tid
    assert gate.events[-1]["decision"] == "STALE"


def test_audit_records_tenant_id_on_advance():
    gate = ReleaseGate()
    ent = _entity()
    rec = gate.advance("ent-1", tenant_id="acme", target="ENGINEERING_VALID", actor="ops", entity=ent)
    assert rec["tenantId"] == "acme"
    assert rec["audit"]["tenantId"] == "acme"


def test_api_release_advance_403_and_422(platform):
    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "acme"}
    live = client.post(
        "/api/release/advance",
        json={"entityId": "x", "target": "LIVE_LASER", "entity": {}},
        headers=headers,
    )
    assert live.status_code == 403

    live_cnc = client.post(
        "/api/release/advance",
        json={"entityId": "x", "target": "LIVE_CNC", "entity": {}},
        headers=headers,
    )
    assert live_cnc.status_code == 403

    skip = client.post(
        "/api/release/advance",
        json={"entityId": "y", "target": "APPROVED_FOR_EXPORT", "entity": _entity("y")},
        headers=headers,
    )
    assert skip.status_code == 422

    bad = client.post(
        "/api/release/advance",
        json={"entityId": "z", "target": "NOPE", "entity": {}},
        headers=headers,
    )
    assert bad.status_code == 422