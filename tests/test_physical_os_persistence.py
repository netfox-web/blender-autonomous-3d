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
from fox3d.release import safe_tenant_filename


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

    target_file = root / store_dir / f"{safe_tenant_filename('tenant-a')}.json"
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


def test_kd_candidates_50_calls_bounded_file_size_and_preserves_approved(
    tmp_path: Path,
) -> None:
    from fox3d.kd_factory import MAX_UNAPPROVED_CANDIDATES_PER_TENANT

    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    headers_a = {"X-Tenant-Id": "tenant-a"}
    headers_b = {"X-Tenant-Id": "tenant-b"}

    # Seed approved candidates via all supported approval paths
    proto_cand = plat.kd.build_sku(tenant_id="tenant-a", kind="PET_FURNITURE", render=False)
    proto_id = proto_cand["spec"]["productId"]
    plat.kd.confirm_prototype(proto_id, actor="kd-lead")

    phys_cand = plat.kd.build_sku(tenant_id="tenant-a", kind="OPEN_SHELF", render=False)
    phys_id = phys_cand["spec"]["productId"]
    ap_res = client.post(
        "/api/physical-os/approve",
        json={"entityId": phys_id, "actor": "ops"},
        headers=headers_a,
    )
    assert ap_res.status_code == 200

    rel_cand = plat.kd.build_sku(tenant_id="tenant-a", kind="DESK_RISER", render=False)
    rel_id = rel_cand["spec"]["productId"]
    rel_ent = _entity_with_evidence(rel_cand, "ev-kd-rel")
    rel_res = client.post(
        "/api/release/advance",
        json={"entityId": rel_id, "target": "ENGINEERING_VALID", "actor": "ops", "entity": rel_ent},
        headers=headers_a,
    )
    assert rel_res.status_code == 200

    # Other tenant's unapproved candidate must never be evicted by tenant-a activity
    other_cand = plat.kd.build_sku(tenant_id="tenant-b", kind="BEDSIDE_CABINET", render=False)
    other_id = other_cand["spec"]["productId"]

    kd_file = root / "kd" / f"{safe_tenant_filename('tenant-a')}.json"
    size_at_cap: int | None = None

    # 50 consecutive calls to POST /api/kd/candidates (plus build_sku)
    for idx in range(50):
        res = client.post(
            "/api/kd/candidates",
            json={"count": 2},
            headers=headers_a,
        )
        assert res.status_code == 200
        if idx == MAX_UNAPPROVED_CANDIDATES_PER_TENANT:
            size_at_cap = kd_file.stat().st_size

    assert kd_file.is_file()
    final_size = kd_file.stat().st_size
    assert size_at_cap is not None
    # File size is strictly bounded after 50 calls and does not grow linearly
    assert final_size <= int(size_at_cap * 1.25)

    payload = json.loads(kd_file.read_text(encoding="utf-8"))
    persisted_ids = {c["spec"]["productId"] for c in payload["candidates"]}
    assert {proto_id, phys_id, rel_id} <= persisted_ids
    unapproved_persisted = [
        c
        for c in payload["candidates"]
        if c["spec"]["productId"] not in {proto_id, phys_id, rel_id}
    ]
    assert len(unapproved_persisted) == MAX_UNAPPROVED_CANDIDATES_PER_TENANT

    # Restart and verify approved candidates and bounded unapproved candidates survive
    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))
    listed_a = client2.get("/api/kd/candidates", headers=headers_a).json()["items"]
    listed_a_ids = {c["spec"]["productId"] for c in listed_a}
    assert {proto_id, phys_id, rel_id} <= listed_a_ids
    assert len(listed_a) == 3 + MAX_UNAPPROVED_CANDIDATES_PER_TENANT

    listed_b = client2.get("/api/kd/candidates", headers=headers_b).json()["items"]
    assert [c["spec"]["productId"] for c in listed_b] == [other_id]


def test_release_gate_events_50_calls_bounded_per_tenant(tmp_path: Path) -> None:
    from fox3d.release import MAX_EVENTS_PER_TENANT

    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    headers_a = {"X-Tenant-Id": "tenant-a"}
    headers_b = {"X-Tenant-Id": "tenant-b"}

    client.post(
        "/api/release/advance",
        json={
            "entityId": "other-ent",
            "target": "ENGINEERING_VALID",
            "actor": "ops-b",
            "entity": {"skuId": "other-ent", "engineeringHash": "h-b"},
        },
        headers=headers_b,
    )

    rel_file = root / "release_gate" / f"{safe_tenant_filename('tenant-a')}.json"
    for i in range(50):
        adv = client.post(
            "/api/release/advance",
            json={
                "entityId": f"ent-{i}",
                "target": "ENGINEERING_VALID",
                "actor": "ops-a",
                "entity": {"skuId": f"ent-{i}", "engineeringHash": f"h-{i}"},
            },
            headers=headers_a,
        )
        assert adv.status_code == 200

    assert rel_file.is_file()
    payload = json.loads(rel_file.read_text(encoding="utf-8"))
    assert len(payload["events"]) == MAX_EVENTS_PER_TENANT
    assert payload["archivedEventCount"] == 50 - MAX_EVENTS_PER_TENANT
    assert payload["totalEventCount"] == 50
    assert [e["entityId"] for e in payload["events"]] == [
        f"ent-{i}" for i in range(50 - MAX_EVENTS_PER_TENANT, 50)
    ]

    plat2 = Platform(root=root, mock_blender=True)
    events_a = [e for e in plat2.release.events if e.get("tenantId") == "tenant-a"]
    events_b = [e for e in plat2.release.events if e.get("tenantId") == "tenant-b"]
    assert len(events_a) == MAX_EVENTS_PER_TENANT
    assert events_a[-1]["entityId"] == "ent-49"
    assert [e["entityId"] for e in plat2.release.archived_events(tenant_id="tenant-a")] == [
        f"ent-{i}" for i in range(50 - MAX_EVENTS_PER_TENANT)
    ]
    assert [e["entityId"] for e in plat2.release.list_events(tenant_id="tenant-a")] == [
        f"ent-{i}" for i in range(50)
    ]
    assert len(events_b) == 1
    assert events_b[0]["entityId"] == "other-ent"


