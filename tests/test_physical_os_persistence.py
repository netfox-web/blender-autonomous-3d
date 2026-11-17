"""Persistence, tenant isolation, idempotency, concurrency, and fail-closed tests for Physical-OS & ReleaseGate (#678)."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform


def _entity_with_evidence(rec: dict[str, Any], evidence_hash: str = "ev-hash-001") -> dict[str, Any]:
    eng_hash = (
        rec.get("engineeringHash")
        or (rec.get("engineering") or {}).get("engineeringHash")
        or (rec.get("lineage") or {}).get("engineeringHash")
    )
    lineage = {**(rec.get("lineage") or {}), "engineeringHash": eng_hash, "evidenceHash": evidence_hash}
    return {
        **rec,
        "engineeringHash": eng_hash,
        "evidenceHash": evidence_hash,
        "lineage": lineage,
    }


def test_all_physical_os_and_release_states_survive_restart(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat1 = Platform(root=root, mock_blender=True)
    client1 = TestClient(create_app(plat1))
    headers_a = {"X-Tenant-Id": "tenant-a"}

    pkg_res = client1.post(
        "/api/packaging/structures",
        json={"family": "MAILER_BOX", "productDims": {"width": 120, "height": 80, "depth": 40}},
        headers=headers_a,
    )
    assert pkg_res.status_code == 200
    pkg_id = pkg_res.json()["packageId"]

    engine_pkg = plat1.packaging.build(tenant_id="tenant-a", template="BOX", sku="PKG-ENGINE-1")
    engine_pkg_id = engine_pkg["packageId"]

    acr_res = client1.post(
        "/api/acrylic/products",
        json={"kind": "SIGN_HOLDER", "sheetSku": "ACR_CLEAR_5"},
        headers=headers_a,
    )
    assert acr_res.status_code == 200
    acr_id = acr_res.json()["productId"]

    ret_res = client1.post(
        "/api/retail/fixtures",
        json={"family": "RISER_DISPLAY", "facing": 2, "render": False},
        headers=headers_a,
    )
    assert ret_res.status_code == 200
    ret_id = ret_res.json()["fixtureId"]

    kd_sku = client1.post(
        "/api/kd/skus",
        json={"kind": "BEDSIDE_CABINET", "render": False},
        headers=headers_a,
    )
    assert kd_sku.status_code == 200
    kd_id = kd_sku.json()["spec"]["productId"]

    batch = plat1.kd.production_batch([kd_sku.json()], [2], tenant_id="tenant-a")
    batch_id = batch["batchId"]

    app_res = client1.post(
        "/api/physical-os/approve",
        json={"entityId": acr_id, "actor": "alice"},
        headers=headers_a,
    )
    assert app_res.status_code == 200
    approval_body = app_res.json()
    assert approval_body["approvedAt"]
    assert approval_body["actor"] == "alice"

    ent_ev = _entity_with_evidence(pkg_res.json(), "ev-pkg-1")
    rel1 = client1.post(
        "/api/release/advance",
        json={"entityId": pkg_id, "target": "ENGINEERING_VALID", "actor": "rel-ops", "entity": ent_ev},
        headers=headers_a,
    )
    assert rel1.status_code == 200
    rel2 = client1.post(
        "/api/release/advance",
        json={
            "entityId": pkg_id,
            "target": "EVIDENCE_VERIFIED",
            "actor": "rel-ops",
            "entity": ent_ev,
            "evidenceOk": True,
        },
        headers=headers_a,
    )
    assert rel2.status_code == 200

    assert not list(root.rglob("*.tmp"))

    # Restart platform from the same root
    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))

    assert pkg_id in plat2.physical.packaging.items
    assert engine_pkg_id in plat2.packaging.items
    assert acr_id in plat2.physical.acrylic.items
    assert ret_id in plat2.physical.retail.items
    assert kd_id in plat2.kd.candidates
    assert batch_id in plat2.kd.batches
    assert ("tenant-a", acr_id) in plat2.physical.approvals
    assert plat2.physical.approvals[("tenant-a", acr_id)]["approvedAt"] == approval_body["approvedAt"]
    assert ("tenant-a", pkg_id) in plat2.release.approvals
    assert plat2.release.approvals[("tenant-a", pkg_id)]["state"] == "EVIDENCE_VERIFIED"
    assert len(plat2.release.events) == 3  # 1 physical approve + 2 release advance

    # Verify tenant-scoped GET endpoints after restart
    pkg_list = client2.get("/api/packaging/structures", headers=headers_a)
    assert pkg_list.status_code == 200
    assert {item["packageId"] for item in pkg_list.json()["items"]} == {pkg_id, engine_pkg_id}

    acr_list = client2.get("/api/acrylic/products", headers=headers_a)
    assert acr_list.status_code == 200
    assert [item["productId"] for item in acr_list.json()["items"]] == [acr_id]

    ret_list = client2.get("/api/retail/fixtures", headers=headers_a)
    assert ret_list.status_code == 200
    assert [item["fixtureId"] for item in ret_list.json()["items"]] == [ret_id]

    kd_list = client2.get("/api/kd/candidates", headers=headers_a)
    assert kd_list.status_code == 200
    assert [item["spec"]["productId"] for item in kd_list.json()["items"]] == [kd_id]


def test_cross_tenant_isolation_get_empty_and_approve_404(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    headers_a = {"X-Tenant-Id": "tenant-a"}
    headers_b = {"X-Tenant-Id": "tenant-b"}

    pkg_id = client.post(
        "/api/packaging/structures",
        json={"family": "RSC_CARTON", "productDims": {"width": 100, "height": 80, "depth": 50}},
        headers=headers_a,
    ).json()["packageId"]
    acr_id = client.post(
        "/api/acrylic/products",
        json={"kind": "MENU_STAND"},
        headers=headers_a,
    ).json()["productId"]
    ret_id = client.post(
        "/api/retail/fixtures",
        json={"family": "COUNTER_DISPLAY"},
        headers=headers_a,
    ).json()["fixtureId"]
    kd_rec = client.post(
        "/api/kd/skus",
        json={"kind": "DESK_RISER"},
        headers=headers_a,
    ).json()
    kd_id = kd_rec["spec"]["productId"]
    batch_id = plat.kd.production_batch([kd_rec], [1], tenant_id="tenant-a")["batchId"]

    for endpoint in (
        "/api/packaging/structures",
        "/api/acrylic/products",
        "/api/retail/fixtures",
        "/api/kd/candidates",
    ):
        res_a = client.get(endpoint, headers=headers_a)
        assert res_a.status_code == 200
        assert len(res_a.json()["items"]) == 1

        res_b = client.get(endpoint, headers=headers_b)
        assert res_b.status_code == 200
        assert res_b.json()["items"] == []

    for eid in (pkg_id, acr_id, ret_id, kd_id, batch_id):
        res = client.post(
            "/api/physical-os/approve",
            json={"entityId": eid, "actor": "mallory"},
            headers=headers_b,
        )
        assert res.status_code == 404
        rel = client.post(
            "/api/release/advance",
            json={"entityId": eid, "target": "ENGINEERING_VALID", "actor": "mallory"},
            headers=headers_b,
        )
        assert rel.status_code == 404

    assert not plat.physical.approvals
    assert not plat.release.events


def test_unknown_entity_approve_returns_404(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "tenant-a"}

    for unknown_id in ("00000000-0000-0000-0000-000000000000", "random-uuid-9999", "nonexistent-sku"):
        res = client.post(
            "/api/physical-os/approve",
            json={"entityId": unknown_id, "actor": "ops"},
            headers=headers,
        )
        assert res.status_code == 404

    with pytest.raises(KeyError):
        plat.physical.approve(entity_id="unknown-direct", tenant_id="tenant-a", actor="ops")

    assert not plat.physical.approvals
    assert not plat.release.events


def test_duplicate_approve_is_idempotent_and_keeps_single_audit_across_restart(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat1 = Platform(root=root, mock_blender=True)
    client1 = TestClient(create_app(plat1))
    headers = {"X-Tenant-Id": "tenant-a"}

    acr_id = client1.post(
        "/api/acrylic/products",
        json={"kind": "DISPLAY_BOX"},
        headers=headers,
    ).json()["productId"]

    first = client1.post(
        "/api/physical-os/approve",
        json={"entityId": acr_id, "actor": "first-actor"},
        headers=headers,
    )
    assert first.status_code == 200
    body1 = first.json()
    assert body1["actor"] == "first-actor"
    assert body1["approvedAt"]
    assert body1["audit"]["actor"] == "first-actor"
    assert body1["audit"]["approvedAt"] == body1["approvedAt"]
    event_id = body1["audit"]["eventId"]

    second = client1.post(
        "/api/physical-os/approve",
        json={"entityId": acr_id, "actor": "second-actor"},
        headers=headers,
    )
    assert second.status_code == 200
    body2 = second.json()
    assert body2 == body1
    assert len(plat1.physical.approvals) == 1
    assert len([e for e in plat1.release.events if e["entityId"] == acr_id]) == 1

    # Restart and approve a third time
    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))
    third = client2.post(
        "/api/physical-os/approve",
        json={"entityId": acr_id, "actor": "third-actor"},
        headers=headers,
    )
    assert third.status_code == 200
    body3 = third.json()
    assert body3["actor"] == "first-actor"
    assert body3["approvedAt"] == body1["approvedAt"]
    assert body3["audit"]["eventId"] == event_id
    assert len(plat2.physical.approvals) == 1
    assert len([e for e in plat2.release.events if e["entityId"] == acr_id]) == 1


def test_concurrent_approve_two_threads_creates_single_audit_record(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "tenant-a"}

    pkg_id = client.post(
        "/api/packaging/structures",
        json={"family": "RSC_CARTON", "productDims": {"width": 120, "height": 90, "depth": 60}},
        headers=headers,
    ).json()["packageId"]

    barrier = threading.Barrier(2)

    def worker(actor_name: str) -> dict[str, Any]:
        barrier.wait(timeout=5)
        res = client.post(
            "/api/physical-os/approve",
            json={"entityId": pkg_id, "actor": actor_name},
            headers=headers,
        )
        assert res.status_code == 200
        return res.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(worker, "thread-1")
        f2 = pool.submit(worker, "thread-2")
        r1 = f1.result(timeout=10)
        r2 = f2.result(timeout=10)

    assert r1["entityId"] == pkg_id
    assert r1["actor"] == r2["actor"]
    assert r1["approvedAt"] == r2["approvedAt"]
    assert r1["audit"]["eventId"] == r2["audit"]["eventId"]
    assert len(plat.physical.approvals) == 1
    pkg_events = [e for e in plat.release.events if e.get("entityId") == pkg_id]
    assert len(pkg_events) == 1

    restarted = Platform(root=root, mock_blender=True)
    assert len(restarted.physical.approvals) == 1
    assert len([e for e in restarted.release.events if e.get("entityId") == pkg_id]) == 1


def test_release_gate_restart_continues_state_without_skip_or_redo(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat1 = Platform(root=root, mock_blender=True)
    client1 = TestClient(create_app(plat1))
    headers = {"X-Tenant-Id": "tenant-a"}

    ret_res = client1.post(
        "/api/retail/fixtures",
        json={"family": "PDQ_DISPLAY"},
        headers=headers,
    )
    assert ret_res.status_code == 200
    fid = ret_res.json()["fixtureId"]
    ent = _entity_with_evidence(ret_res.json(), "ev-pdq-100")

    r1 = client1.post(
        "/api/release/advance",
        json={"entityId": fid, "target": "ENGINEERING_VALID", "actor": "ops", "entity": ent},
        headers=headers,
    )
    assert r1.status_code == 200

    r2 = client1.post(
        "/api/release/advance",
        json={
            "entityId": fid,
            "target": "EVIDENCE_VERIFIED",
            "actor": "ops",
            "entity": ent,
            "evidenceOk": True,
        },
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == "EVIDENCE_VERIFIED"

    # Restart after EVIDENCE_VERIFIED
    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))
    assert plat2.release.approvals[("tenant-a", fid)]["state"] == "EVIDENCE_VERIFIED"
    assert len([e for e in plat2.release.events if e.get("entityId") == fid]) == 2

    # Cannot skip WAITING_APPROVAL to APPROVED_FOR_EXPORT after restart
    skip = client2.post(
        "/api/release/advance",
        json={"entityId": fid, "target": "APPROVED_FOR_EXPORT", "actor": "ops", "entity": ent},
        headers=headers,
    )
    assert skip.status_code == 422

    # Cannot regress back to ENGINEERING_VALID after restart
    regress = client2.post(
        "/api/release/advance",
        json={"entityId": fid, "target": "ENGINEERING_VALID", "actor": "ops", "entity": ent},
        headers=headers,
    )
    assert regress.status_code == 422

    # Re-sending EVIDENCE_VERIFIED is idempotent and does not add a duplicate audit event
    same_step = client2.post(
        "/api/release/advance",
        json={
            "entityId": fid,
            "target": "EVIDENCE_VERIFIED",
            "actor": "ops",
            "entity": ent,
            "evidenceOk": True,
        },
        headers=headers,
    )
    assert same_step.status_code == 200
    assert len([e for e in plat2.release.events if e.get("entityId") == fid]) == 2

    # Tampered hash is rejected across restart
    tampered = _entity_with_evidence(ret_res.json(), "ev-pdq-tampered")
    bad_hash = client2.post(
        "/api/release/advance",
        json={"entityId": fid, "target": "WAITING_APPROVAL", "actor": "ops", "entity": tampered},
        headers=headers,
    )
    assert bad_hash.status_code == 403

    # Advance to WAITING_APPROVAL continues seamlessly from persisted EVIDENCE_VERIFIED
    r3 = client2.post(
        "/api/release/advance",
        json={"entityId": fid, "target": "WAITING_APPROVAL", "actor": "ops", "entity": ent},
        headers=headers,
    )
    assert r3.status_code == 200
    assert r3.json()["state"] == "WAITING_APPROVAL"

    # Second restart after WAITING_APPROVAL
    plat3 = Platform(root=root, mock_blender=True)
    client3 = TestClient(create_app(plat3))
    assert plat3.release.approvals[("tenant-a", fid)]["state"] == "WAITING_APPROVAL"

    # Cannot redo EVIDENCE_VERIFIED once in WAITING_APPROVAL
    redo_ev = client3.post(
        "/api/release/advance",
        json={
            "entityId": fid,
            "target": "EVIDENCE_VERIFIED",
            "actor": "ops",
            "entity": ent,
            "evidenceOk": True,
        },
        headers=headers,
    )
    assert redo_ev.status_code == 422

    # Advance to APPROVED_FOR_EXPORT
    r4 = client3.post(
        "/api/release/advance",
        json={"entityId": fid, "target": "APPROVED_FOR_EXPORT", "actor": "ops", "entity": ent},
        headers=headers,
    )
    assert r4.status_code == 200
    assert r4.json()["state"] == "APPROVED_FOR_EXPORT"
    decisions = [e["decision"] for e in plat3.release.events if e.get("entityId") == fid]
    assert decisions == [
        "ENGINEERING_VALID",
        "EVIDENCE_VERIFIED",
        "WAITING_APPROVAL",
        "APPROVED_FOR_EXPORT",
    ]


@pytest.mark.parametrize(
    "store_dir",
    [
        "packaging",
        "acrylic",
        "retail_fixtures",
        "kd",
        "physical_os",
        "release_gate",
    ],
)
@pytest.mark.parametrize(
    "corrupt_content",
    [
        "{not-valid-json",
        "",
        "[]",
        json.dumps({"tenantId": "tenant-a"}),
        json.dumps({"tenantId": "wrong-tenant", "items": [], "candidates": [], "batches": [], "approvals": [], "events": []}),
        json.dumps({"tenantId": "tenant-a", "items": ["not-an-object"], "candidates": ["bad"], "batches": [], "approvals": ["bad"], "events": []}),
    ],
)
def test_corrupt_state_file_fails_closed_and_does_not_silently_clear(
    tmp_path: Path, store_dir: str, corrupt_content: str
) -> None:
    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    pkg = plat.physical.packaging.build(
        tenant_id="tenant-a", family="RSC_CARTON", product_dims={"width": 100, "height": 80, "depth": 50}
    )
    acr = plat.physical.acrylic.build(tenant_id="tenant-a", kind="MENU_STAND")
    ret = plat.physical.retail.build(tenant_id="tenant-a", family="RISER_DISPLAY")
    kd_rec = plat.kd.build_sku(tenant_id="tenant-a", kind="OPEN_SHELF")
    plat.kd.production_batch([kd_rec], [1], tenant_id="tenant-a")
    plat.physical.approve(entity_id=acr["productId"], tenant_id="tenant-a", actor="ops")
    ent_ev = _entity_with_evidence(pkg, "ev-1")
    plat.release.advance(pkg["packageId"], tenant_id="tenant-a", target="ENGINEERING_VALID", actor="ops", entity=ent_ev)

    target_file = root / store_dir / "tenant-a.json"
    assert target_file.is_file()
    target_file.write_text(corrupt_content, encoding="utf-8")

    # Reloading existing store must fail closed and preserve in-memory state
    store_obj: Any = {
        "packaging": plat.physical.packaging,
        "acrylic": plat.physical.acrylic,
        "retail_fixtures": plat.physical.retail,
        "kd": plat.kd,
        "physical_os": plat.physical,
        "release_gate": plat.release,
    }[store_dir]
    with pytest.raises(ValueError):
        store_obj.load()

    # In-memory state was not wiped on failed load, and corrupt file was not deleted
    assert target_file.is_file()
    assert pkg["packageId"] in plat.physical.packaging.items
    assert acr["productId"] in plat.physical.acrylic.items
    assert ret["fixtureId"] in plat.physical.retail.items
    assert kd_rec["spec"]["productId"] in plat.kd.candidates
    assert ("tenant-a", acr["productId"]) in plat.physical.approvals
    assert ("tenant-a", pkg["packageId"]) in plat.release.approvals

    # Starting a new Platform against the corrupted root must also fail closed
    with pytest.raises(ValueError):
        Platform(root=root, mock_blender=True)


@pytest.mark.parametrize(
    "endpoint,body",
    [
        ("/api/physical-os/approve", {"entityId": "valid-id", "actor": ""}),
        ("/api/physical-os/approve", {"entityId": "valid-id", "actor": "   "}),
        ("/api/physical-os/approve", {"entityId": "valid-id", "actor": 123}),
        ("/api/physical-os/approve", {"entityId": "valid-id", "actor": True}),
        ("/api/physical-os/approve", {"entityId": "valid-id", "kind": 123}),
        ("/api/physical-os/approve", {"entityId": "valid-id", "kind": ["bad"]}),
        ("/api/release/advance", {"entityId": "valid-id", "actor": ""}),
        ("/api/release/advance", {"entityId": "valid-id", "actor": 123}),
        ("/api/release/advance", {"entityId": "valid-id", "target": ""}),
        ("/api/release/advance", {"entityId": "valid-id", "target": 123}),
        ("/api/release/advance", {"entityId": "valid-id", "entity": "not-a-dict"}),
        ("/api/release/advance", {"entityId": "valid-id", "entity": [1, 2]}),
        ("/api/release/advance", {"entityId": "valid-id", "evidenceOk": "false"}),
    ],
)
def test_approve_and_release_advance_reject_malformed_inputs(
    tmp_path: Path, endpoint: str, body: dict[str, Any]
) -> None:
    plat = Platform(root=tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(plat))
    res = client.post(endpoint, json=body, headers={"X-Tenant-Id": "tenant-a"})
    assert res.status_code == 422
    assert "Traceback" not in res.text


def test_approve_kd_candidate_and_batch_and_release_advance_without_resending_entity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    plat1 = Platform(root=root, mock_blender=True)
    client1 = TestClient(create_app(plat1))
    headers = {"X-Tenant-Id": "tenant-a"}

    sku = plat1.kd.build_sku(tenant_id="tenant-a", kind="OPEN_SHELF")
    sku_id = sku["spec"]["productId"]
    batch = plat1.kd.production_batch([sku], [2], tenant_id="tenant-a")
    batch_id = batch["batchId"]

    for eid in (sku_id, batch_id):
        ap1 = client1.post(
            "/api/physical-os/approve",
            json={"entityId": eid, "actor": "kd-lead"},
            headers=headers,
        )
        assert ap1.status_code == 200
        ap2 = client1.post(
            "/api/physical-os/approve",
            json={"entityId": eid, "actor": "other-lead"},
            headers=headers,
        )
        assert ap2.status_code == 200
        assert ap2.json() == ap1.json()

    ent = _entity_with_evidence(sku, "ev-kd-shelf")
    assert (
        client1.post(
            "/api/release/advance",
            json={"entityId": sku_id, "target": "ENGINEERING_VALID", "actor": "ops", "entity": ent},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client1.post(
            "/api/release/advance",
            json={
                "entityId": sku_id,
                "target": "EVIDENCE_VERIFIED",
                "actor": "ops",
                "entity": ent,
                "evidenceOk": True,
            },
            headers=headers,
        ).status_code
        == 200
    )

    # Restart and advance without resending "entity" in body (uses persisted entity + bound evidenceHash)
    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))
    wait_res = client2.post(
        "/api/release/advance",
        json={"entityId": sku_id, "target": "WAITING_APPROVAL", "actor": "ops"},
        headers=headers,
    )
    assert wait_res.status_code == 200
    assert wait_res.json()["state"] == "WAITING_APPROVAL"

    exp_res = client2.post(
        "/api/release/advance",
        json={"entityId": sku_id, "target": "APPROVED_FOR_EXPORT", "actor": "ops"},
        headers=headers,
    )
    assert exp_res.status_code == 200
    assert exp_res.json()["state"] == "APPROVED_FOR_EXPORT"


