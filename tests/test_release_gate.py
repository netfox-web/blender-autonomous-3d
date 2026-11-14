"""ReleaseGate tenant isolation, sequential states, API error mapping."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

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


def _advance_chain(gate: ReleaseGate, eid: str, tid: str, ent: dict, *, to: str) -> None:
    steps = ("ENGINEERING_VALID", "EVIDENCE_VERIFIED", "WAITING_APPROVAL", "APPROVED_FOR_EXPORT")
    for step in steps:
        if step == to:
            break
        gate.advance(
            eid,
            tenant_id=tid,
            target=step,
            actor="ops",
            entity=ent,
            evidence_ok=step == "EVIDENCE_VERIFIED",
        )
    gate.advance(eid, tenant_id=tid, target=to, actor="ops", entity=ent, evidence_ok=True)


def test_advance_rejects_hash_change_after_evidence():
    gate = ReleaseGate()
    ent_a = _entity("ent-h")
    tid = "t1"
    eid = "ent-h"
    gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="ops", entity=ent_a)
    gate.advance(eid, tenant_id=tid, target="EVIDENCE_VERIFIED", actor="ops", entity=ent_a, evidence_ok=True)
    ent_b = dict(ent_a)
    ent_b["engineeringHash"] = "eng-b"
    ent_b["lineage"] = {**(ent_a.get("lineage") or {}), "engineeringHash": "eng-b"}
    with pytest.raises(PermissionError, match="hashes changed"):
        gate.advance(eid, tenant_id=tid, target="WAITING_APPROVAL", actor="ops", entity=ent_b)


def test_unverified_hash_cannot_reach_export_and_refresh_stale_stays_blocked():
    gate = ReleaseGate()
    ent_a = _entity("ent-h2")
    tid = "t1"
    eid = "ent-h2"
    gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="ops", entity=ent_a)
    gate.advance(eid, tenant_id=tid, target="EVIDENCE_VERIFIED", actor="ops", entity=ent_a, evidence_ok=True)
    ent_b = dict(ent_a)
    ent_b["engineeringHash"] = "eng-b"
    ent_b["lineage"] = {**(ent_a.get("lineage") or {}), "engineeringHash": "eng-b"}
    with pytest.raises(PermissionError):
        gate.advance(eid, tenant_id=tid, target="WAITING_APPROVAL", actor="ops", entity=ent_b)
    assert gate.approvals[(tid, eid)]["state"] == "EVIDENCE_VERIFIED"
    after = gate.refresh_stale(eid, tenant_id=tid, entity=ent_b)
    assert after["state"] != "APPROVED_FOR_EXPORT"


def test_advance_first_step_with_missing_hashes_allowed():
    gate = ReleaseGate()
    ent = {"spec": {"productId": "bare", "revision": 1}}
    gate.advance("bare", tenant_id="t1", target="ENGINEERING_VALID", actor="ops", entity=ent)
    assert gate.approvals[("t1", "bare")]["state"] == "ENGINEERING_VALID"


def test_empty_entity_cannot_verify_evidence_or_backfill_to_export():
    gate = ReleaseGate()
    ent = {"spec": {"productId": "bare2", "revision": 1}}
    eid = "bare2"
    tid = "t1"
    gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="ops", entity=ent)
    with pytest.raises(PermissionError, match="engineeringHash required"):
        gate.advance(eid, tenant_id=tid, target="EVIDENCE_VERIFIED", actor="ops", entity=ent, evidence_ok=True)
    ent_b = {**ent, "engineeringHash": "eng-b", "lineage": {"engineeringHash": "eng-b"}}
    with pytest.raises(PermissionError, match="cannot bind new hashes"):
        gate.advance(eid, tenant_id=tid, target="EVIDENCE_VERIFIED", actor="ops", entity=ent_b, evidence_ok=True)


def test_evidence_hash_change_rejected_after_verified():
    gate = ReleaseGate()
    ent = {
        **_entity("ent-ev"),
        "evidenceHash": "ev-a",
        "lineage": {"engineeringHash": "eng-a", "bomHash": "bom-a", "evidenceHash": "ev-a"},
    }
    eid = "ent-ev"
    tid = "t1"
    gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="ops", entity=ent)
    gate.advance(eid, tenant_id=tid, target="EVIDENCE_VERIFIED", actor="ops", entity=ent, evidence_ok=True)
    ent_changed = dict(ent)
    ent_changed["evidenceHash"] = "ev-b"
    ent_changed["lineage"] = {**ent["lineage"], "evidenceHash": "ev-b"}
    with pytest.raises(PermissionError, match="hashes changed"):
        gate.advance(eid, tenant_id=tid, target="WAITING_APPROVAL", actor="ops", entity=ent_changed)


def test_refresh_stale_clears_hashes_allows_full_reverify_to_export():
    gate = ReleaseGate()
    ent = _entity("ent-re")
    eid = "ent-re"
    tid = "t1"
    gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="ops", entity=ent)
    gate.advance(eid, tenant_id=tid, target="EVIDENCE_VERIFIED", actor="ops", entity=ent, evidence_ok=True)
    gate.advance(eid, tenant_id=tid, target="WAITING_APPROVAL", actor="ops", entity=ent)
    mutated = dict(ent)
    mutated["engineeringHash"] = "eng-new"
    mutated["lineage"] = {**(ent.get("lineage") or {}), "engineeringHash": "eng-new"}
    stale = gate.refresh_stale(eid, tenant_id=tid, entity=mutated)
    assert stale["state"] == "PROTOTYPE"
    assert stale["hashes"] == {}
    gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="ops", entity=mutated)
    gate.advance(eid, tenant_id=tid, target="EVIDENCE_VERIFIED", actor="ops", entity=mutated, evidence_ok=True)
    gate.advance(eid, tenant_id=tid, target="WAITING_APPROVAL", actor="ops", entity=mutated)
    done = gate.advance(eid, tenant_id=tid, target="APPROVED_FOR_EXPORT", actor="ops", entity=mutated)
    assert done["state"] == "APPROVED_FOR_EXPORT"
    assert done["hashes"]["engineeringHash"] == "eng-new"


class _GateWithAuditPause(ReleaseGate):
    """Hold entity lock through a controllable pause inside audit (concurrency regression)."""

    def __init__(self) -> None:
        super().__init__()
        self._hold = threading.Event()
        self._proceed = threading.Event()
        self.at_audit = threading.Event()

    def arm_slow_audit(self) -> None:
        self._hold.clear()
        self._proceed.clear()
        self.at_audit.clear()

    def release_slow_audit(self) -> None:
        self._proceed.set()

    def audit(self, **kwargs):  # type: ignore[override]
        if self._hold.is_set():
            self.at_audit.set()
            self._proceed.wait(timeout=5)
        return super().audit(**kwargs)


def test_concurrent_advance_does_not_regress_state():
    gate = _GateWithAuditPause()
    ent = _entity("ent-race")
    tid = "t1"
    eid = "ent-race"
    errors: list[BaseException] = []

    def slow_engineering() -> None:
        try:
            gate.arm_slow_audit()
            gate._hold.set()
            gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="slow", entity=ent)
        except BaseException as exc:
            errors.append(exc)

    def fast_to_export() -> None:
        try:
            _advance_chain(gate, eid, tid, ent, to="APPROVED_FOR_EXPORT")
        except BaseException as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_slow = pool.submit(slow_engineering)
        assert gate.at_audit.wait(timeout=5), "slow advance did not reach audit while holding lock"
        f_fast = pool.submit(fast_to_export)
        time.sleep(0.2)
        assert not f_fast.done(), "fast advance should block on entity lock while slow holds audit"
        gate.release_slow_audit()
        f_slow.result(timeout=10)
        f_fast.result(timeout=10)

    assert not errors
    final = gate.approvals[(tid, eid)]["state"]
    assert final == "APPROVED_FOR_EXPORT"
    decisions = [e["decision"] for e in gate.events if e.get("entityId") == eid]
    assert decisions[0] == "ENGINEERING_VALID"
    assert decisions[-1] == "APPROVED_FOR_EXPORT"


def test_concurrent_advance_from_prototype_one_wins_cleanly():
    gate = ReleaseGate()
    ent = _entity("ent-race2")
    tid = "t1"
    eid = "ent-race2"
    barrier = threading.Barrier(2)

    def first_step() -> str:
        barrier.wait(timeout=5)
        try:
            gate.advance(eid, tenant_id=tid, target="ENGINEERING_VALID", actor="ops", entity=ent)
            return "ok"
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=10) for f in [pool.submit(first_step), pool.submit(first_step)]]

    assert results.count("ok") == 2
    assert gate.approvals[(tid, eid)]["state"] == "ENGINEERING_VALID"