def test_colliding_tenant_names_isolated_across_restart(tmp_path: Path) -> None:
    """'acme corp' vs 'acme_corp' and 'Acme' vs 'acme' must never collide on disk."""
    root = tmp_path / "data"
    tenants = ("acme corp", "acme_corp", "Acme", "acme")
    stems = [safe_tenant_filename(t) for t in tenants]
    assert len(set(stems)) == len(tenants)
    assert len({s.lower() for s in stems}) == len(tenants)

    plat1 = Platform(root=root, mock_blender=True)
    client1 = TestClient(create_app(plat1))
    recorded: dict[str, dict[str, str]] = {}

    for idx, tid in enumerate(tenants):
        hdr = {"X-Tenant-Id": tid}
        pkg = client1.post(
            "/api/packaging/structures",
            json={"family": "MAILER_BOX", "productDims": {"width": 100 + idx, "height": 80, "depth": 40}},
            headers=hdr,
        ).json()
        acr = client1.post(
            "/api/acrylic/products",
            json={"kind": "SIGN_HOLDER"},
            headers=hdr,
        ).json()
        ret = client1.post(
            "/api/retail/fixtures",
            json={"family": "RISER_DISPLAY"},
            headers=hdr,
        ).json()
        kd_rec = client1.post(
            "/api/kd/skus",
            json={"kind": "BEDSIDE_CABINET"},
            headers=hdr,
        ).json()
        app = client1.post(
            "/api/physical-os/approve",
            json={"entityId": acr["productId"], "actor": f"actor-{idx}"},
            headers=hdr,
        ).json()
        ent_ev = _entity_with_evidence(pkg, f"ev-{idx}")
        rel = client1.post(
            "/api/release/advance",
            json={"entityId": pkg["packageId"], "target": "ENGINEERING_VALID", "actor": f"rel-{idx}", "entity": ent_ev},
            headers=hdr,
        ).json()
        rem_created = plat1.remnants.add_from_nesting(
            {"candidateRemnants": [{"w": 500 + idx * 10, "h": 300, "sheetIndex": 0}]},
            material="WOOD_WHITE",
            thickness=18,
            source_run=f"run-{idx}",
            tenant_id=tid,
        )
        ev = plat1.pilot.journal.append(
            "pilot.test",
            tenant_id=tid,
            aggregate_type="Test",
            aggregate_id=f"agg-{idx}",
            actor=f"actor-{idx}",
            payload={"tenant": tid, "idx": idx},
        )
        recorded[tid] = {
            "pkg": pkg["packageId"],
            "acr": acr["productId"],
            "ret": ret["fixtureId"],
            "kd": kd_rec["spec"]["productId"],
            "app": app["entityId"],
            "rel": rel["entityId"],
            "rem": rem_created[0]["remnantId"],
            "ev": ev["eventId"],
        }

    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))

    for tid in tenants:
        hdr = {"X-Tenant-Id": tid}
        exp = recorded[tid]

        pkgs = client2.get("/api/packaging/structures", headers=hdr).json()["items"]
        assert [p["packageId"] for p in pkgs] == [exp["pkg"]]

        acrs = client2.get("/api/acrylic/products", headers=hdr).json()["items"]
        assert [a["productId"] for a in acrs] == [exp["acr"]]

        rets = client2.get("/api/retail/fixtures", headers=hdr).json()["items"]
        assert [r["fixtureId"] for r in rets] == [exp["ret"]]

        kds = client2.get("/api/kd/candidates", headers=hdr).json()["items"]
        assert [k["spec"]["productId"] for k in kds] == [exp["kd"]]

        rems = client2.get("/api/remnants", headers=hdr).json()["items"]
        assert [r["remnantId"] for r in rems] == [exp["rem"]]

        assert (tid, exp["app"]) in plat2.physical.approvals
        assert (tid, exp["rel"]) in plat2.release.approvals

        j_events = plat2.pilot.journal.list(tid)
        assert [e["eventId"] for e in j_events] == [exp["ev"]]
        assert plat2.pilot.journal.verify(tid)["ok"] is True


def test_legacy_tenant_files_migrate_to_hashed_filenames(tmp_path: Path) -> None:
    from fox3d.inventory import DurableRemnantStore
    from fox3d.journal import EventJournal
    from fox3d.release import legacy_safe_tenant_filename

    root = tmp_path / "data"
    tid = "acme corp"
    legacy_stem = legacy_safe_tenant_filename(tid)
    new_stem = safe_tenant_filename(tid)
    assert legacy_stem == "acme_corp"
    assert new_stem != legacy_stem

    # Seed legacy files on disk using the pre-#689 filename convention
    (root / "packaging").mkdir(parents=True, exist_ok=True)
    (root / "packaging" / f"{legacy_stem}.json").write_text(
        json.dumps({"tenantId": tid, "items": [{"packageId": "pkg-leg-1", "tenantId": tid, "family": "RSC_CARTON"}]}),
        encoding="utf-8",
    )
    (root / "acrylic").mkdir(parents=True, exist_ok=True)
    (root / "acrylic" / f"{legacy_stem}.json").write_text(
        json.dumps({"tenantId": tid, "items": [{"productId": "acr-leg-1", "tenantId": tid, "kind": "MENU_STAND"}]}),
        encoding="utf-8",
    )
    (root / "retail_fixtures").mkdir(parents=True, exist_ok=True)
    (root / "retail_fixtures" / f"{legacy_stem}.json").write_text(
        json.dumps({"tenantId": tid, "items": [{"fixtureId": "ret-leg-1", "tenantId": tid, "family": "RISER_DISPLAY"}]}),
        encoding="utf-8",
    )
    (root / "kd").mkdir(parents=True, exist_ok=True)
    (root / "kd" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "candidates": [{"productId": "kd-leg-1", "tenantId": tid, "spec": {"productId": "kd-leg-1", "tenantId": tid, "kind": "OPEN_SHELF"}}],
                "batches": [{"batchId": "bat-leg-1", "tenantId": tid, "items": []}],
            }
        ),
        encoding="utf-8",
    )
    (root / "physical_os").mkdir(parents=True, exist_ok=True)
    (root / "physical_os" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "approvals": [{"entityId": "acr-leg-1", "tenantId": tid, "actor": "ops", "approvedAt": "2026-11-18T00:00:00+00:00"}],
                "benchmarks": [{"tenantId": tid, "seq": 1}],
            }
        ),
        encoding="utf-8",
    )
    (root / "release_gate").mkdir(parents=True, exist_ok=True)
    (root / "release_gate" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "approvals": [{"entityId": "pkg-leg-1", "tenantId": tid, "state": "ENGINEERING_VALID"}],
                "events": [{"eventId": "ev-leg-1", "entityId": "pkg-leg-1", "tenantId": tid, "decision": "ENGINEERING_VALID"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "remnants").mkdir(parents=True, exist_ok=True)
    (root / "remnants" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "kind": "remnant-store",
                "count": 1,
                "items": [{"remnantId": "rem-leg-1", "tenantId": tid, "status": "available", "w": 500, "h": 300, "thickness": 18, "version": 1}],
            }
        ),
        encoding="utf-8",
    )

    # Seed a legacy journal file and migrate via EventJournal
    j_seed = EventJournal(tmp_path / "seed_journal")
    ev = j_seed.append("pilot.legacy", tenant_id=tid, aggregate_type="Test", aggregate_id="a1", actor="ops")
    seed_payload = json.loads(j_seed._path(tid).read_text(encoding="utf-8"))
    (root / "journal").mkdir(parents=True, exist_ok=True)
    (root / "journal" / f"{legacy_stem}.json").write_text(json.dumps(seed_payload), encoding="utf-8")

    plat = Platform(root=root, mock_blender=True)
    for store_dir in ("packaging", "acrylic", "retail_fixtures", "kd", "physical_os", "release_gate", "remnants", "journal"):
        assert (root / store_dir / f"{new_stem}.json").is_file(), store_dir
        assert not (root / store_dir / f"{legacy_stem}.json").exists(), store_dir

    assert "pkg-leg-1" in plat.physical.packaging.items
    assert "acr-leg-1" in plat.physical.acrylic.items
    assert "ret-leg-1" in plat.physical.retail.items
    assert "kd-leg-1" in plat.kd.candidates
    assert "bat-leg-1" in plat.kd.batches
    assert (tid, "acr-leg-1") in plat.physical.approvals
    assert (tid, "pkg-leg-1") in plat.release.approvals
    assert [r["remnantId"] for r in DurableRemnantStore(root / "remnants").list(tenant_id=tid)] == ["rem-leg-1"]
    assert [e["eventId"] for e in plat.pilot.journal.list(tid)] == [ev["eventId"]]
    assert plat.pilot.journal.verify(tid)["ok"] is True
    # Colliding tenant "acme_corp" sees empty state and does not steal "acme corp"'s migrated data
    assert plat.physical.packaging.list(tenant_id="acme_corp") == []
    assert plat.pilot.journal.list("acme_corp") == []

    # If a stale legacy file coexists with a newer canonical file, canonical state wins and legacy file is cleaned up
    stale_legacy = root / "packaging" / f"{legacy_stem}.json"
    stale_legacy.write_text(
        json.dumps({"tenantId": tid, "items": [{"packageId": "pkg-leg-1", "tenantId": tid, "family": "STALE_FAMILY"}]}),
        encoding="utf-8",
    )
    plat_coexist = Platform(root=root, mock_blender=True)
    assert plat_coexist.physical.packaging.items["pkg-leg-1"]["family"] == "RSC_CARTON"
    assert not stale_legacy.exists()


def test_cross_process_hashed_stem_collision_does_not_clobber_victim(tmp_path: Path) -> None:
    """Tenant 'victim-1bdd5b5b92e2' must never treat victim's canonical file as its own legacy file."""
    import os
    import subprocess
    import sys
    from fox3d.release import legacy_safe_tenant_filename

    root = tmp_path / "data"
    victim = "victim"
    victim_stem = safe_tenant_filename(victim)
    colliding_tenant = victim_stem
    assert legacy_safe_tenant_filename(colliding_tenant) == victim_stem
    colliding_canonical_stem = safe_tenant_filename(colliding_tenant)
    assert colliding_canonical_stem != victim_stem

    # 1. Resident process starts first on an empty root.
    resident = Platform(root=root, mock_blender=True)
    resident_client = TestClient(create_app(resident))

    # 2. Separate process creates durable records for 'victim' across all per-tenant stores.
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    writer_script = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, os.environ['FOX3D_SRC'])\n"
        "from fox3d.platform import Platform\n"
        "root = Path(sys.argv[1])\n"
        "tid = sys.argv[2]\n"
        "plat = Platform(root=root, mock_blender=True)\n"
        "pkg = plat.physical.packaging.build(tenant_id=tid, family='RSC_CARTON', product_dims={'width': 120, 'height': 80, 'depth': 50})\n"
        "acr = plat.physical.acrylic.build(tenant_id=tid, kind='MENU_STAND')\n"
        "ret = plat.physical.retail.build(tenant_id=tid, family='RISER_DISPLAY')\n"
        "kd_sku = plat.kd.build_sku(tenant_id=tid, kind='OPEN_SHELF')\n"
        "bat = plat.kd.production_batch([kd_sku], [1], tenant_id=tid)\n"
        "plat.physical.approve(entity_id=acr['productId'], tenant_id=tid, actor='ops-v')\n"
        "plat.physical.record_benchmark({'score': 99}, tenant_id=tid)\n"
        "eng = pkg.get('engineeringHash') or (pkg.get('engineering') or {}).get('engineeringHash') or 'eh-v'\n"
        "plat.release.advance(pkg['packageId'], tenant_id=tid, target='ENGINEERING_VALID', actor='ops-v', entity={**pkg, 'engineeringHash': eng, 'evidenceHash': 'ev-v'})\n"
        "rems = plat.remnants.add_from_nesting({'candidateRemnants': [{'w': 500, 'h': 300, 'sheetIndex': 0}]}, material='WOOD_WHITE', thickness=18, source_run='run-v', tenant_id=tid)\n"
        "jev = plat.pilot.journal.append('pilot.victim', tenant_id=tid, aggregate_type='Test', aggregate_id='v1', actor='ops-v')\n"
        "print(json.dumps({\n"
        "  'pkg': pkg['packageId'],\n"
        "  'acr': acr['productId'],\n"
        "  'ret': ret['fixtureId'],\n"
        "  'kd': kd_sku['spec']['productId'],\n"
        "  'bat': bat['batchId'],\n"
        "  'rems': sorted(r['remnantId'] for r in plat.remnants.snapshot(tenant_id=tid)['items']),\n"
        "  'jev': jev['eventId'],\n"
        "}))\n"
    )
    env = {**os.environ, "FOX3D_SRC": src_dir, "FOX3D_MOCK_BLENDER": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", writer_script, str(root), victim],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    created = json.loads(proc.stdout.strip().splitlines()[-1])

    store_dirs = (
        "packaging",
        "acrylic",
        "retail_fixtures",
        "kd",
        "physical_os",
        "release_gate",
        "remnants",
        "journal",
    )
    for sdir in store_dirs:
        assert (root / sdir / f"{victim_stem}.json").is_file(), sdir

    # 3. Resident process now queries as colliding_tenant ('victim-1bdd5b5b92e2').
    hdr_collide = {"X-Tenant-Id": colliding_tenant}
    for ep in (
        "/api/packaging/structures",
        "/api/acrylic/products",
        "/api/retail/fixtures",
        "/api/kd/candidates",
        "/api/remnants",
    ):
        res = resident_client.get(ep, headers=hdr_collide)
        assert res.status_code == 200
        assert res.json()["items"] == []

    assert resident.kd.list_batches(tenant_id=colliding_tenant) == []
    resident.physical._sync_tenant(colliding_tenant)
    resident.release._sync_tenant(colliding_tenant)
    assert resident.pilot.journal.list(colliding_tenant) == []
    assert resident.pilot.journal.verify(colliding_tenant)["ok"] is True

    # Victim's canonical files must ALL still exist and retain victim's data!
    for sdir in store_dirs:
        victim_file = root / sdir / f"{victim_stem}.json"
        assert victim_file.is_file(), f"victim file deleted in {sdir}"
        disk_payload = json.loads(victim_file.read_text(encoding="utf-8"))
        assert disk_payload["tenantId"] == victim
        assert not (root / sdir / f"{colliding_canonical_stem}.json").exists(), sdir

    # 4. Resident process can also write its own state for colliding_tenant without harming victim.
    col_pkg = resident_client.post(
        "/api/packaging/structures",
        json={"family": "MAILER_BOX", "productDims": {"width": 140, "height": 90, "depth": 50}},
        headers=hdr_collide,
    )
    assert col_pkg.status_code == 200
    col_pkg_id = col_pkg.json()["packageId"]
    assert (root / "packaging" / f"{victim_stem}.json").is_file()
    assert (root / "packaging" / f"{colliding_canonical_stem}.json").is_file()

    # 5. Restarting Platform keeps both tenants' data intact and isolated.
    reloaded = Platform(root=root, mock_blender=True)
    reloaded_client = TestClient(create_app(reloaded))
    hdr_victim = {"X-Tenant-Id": victim}

    assert [p["packageId"] for p in reloaded_client.get("/api/packaging/structures", headers=hdr_victim).json()["items"]] == [created["pkg"]]
    assert [p["packageId"] for p in reloaded_client.get("/api/packaging/structures", headers=hdr_collide).json()["items"]] == [col_pkg_id]
    assert [a["productId"] for a in reloaded_client.get("/api/acrylic/products", headers=hdr_victim).json()["items"]] == [created["acr"]]
    assert [r["fixtureId"] for r in reloaded_client.get("/api/retail/fixtures", headers=hdr_victim).json()["items"]] == [created["ret"]]
    assert [k["spec"]["productId"] for k in reloaded_client.get("/api/kd/candidates", headers=hdr_victim).json()["items"]] == [created["kd"]]
    assert [b["batchId"] for b in reloaded.kd.list_batches(tenant_id=victim)] == [created["bat"]]
    assert (victim, created["acr"]) in reloaded.physical.approvals
    assert (victim, created["pkg"]) in reloaded.release.approvals
    assert sorted(r["remnantId"] for r in reloaded_client.get("/api/remnants", headers=hdr_victim).json()["items"]) == created["rems"]
    assert [e["eventId"] for e in reloaded.pilot.journal.list(victim)] == [created["jev"]]

    # 6. Conversely, a genuine legacy file owned by colliding_tenant ('victim-1bdd5b5b92e2') migrates cleanly.
    leg_root = tmp_path / "genuine-legacy"
    (leg_root / "packaging").mkdir(parents=True, exist_ok=True)
    (leg_root / "packaging" / f"{victim_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": colliding_tenant,
                "items": [{"packageId": "pkg-col-leg", "tenantId": colliding_tenant, "family": "RSC_CARTON"}],
            }
        ),
        encoding="utf-8",
    )
    j_col_seed = Platform(root=tmp_path / "seed-col", mock_blender=True)
    ev_col = j_col_seed.pilot.journal.append(
        "pilot.col", tenant_id=colliding_tenant, aggregate_type="Test", aggregate_id="c1", actor="ops"
    )
    col_j_payload = json.loads(j_col_seed.pilot.journal._path(colliding_tenant).read_text(encoding="utf-8"))
    (leg_root / "journal").mkdir(parents=True, exist_ok=True)
    (leg_root / "journal" / f"{victim_stem}.json").write_text(json.dumps(col_j_payload), encoding="utf-8")

    migrated = Platform(root=leg_root, mock_blender=True)
    assert (leg_root / "packaging" / f"{colliding_canonical_stem}.json").is_file()
    assert not (leg_root / "packaging" / f"{victim_stem}.json").exists()
    assert [p["packageId"] for p in migrated.physical.packaging.list(tenant_id=colliding_tenant)] == ["pkg-col-leg"]
    assert [e["eventId"] for e in migrated.pilot.journal.list(colliding_tenant)] == [ev_col["eventId"]]
    assert (leg_root / "journal" / f"{colliding_canonical_stem}.json").is_file()
    assert not (leg_root / "journal" / f"{victim_stem}.json").exists()


def test_coexisting_legacy_and_canonical_files_do_not_resurrect_deleted_items(tmp_path: Path) -> None:
    """Interrupted migration leaving both legacy and canonical files must not resurrect deleted items."""
    from fox3d.inventory import DurableRemnantStore
    from fox3d.release import legacy_safe_tenant_filename

    root = tmp_path / "data"
    tid = "acme corp"
    legacy_stem = legacy_safe_tenant_filename(tid)
    canonical_stem = safe_tenant_filename(tid)

    def _write_pair(store_dir: str, legacy_obj: dict[str, Any], canonical_obj: dict[str, Any]) -> tuple[Path, Path]:
        d = root / store_dir
        d.mkdir(parents=True, exist_ok=True)
        leg = d / f"{legacy_stem}.json"
        can = d / f"{canonical_stem}.json"
        leg.write_text(json.dumps(legacy_obj), encoding="utf-8")
        can.write_text(json.dumps(canonical_obj), encoding="utf-8")
        return leg, can

    leg_pkg, can_pkg = _write_pair(
        "packaging",
        {
            "tenantId": tid,
            "items": [
                {"packageId": "pkg-keep", "tenantId": tid, "family": "RSC_CARTON"},
                {"packageId": "pkg-deleted", "tenantId": tid, "family": "MAILER_BOX"},
            ],
        },
        {
            "tenantId": tid,
            "items": [
                {"packageId": "pkg-keep", "tenantId": tid, "family": "RSC_CARTON"},
            ],
        },
    )
    leg_acr, can_acr = _write_pair(
        "acrylic",
        {
            "tenantId": tid,
            "items": [
                {"productId": "acr-keep", "tenantId": tid, "kind": "MENU_STAND"},
                {"productId": "acr-deleted", "tenantId": tid, "kind": "SIGN_HOLDER"},
            ],
        },
        {
            "tenantId": tid,
            "items": [
                {"productId": "acr-keep", "tenantId": tid, "kind": "MENU_STAND"},
            ],
        },
    )
    leg_ret, can_ret = _write_pair(
        "retail_fixtures",
        {
            "tenantId": tid,
            "items": [
                {"fixtureId": "ret-keep", "tenantId": tid, "family": "RISER_DISPLAY"},
                {"fixtureId": "ret-deleted", "tenantId": tid, "family": "PDQ_DISPLAY"},
            ],
        },
        {
            "tenantId": tid,
            "items": [
                {"fixtureId": "ret-keep", "tenantId": tid, "family": "RISER_DISPLAY"},
            ],
        },
    )
    leg_kd, can_kd = _write_pair(
        "kd",
        {
            "tenantId": tid,
            "candidates": [
                {"productId": "kd-keep", "tenantId": tid, "spec": {"productId": "kd-keep", "tenantId": tid, "kind": "OPEN_SHELF"}},
                {"productId": "kd-deleted", "tenantId": tid, "spec": {"productId": "kd-deleted", "tenantId": tid, "kind": "DESK_RISER"}},
            ],
            "batches": [
                {"batchId": "bat-keep", "tenantId": tid, "items": []},
                {"batchId": "bat-deleted", "tenantId": tid, "items": []},
            ],
        },
        {
            "tenantId": tid,
            "candidates": [
                {"productId": "kd-keep", "tenantId": tid, "spec": {"productId": "kd-keep", "tenantId": tid, "kind": "OPEN_SHELF"}},
            ],
            "batches": [
                {"batchId": "bat-keep", "tenantId": tid, "items": []},
            ],
        },
    )
    leg_phys, can_phys = _write_pair(
        "physical_os",
        {
            "tenantId": tid,
            "approvals": [
                {"entityId": "acr-keep", "tenantId": tid, "actor": "ops", "approvedAt": "2026-11-18T00:00:00+00:00"},
                {"entityId": "acr-deleted", "tenantId": tid, "actor": "ops", "approvedAt": "2026-11-18T00:00:00+00:00"},
            ],
            "benchmarks": [
                {"tenantId": tid, "seq": 1},
                {"tenantId": tid, "seq": 999},
            ],
        },
        {
            "tenantId": tid,
            "approvals": [
                {"entityId": "acr-keep", "tenantId": tid, "actor": "ops", "approvedAt": "2026-11-18T00:00:00+00:00"},
            ],
            "benchmarks": [
                {"tenantId": tid, "seq": 1},
            ],
        },
    )
    leg_rel, can_rel = _write_pair(
        "release_gate",
        {
            "tenantId": tid,
            "approvals": [
                {"entityId": "pkg-keep", "tenantId": tid, "state": "ENGINEERING_VALID"},
                {"entityId": "pkg-deleted", "tenantId": tid, "state": "ENGINEERING_VALID"},
            ],
            "events": [
                {"eventId": "ev-keep", "entityId": "pkg-keep", "tenantId": tid, "decision": "ENGINEERING_VALID"},
                {"eventId": "ev-deleted", "entityId": "pkg-deleted", "tenantId": tid, "decision": "ENGINEERING_VALID"},
            ],
        },
        {
            "tenantId": tid,
            "approvals": [
                {"entityId": "pkg-keep", "tenantId": tid, "state": "ENGINEERING_VALID"},
            ],
            "events": [
                {"eventId": "ev-keep", "entityId": "pkg-keep", "tenantId": tid, "decision": "ENGINEERING_VALID"},
            ],
        },
    )
    leg_rem, can_rem = _write_pair(
        "remnants",
        {
            "tenantId": tid,
            "kind": "remnant-store",
            "count": 2,
            "items": [
                {"remnantId": "rem-keep", "tenantId": tid, "status": "available", "w": 500, "h": 300, "thickness": 18, "version": 1},
                {"remnantId": "rem-deleted", "tenantId": tid, "status": "available", "w": 400, "h": 200, "thickness": 18, "version": 1},
            ],
        },
        {
            "tenantId": tid,
            "kind": "remnant-store",
            "count": 1,
            "items": [
                {"remnantId": "rem-keep", "tenantId": tid, "status": "available", "w": 500, "h": 300, "thickness": 18, "version": 1},
            ],
        },
    )

    plat = Platform(root=root, mock_blender=True)

    for leg_path, can_path in (
        (leg_pkg, can_pkg),
        (leg_acr, can_acr),
        (leg_ret, can_ret),
        (leg_kd, can_kd),
        (leg_phys, can_phys),
        (leg_rel, can_rel),
        (leg_rem, can_rem),
    ):
        assert not leg_path.exists(), leg_path
        assert can_path.is_file(), can_path

    assert [r["packageId"] for r in plat.physical.packaging.list(tenant_id=tid)] == ["pkg-keep"]
    assert "pkg-deleted" not in plat.physical.packaging.items
    assert [r["productId"] for r in plat.physical.acrylic.list(tenant_id=tid)] == ["acr-keep"]
    assert "acr-deleted" not in plat.physical.acrylic.items
    assert [r["fixtureId"] for r in plat.physical.retail.list(tenant_id=tid)] == ["ret-keep"]
    assert "ret-deleted" not in plat.physical.retail.items
    assert [r["productId"] for r in plat.kd.list_candidates(tenant_id=tid)] == ["kd-keep"]
    assert "kd-deleted" not in plat.kd.candidates
    assert "kd-deleted" not in plat.parametrics
    assert [b["batchId"] for b in plat.kd.list_batches(tenant_id=tid)] == ["bat-keep"]
    assert "bat-deleted" not in plat.kd.batches
    assert list(plat.physical.approvals.keys()) == [(tid, "acr-keep")]
    assert [b["seq"] for b in plat.physical.benchmarks if b.get("tenantId") == tid] == [1]
    assert list(plat.release.approvals.keys()) == [(tid, "pkg-keep")]
    assert [e["eventId"] for e in plat.release.events if e.get("tenantId") == tid] == ["ev-keep"]
    assert [r["remnantId"] for r in DurableRemnantStore(root / "remnants").list(tenant_id=tid)] == ["rem-keep"]

    # Second restart confirms canonical files on disk were NOT polluted with resurrected legacy records.
    plat2 = Platform(root=root, mock_blender=True)
    assert [r["packageId"] for r in plat2.physical.packaging.list(tenant_id=tid)] == ["pkg-keep"]
    assert [r["productId"] for r in plat2.kd.list_candidates(tenant_id=tid)] == ["kd-keep"]
    assert [e["eventId"] for e in plat2.release.events if e.get("tenantId") == tid] == ["ev-keep"]
    assert [r["remnantId"] for r in DurableRemnantStore(root / "remnants").list(tenant_id=tid)] == ["rem-keep"]

    # Empty canonical file + non-empty legacy file also keeps canonical empty state without resurrection.
    empty_root = tmp_path / "empty-canonical"
    (empty_root / "packaging").mkdir(parents=True, exist_ok=True)
    (empty_root / "packaging" / f"{legacy_stem}.json").write_text(
        json.dumps({"tenantId": tid, "items": [{"packageId": "pkg-ghost", "tenantId": tid, "family": "RSC_CARTON"}]}),
        encoding="utf-8",
    )
    (empty_root / "packaging" / f"{canonical_stem}.json").write_text(
        json.dumps({"tenantId": tid, "items": []}),
        encoding="utf-8",
    )
    plat_empty = Platform(root=empty_root, mock_blender=True)
    assert plat_empty.physical.packaging.list(tenant_id=tid) == []
    assert not (empty_root / "packaging" / f"{legacy_stem}.json").exists()


def test_kd_catalog_count_aligned_with_retention_and_every_returned_id_usable_across_restart(
    tmp_path: Path,
) -> None:
    """Review #4: /api/kd/catalog acceptable count, retention cap, and returned IDs must match."""
    from fox3d.kd_factory import MAX_UNAPPROVED_CANDIDATES_PER_TENANT

    root = tmp_path / "data"
    plat1 = Platform(root=root, mock_blender=True)
    client1 = TestClient(create_app(plat1))
    headers_a = {"X-Tenant-Id": "tenant-a"}
    headers_b = {"X-Tenant-Id": "tenant-b"}

    # 1. Counts exceeding MAX_UNAPPROVED_CANDIDATES_PER_TENANT (including count=40, 25, 100) or invalid types fail with 422.
    for bad_count in (0, -1, MAX_UNAPPROVED_CANDIDATES_PER_TENANT + 1, 40, 100, "40", True, 2.5):
        bad_res = client1.post(
            "/api/kd/catalog",
            json={"count": bad_count, "render": False},
            headers=headers_a,
        )
        assert bad_res.status_code == 422, (bad_count, bad_res.text)
        assert "Traceback" not in bad_res.text

    with pytest.raises(ValueError):
        plat1.kd.generate_candidates(tenant_id="tenant-a", count=40, render=False)
    assert client1.get("/api/kd/candidates", headers=headers_a).json()["items"] == []

    # 2. Generating at the retention cap (count=24) retains every single returned ID.
    cat_res = client1.post(
        "/api/kd/catalog",
        json={"count": MAX_UNAPPROVED_CANDIDATES_PER_TENANT, "render": False},
        headers=headers_a,
    )
    assert cat_res.status_code == 200, cat_res.text
    cat_body = cat_res.json()
    catalog = cat_body["catalog"]
    assert len(catalog) == MAX_UNAPPROVED_CANDIDATES_PER_TENANT
    assert cat_body["retained"] == MAX_UNAPPROVED_CANDIDATES_PER_TENANT
    returned_ids = [row["productId"] for row in catalog]
    assert len(set(returned_ids)) == MAX_UNAPPROVED_CANDIDATES_PER_TENANT
    assert {row["productId"] for row in cat_body["top"]} <= set(returned_ids)

    listed_before = client1.get("/api/kd/candidates", headers=headers_a).json()["items"]
    listed_before_ids = {item["spec"]["productId"] for item in listed_before}
    assert set(returned_ids) == listed_before_ids

    # Tenant isolation: tenant-b sees nothing and gets 404 on returned IDs.
    assert client1.get("/api/kd/candidates", headers=headers_b).json()["items"] == []
    assert (
        client1.post(
            "/api/physical-os/approve",
            json={"entityId": returned_ids[0], "actor": "mallory"},
            headers=headers_b,
        ).status_code
        == 404
    )
    assert (
        client1.post(
            f"/api/parametric/products/{returned_ids[0]}/resize",
            json={"width": 600, "render": False},
            headers=headers_b,
        ).status_code
        == 404
    )

    # 3. Exercise immediate follow-up operations on the first 12 returned IDs before restart.
    for pid in returned_ids[:6]:
        ap = client1.post(
            "/api/physical-os/approve",
            json={"entityId": pid, "actor": "ops-pre"},
            headers=headers_a,
        )
        assert ap.status_code == 200, (pid, ap.text)
    for pid in returned_ids[6:12]:
        rsz = client1.post(
            f"/api/parametric/products/{pid}/resize",
            json={"width": 620, "render": False},
            headers=headers_a,
        )
        assert rsz.status_code == 200, (pid, rsz.text)
        adv = client1.post(
            "/api/release/advance",
            json={"entityId": pid, "target": "ENGINEERING_VALID", "actor": "ops-pre"},
            headers=headers_a,
        )
        assert adv.status_code == 200, (pid, adv.text)

    # 4. Restart Platform and verify ALL 24 returned IDs survive and the remaining 12 IDs also work for follow-up ops.
    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))

    listed_after = client2.get("/api/kd/candidates", headers=headers_a).json()["items"]
    listed_after_ids = {item["spec"]["productId"] for item in listed_after}
    assert set(returned_ids) <= listed_after_ids

    proto_top = plat2.kd.confirm_prototype(returned_ids[0], actor="kd-post")
    assert proto_top["approvalState"] == "APPROVED_FOR_PROTOTYPE"

    for pid in returned_ids[12:18]:
        ap_post = client2.post(
            "/api/physical-os/approve",
            json={"entityId": pid, "actor": "ops-post"},
            headers=headers_a,
        )
        assert ap_post.status_code == 200, (pid, ap_post.text)
    for pid in returned_ids[18:]:
        cand_rec = plat2.kd.candidates[pid]
        if cand_rec.get("approvalState") in {"COMMERCIAL_CANDIDATE", "WAITING_PRODUCT_APPROVAL", "DFM_VALID"}:
            proto = plat2.kd.confirm_prototype(pid, actor="kd-post")
            assert proto["approvalState"] == "APPROVED_FOR_PROTOTYPE"
        adv_post = client2.post(
            "/api/release/advance",
            json={"entityId": pid, "target": "ENGINEERING_VALID", "actor": "ops-post"},
            headers=headers_a,
        )
        assert adv_post.status_code == 200, (pid, adv_post.text)
        rsz_post = client2.post(
            f"/api/parametric/products/{pid}/resize",
            json={"width": 640, "render": False},
            headers=headers_a,
        )
        assert rsz_post.status_code == 200, (pid, rsz_post.text)

    batch = plat2.kd.production_batch([plat2.kd.candidates[returned_ids[-1]]], [2], tenant_id="tenant-a")
    assert batch["batchId"] in plat2.kd.batches

    # 5. Custom max_unapproved_per_tenant dynamically bounds API default and max count as well.
    plat2.kd.max_unapproved_per_tenant = 6
    assert (
        client2.post("/api/kd/catalog", json={"count": 7, "render": False}, headers=headers_b).status_code
        == 422
    )
    ok_custom = client2.post("/api/kd/catalog", json={"render": False}, headers=headers_b)
    assert ok_custom.status_code == 200
    assert len(ok_custom.json()["catalog"]) == 6
    custom_ids = {row["productId"] for row in ok_custom.json()["catalog"]}
    assert {c["spec"]["productId"] for c in client2.get("/api/kd/candidates", headers=headers_b).json()["items"]} == custom_ids


def _seed_legacy_stores_for_tenant(
    root: Path,
    tmp_path: Path,
    tid: str,
    tag: str,
) -> dict[str, str]:
    from fox3d.journal import EventJournal
    from fox3d.release import legacy_safe_tenant_filename

    legacy_stem = legacy_safe_tenant_filename(tid)
    pkg_id = f"pkg-{tag}"
    acr_id = f"acr-{tag}"
    ret_id = f"ret-{tag}"
    kd_id = f"kd-{tag}"
    bat_id = f"bat-{tag}"
    rel_ev_id = f"rel-ev-{tag}"
    rem_id = f"rem-{tag}"

    (root / "packaging").mkdir(parents=True, exist_ok=True)
    (root / "packaging" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "items": [{"packageId": pkg_id, "tenantId": tid, "family": "RSC_CARTON"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "acrylic").mkdir(parents=True, exist_ok=True)
    (root / "acrylic" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "items": [{"productId": acr_id, "tenantId": tid, "kind": "MENU_STAND"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "retail_fixtures").mkdir(parents=True, exist_ok=True)
    (root / "retail_fixtures" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "items": [{"fixtureId": ret_id, "tenantId": tid, "family": "RISER_DISPLAY"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "kd").mkdir(parents=True, exist_ok=True)
    (root / "kd" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "candidates": [
                    {
                        "productId": kd_id,
                        "tenantId": tid,
                        "spec": {"productId": kd_id, "tenantId": tid, "kind": "OPEN_SHELF"},
                    }
                ],
                "batches": [{"batchId": bat_id, "tenantId": tid, "items": []}],
            }
        ),
        encoding="utf-8",
    )
    (root / "physical_os").mkdir(parents=True, exist_ok=True)
    (root / "physical_os" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "approvals": [
                    {
                        "entityId": acr_id,
                        "tenantId": tid,
                        "actor": f"ops-{tag}",
                        "approvedAt": "2026-11-18T00:00:00+00:00",
                    }
                ],
                "benchmarks": [{"tenantId": tid, "tag": tag}],
            }
        ),
        encoding="utf-8",
    )
    (root / "release_gate").mkdir(parents=True, exist_ok=True)
    (root / "release_gate" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "approvals": [
                    {"entityId": pkg_id, "tenantId": tid, "state": "ENGINEERING_VALID"}
                ],
                "events": [
                    {
                        "eventId": rel_ev_id,
                        "entityId": pkg_id,
                        "tenantId": tid,
                        "decision": "ENGINEERING_VALID",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "remnants").mkdir(parents=True, exist_ok=True)
    (root / "remnants" / f"{legacy_stem}.json").write_text(
        json.dumps(
            {
                "tenantId": tid,
                "kind": "remnant-store",
                "count": 1,
                "items": [
                    {
                        "remnantId": rem_id,
                        "tenantId": tid,
                        "status": "available",
                        "w": 500,
                        "h": 300,
                        "thickness": 18,
                        "version": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    j_seed = EventJournal(tmp_path / f"seed_journal_{tag}")
    jev = j_seed.append(
        "pilot.legacy",
        tenant_id=tid,
        aggregate_type="Test",
        aggregate_id=f"agg-{tag}",
        actor=f"ops-{tag}",
    )
    seed_payload = json.loads(j_seed._path(tid).read_text(encoding="utf-8"))
    (root / "journal").mkdir(parents=True, exist_ok=True)
    (root / "journal" / f"{legacy_stem}.json").write_text(
        json.dumps(seed_payload), encoding="utf-8"
    )
    return {
        "pkg": pkg_id,
        "acr": acr_id,
        "ret": ret_id,
        "kd": kd_id,
        "bat": bat_id,
        "rel_ev": rel_ev_id,
        "rem": rem_id,
        "jev": jev["eventId"],
    }


def test_coexisting_legacy_files_with_canonical_path_collision_survive_migration_and_restart(
    tmp_path: Path,
) -> None:
    """Review #696 item 1: victim.json and victim-1bdd5b5b92e2.json coexisting at startup must not delete victim's canonical file."""
    from fox3d.release import legacy_safe_tenant_filename

    root = tmp_path / "data"
    t1 = "victim"
    t2 = safe_tenant_filename(t1)  # "victim-1bdd5b5b92e2"
    t3 = safe_tenant_filename(t2)  # 3rd chained tenant whose legacy filename == t2's canonical filename

    assert t2 == "victim-1bdd5b5b92e2"
    assert legacy_safe_tenant_filename(t2) == safe_tenant_filename(t1)
    assert legacy_safe_tenant_filename(t3) == safe_tenant_filename(t2)

    expected = {
        t1: _seed_legacy_stores_for_tenant(root, tmp_path, t1, "t1"),
        t2: _seed_legacy_stores_for_tenant(root, tmp_path, t2, "t2"),
        t3: _seed_legacy_stores_for_tenant(root, tmp_path, t3, "t3"),
    }

    store_dirs = (
        "packaging",
        "acrylic",
        "retail_fixtures",
        "kd",
        "physical_os",
        "release_gate",
        "remnants",
        "journal",
    )

    # First startup performs migration across all stores.
    plat1 = Platform(root=root, mock_blender=True)
    for tid in (t1, t2, t3):
        assert [p["packageId"] for p in plat1.physical.packaging.list(tenant_id=tid)] == [
            expected[tid]["pkg"]
        ]

    for sdir in store_dirs:
        # t1's legacy file victim.json must be cleaned up, while t1/t2/t3 canonical files must all exist and match their owners!
        assert not (root / sdir / f"{legacy_safe_tenant_filename(t1)}.json").exists(), sdir
        for tid in (t1, t2, t3):
            cpath = root / sdir / f"{safe_tenant_filename(tid)}.json"
            assert cpath.is_file(), f"missing canonical file for {tid} in {sdir}"
            disk_obj = json.loads(cpath.read_text(encoding="utf-8"))
            assert disk_obj["tenantId"] == tid, (sdir, tid, disk_obj.get("tenantId"))

    # Second startup (restart verification) confirms nothing was deleted by post-persist cleanup!
    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))

    for tid in (t1, t2, t3):
        exp = expected[tid]
        hdr = {"X-Tenant-Id": tid}
        assert [
            p["packageId"]
            for p in client2.get("/api/packaging/structures", headers=hdr).json()["items"]
        ] == [exp["pkg"]]
        assert [
            a["productId"]
            for a in client2.get("/api/acrylic/products", headers=hdr).json()["items"]
        ] == [exp["acr"]]
        assert [
            r["fixtureId"]
            for r in client2.get("/api/retail/fixtures", headers=hdr).json()["items"]
        ] == [exp["ret"]]
        assert [
            k["spec"]["productId"]
            for k in client2.get("/api/kd/candidates", headers=hdr).json()["items"]
        ] == [exp["kd"]]
        assert [b["batchId"] for b in plat2.kd.list_batches(tenant_id=tid)] == [exp["bat"]]
        assert (tid, exp["acr"]) in plat2.physical.approvals
        assert [b["tag"] for b in plat2.physical.benchmarks if b.get("tenantId") == tid] == [
            "t1" if tid == t1 else ("t2" if tid == t2 else "t3")
        ]
        assert (tid, exp["pkg"]) in plat2.release.approvals
        assert [e["eventId"] for e in plat2.release.list_events(tenant_id=tid)] == [
            exp["rel_ev"]
        ]
        assert [
            r["remnantId"]
            for r in client2.get("/api/remnants", headers=hdr).json()["items"]
        ] == [exp["rem"]]
        assert [e["eventId"] for e in plat2.pilot.journal.list(tid)] == [exp["jev"]]
        assert plat2.pilot.journal.verify(tid)["ok"] is True


def test_cross_process_coexisting_legacy_collision_lazy_sync_and_write(
    tmp_path: Path,
) -> None:
    """Review #696 item 1: cross-process lazy sync for 'victim' when 'victim-1bdd5b5b92e2.json' is occupied by the other tenant's legacy file."""
    import os
    import subprocess
    import sys

    root = tmp_path / "data"
    victim = "victim"
    colliding = safe_tenant_filename(victim)  # "victim-1bdd5b5b92e2"

    # 1. Resident process starts on empty root.
    resident = Platform(root=root, mock_blender=True)
    resident_client = TestClient(create_app(resident))

    # 2. External writer deposits legacy files victim.json and victim-1bdd5b5b92e2.json while resident is running.
    exp_v = _seed_legacy_stores_for_tenant(root, tmp_path, victim, "v")
    exp_c = _seed_legacy_stores_for_tenant(root, tmp_path, colliding, "c")

    # 3. Resident process queries and writes as 'victim' FIRST (whose canonical path is occupied by colliding's legacy file).
    hdr_v = {"X-Tenant-Id": victim}
    hdr_c = {"X-Tenant-Id": colliding}

    assert [
        p["packageId"]
        for p in resident_client.get("/api/packaging/structures", headers=hdr_v).json()["items"]
    ] == [exp_v["pkg"]]
    assert [
        a["productId"]
        for a in resident_client.get("/api/acrylic/products", headers=hdr_v).json()["items"]
    ] == [exp_v["acr"]]
    assert [
        r["fixtureId"]
        for r in resident_client.get("/api/retail/fixtures", headers=hdr_v).json()["items"]
    ] == [exp_v["ret"]]
    assert [
        k["spec"]["productId"]
        for k in resident_client.get("/api/kd/candidates", headers=hdr_v).json()["items"]
    ] == [exp_v["kd"]]
    assert [b["batchId"] for b in resident.kd.list_batches(tenant_id=victim)] == [exp_v["bat"]]
    resident.physical._sync_tenant(victim)
    assert (victim, exp_v["acr"]) in resident.physical.approvals
    assert [e["eventId"] for e in resident.release.list_events(tenant_id=victim)] == [
        exp_v["rel_ev"]
    ]
    assert [
        r["remnantId"]
        for r in resident_client.get("/api/remnants", headers=hdr_v).json()["items"]
    ] == [exp_v["rem"]]
    assert [e["eventId"] for e in resident.pilot.journal.list(victim)] == [exp_v["jev"]]

    # Resident process also creates a new packaging item for victim.
    new_v_pkg = resident_client.post(
        "/api/packaging/structures",
        json={"family": "MAILER_BOX", "productDims": {"width": 130, "height": 90, "depth": 45}},
        headers=hdr_v,
    ).json()["packageId"]

    # 4. Separate subprocess and restarted Platform both see intact state for BOTH victim and colliding tenant!
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    reader_script = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, os.environ['FOX3D_SRC'])\n"
        "from fox3d.platform import Platform\n"
        "root = Path(sys.argv[1])\n"
        "v, c = sys.argv[2], sys.argv[3]\n"
        "plat = Platform(root=root, mock_blender=True)\n"
        "print(json.dumps({\n"
        "  'v_pkg': sorted(p['packageId'] for p in plat.physical.packaging.list(tenant_id=v)),\n"
        "  'c_pkg': [p['packageId'] for p in plat.physical.packaging.list(tenant_id=c)],\n"
        "  'v_acr': [a['productId'] for a in plat.physical.acrylic.list(tenant_id=v)],\n"
        "  'c_acr': [a['productId'] for a in plat.physical.acrylic.list(tenant_id=c)],\n"
        "  'v_ret': [r['fixtureId'] for r in plat.physical.retail.list(tenant_id=v)],\n"
        "  'c_ret': [r['fixtureId'] for r in plat.physical.retail.list(tenant_id=c)],\n"
        "  'v_kd': [k['productId'] for k in plat.kd.list_candidates(tenant_id=v)],\n"
        "  'c_kd': [k['productId'] for k in plat.kd.list_candidates(tenant_id=c)],\n"
        "  'v_rem': [r['remnantId'] for r in plat.remnants.snapshot(tenant_id=v)['items']],\n"
        "  'c_rem': [r['remnantId'] for r in plat.remnants.snapshot(tenant_id=c)['items']],\n"
        "  'v_jev': [e['eventId'] for e in plat.pilot.journal.list(v)],\n"
        "  'c_jev': [e['eventId'] for e in plat.pilot.journal.list(c)],\n"
        "  'v_rel': [e['eventId'] for e in plat.release.list_events(tenant_id=v)],\n"
        "  'c_rel': [e['eventId'] for e in plat.release.list_events(tenant_id=c)],\n"
        "}))\n"
    )
    env = {**os.environ, "FOX3D_SRC": src_dir, "FOX3D_MOCK_BLENDER": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", reader_script, str(root), victim, colliding],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    observed = json.loads(proc.stdout.strip().splitlines()[-1])
    assert observed["v_pkg"] == sorted([exp_v["pkg"], new_v_pkg])
    assert observed["c_pkg"] == [exp_c["pkg"]]
    assert observed["v_acr"] == [exp_v["acr"]]
    assert observed["c_acr"] == [exp_c["acr"]]
    assert observed["v_ret"] == [exp_v["ret"]]
    assert observed["c_ret"] == [exp_c["ret"]]
    assert observed["v_kd"] == [exp_v["kd"]]
    assert observed["c_kd"] == [exp_c["kd"]]
    assert observed["v_rem"] == [exp_v["rem"]]
    assert observed["c_rem"] == [exp_c["rem"]]
    assert observed["v_jev"] == [exp_v["jev"]]
    assert observed["c_jev"] == [exp_c["jev"]]
    assert observed["v_rel"] == [exp_v["rel_ev"]]
    assert observed["c_rel"] == [exp_c["rel_ev"]]

    # Resident process also sees colliding's data when queried afterwards.
    assert [
        p["packageId"]
        for p in resident_client.get("/api/packaging/structures", headers=hdr_c).json()["items"]
    ] == [exp_c["pkg"]]


def test_release_gate_upgrade_with_21_events_and_21st_event_preserve_full_audit_history(
    tmp_path: Path,
) -> None:
    """Review #696 item 2: upgrading a 21-event tenant file and recording a 21st/22nd event must never lose old audit records."""
    from fox3d.release import MAX_EVENTS_PER_TENANT, legacy_safe_tenant_filename

    root = tmp_path / "data"
    rel_dir = root / "release_gate"
    rel_dir.mkdir(parents=True, exist_ok=True)

    tid_canon = "upgrade-canon"
    tid_legacy = "upgrade legacy"
    tid_fresh = "fresh-tenant"
    tid_other = "other-tenant"

    def _make_events(tid: str, prefix: str, count: int) -> list[dict[str, Any]]:
        return [
            {
                "eventId": f"{prefix}-ev-{i}",
                "actor": "ops",
                "tenantId": tid,
                "entityId": f"{prefix}-ent-{i}",
                "entityVersion": 1,
                "engineeringHash": f"eh-{i}",
                "evidenceHash": f"evh-{i}",
                "hashes": {"engineeringHash": f"eh-{i}", "evidenceHash": f"evh-{i}"},
                "approvedAt": f"2026-11-18T00:00:{i:02d}+00:00",
                "decision": "ENGINEERING_VALID",
                "reason": "release-gate",
                "immutable": True,
                "liveMachineControl": False,
                "auditHash": f"ah-{i}",
            }
            for i in range(count)
        ]

    # Seed 21 pre-existing valid events in both canonical and legacy files before startup.
    canon_events_21 = _make_events(tid_canon, "canon", 21)
    legacy_events_21 = _make_events(tid_legacy, "leg", 21)

    (rel_dir / f"{safe_tenant_filename(tid_canon)}.json").write_text(
        json.dumps(
            {
                "tenantId": tid_canon,
                "approvals": [
                    {
                        "entityId": "canon-ent-0",
                        "tenantId": tid_canon,
                        "state": "ENGINEERING_VALID",
                    }
                ],
                "events": canon_events_21,
            }
        ),
        encoding="utf-8",
    )
    (rel_dir / f"{legacy_safe_tenant_filename(tid_legacy)}.json").write_text(
        json.dumps(
            {
                "tenantId": tid_legacy,
                "approvals": [
                    {
                        "entityId": "leg-ent-0",
                        "tenantId": tid_legacy,
                        "state": "ENGINEERING_VALID",
                    }
                ],
                "events": legacy_events_21,
            }
        ),
        encoding="utf-8",
    )

    # 1. Upgrade load: in-memory active window has 20 events, while earliest event is archived and still readable!
    plat1 = Platform(root=root, mock_blender=True)
    client1 = TestClient(create_app(plat1))

    active_canon = [e for e in plat1.release.events if e.get("tenantId") == tid_canon]
    assert len(active_canon) == MAX_EVENTS_PER_TENANT
    assert [e["eventId"] for e in plat1.release.archived_events(tenant_id=tid_canon)] == [
        "canon-ev-0"
    ]
    assert [e["eventId"] for e in plat1.release.list_events(tenant_id=tid_canon)] == [
        f"canon-ev-{i}" for i in range(21)
    ]
    assert [e["eventId"] for e in plat1.release.list_events(tenant_id=tid_legacy)] == [
        f"leg-ev-{i}" for i in range(21)
    ]

    # 2. Next approval/audit write (22nd event) rotates out the 2nd event to archive without losing the 1st or 2nd event!
    res_canon = client1.post(
        "/api/release/advance",
        json={
            "entityId": "canon-ent-21",
            "target": "ENGINEERING_VALID",
            "actor": "ops",
            "entity": {"skuId": "canon-ent-21", "engineeringHash": "eh-21"},
        },
        headers={"X-Tenant-Id": tid_canon},
    )
    assert res_canon.status_code == 200
    ev21_canon_id = res_canon.json()["audit"]["eventId"]

    res_leg = client1.post(
        "/api/release/advance",
        json={
            "entityId": "leg-ent-21",
            "target": "ENGINEERING_VALID",
            "actor": "ops",
            "entity": {"skuId": "leg-ent-21", "engineeringHash": "eh-21"},
        },
        headers={"X-Tenant-Id": tid_legacy},
    )
    assert res_leg.status_code == 200
    ev21_leg_id = res_leg.json()["audit"]["eventId"]

    assert [e["eventId"] for e in plat1.release.archived_events(tenant_id=tid_canon)] == [
        "canon-ev-0",
        "canon-ev-1",
    ]
    assert [e["eventId"] for e in plat1.release.list_events(tenant_id=tid_canon)] == [
        *[f"canon-ev-{i}" for i in range(21)],
        ev21_canon_id,
    ]
    assert [e["eventId"] for e in plat1.release.list_events(tenant_id=tid_legacy)] == [
        *[f"leg-ev-{i}" for i in range(21)],
        ev21_leg_id,
    ]

    # 3. Fresh tenant: test 21st event and pagination across archived + active events.
    fresh_ev_ids: list[str] = []
    for i in range(21):
        adv = client1.post(
            "/api/release/advance",
            json={
                "entityId": f"fresh-ent-{i}",
                "target": "ENGINEERING_VALID",
                "actor": "ops-f",
                "entity": {"skuId": f"fresh-ent-{i}", "engineeringHash": f"fh-{i}"},
            },
            headers={"X-Tenant-Id": tid_fresh},
        )
        assert adv.status_code == 200
        fresh_ev_ids.append(adv.json()["audit"]["eventId"])

    assert [e["eventId"] for e in plat1.release.archived_events(tenant_id=tid_fresh)] == [
        fresh_ev_ids[0]
    ]
    assert [e["eventId"] for e in plat1.release.list_events(tenant_id=tid_fresh)] == fresh_ev_ids
    assert [
        e["eventId"]
        for e in plat1.release.list_events(tenant_id=tid_fresh, include_archived=False)
    ] == fresh_ev_ids[1:]

    # Pagination checks
    p0 = plat1.release.events_page(tenant_id=tid_fresh, limit=8, offset=0)
    assert p0["total"] == 21
    assert p0["archivedCount"] == 1
    assert p0["activeCount"] == 20
    assert p0["hasMore"] is True
    assert [e["eventId"] for e in p0["items"]] == fresh_ev_ids[:8]

    p1 = plat1.release.events_page(tenant_id=tid_fresh, limit=8, offset=8)
    assert p1["hasMore"] is True
    assert [e["eventId"] for e in p1["items"]] == fresh_ev_ids[8:16]

    p2 = plat1.release.events_page(tenant_id=tid_fresh, limit=8, offset=16)
    assert p2["hasMore"] is False
    assert [e["eventId"] for e in p2["items"]] == fresh_ev_ids[16:]

    # Filter by entity_id works across archived events too (fresh-ent-0 is in archive!)
    assert [
        e["eventId"]
        for e in plat1.release.list_events(tenant_id=tid_fresh, entity_id="fresh-ent-0")
    ] == [fresh_ev_ids[0]]

    # Tenant isolation: another tenant sees 0 events
    assert plat1.release.list_events(tenant_id=tid_other) == []
    assert plat1.release.archived_events(tenant_id=tid_other) == []
    assert plat1.release.events_page(tenant_id=tid_other)["items"] == []

    # Invalid pagination parameters fail closed with ValueError
    for bad_tid in ("", "   "):
        with pytest.raises(ValueError):
            plat1.release.list_events(tenant_id=bad_tid)
        with pytest.raises(ValueError):
            plat1.release.archived_events(tenant_id=bad_tid)
        with pytest.raises(ValueError):
            plat1.release.events_page(tenant_id=bad_tid)
    with pytest.raises(ValueError):
        plat1.release.list_events(tenant_id=tid_fresh, entity_id="")
    with pytest.raises(ValueError):
        plat1.release.archived_events(tenant_id=tid_fresh, entity_id="   ")
    with pytest.raises(ValueError):
        plat1.release.events_page(tenant_id=tid_fresh, entity_id="")
    with pytest.raises(ValueError):
        plat1.release.list_events(tenant_id=tid_fresh, include_archived="no")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        plat1.release.list_events(tenant_id=tid_fresh, offset=-1)
    with pytest.raises(ValueError):
        plat1.release.list_events(tenant_id=tid_fresh, limit=-1)
    with pytest.raises(ValueError):
        plat1.release.list_events(tenant_id=tid_fresh, limit=True)
    with pytest.raises(ValueError):
        plat1.release.events_page(tenant_id=tid_fresh, limit=0)
    with pytest.raises(ValueError):
        plat1.release.events_page(tenant_id=tid_fresh, offset=-1)

    # 4. Restart Platform and verify all 22 events for upgraded tenants and 21 events for fresh tenant survive on disk!
    plat2 = Platform(root=root, mock_blender=True)
    assert [e["eventId"] for e in plat2.release.list_events(tenant_id=tid_canon)] == [
        *[f"canon-ev-{i}" for i in range(21)],
        ev21_canon_id,
    ]
    assert [e["eventId"] for e in plat2.release.list_events(tenant_id=tid_legacy)] == [
        *[f"leg-ev-{i}" for i in range(21)],
        ev21_leg_id,
    ]
    assert [e["eventId"] for e in plat2.release.list_events(tenant_id=tid_fresh)] == fresh_ev_ids





