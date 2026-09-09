"""Phase 481–540 backup/restore integrity. FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread

import pytest

import fox3d.backup as backup_mod
from fox3d.backup import (
    BackupError,
    backup_pilot,
    evaluate_tenant_restore_matrix,
    no_double_complete_ok,
    no_double_consume_ok,
    restore_pilot,
    tenant_domain_counts,
    verify_backup,
)
from fox3d.inventory import atomic_write_json, read_json
from fox3d.manual_pilot import seed_tenant_backup_fixture
from fox3d.platform import Platform
from fox3d.station import STATION_CAPS


def _facts(**overrides):
    base = {
        "state": "COMPLETED",
        "releaseHash": "rh",
        "reservations": [{"reservationId": "r1", "lotId": "l1", "quantity": 1, "state": "CONSUMED"}],
        "consumedQty": 1,
        "lotConsumed": {"l1": 1},
        "consumeEventCount": 1,
        "completeEventCount": 1,
        "journalHead": "h",
        "journalOk": True,
    }
    base.update(overrides)
    return base


def test_no_double_consume_complete_requires_durable_facts():
    before = _facts()
    assert no_double_consume_ok(before, _facts()) is True
    assert no_double_complete_ok(before, _facts()) is True
    assert no_double_consume_ok(before, _facts(consumedQty=2)) is False
    assert no_double_consume_ok(before, _facts(consumeEventCount=2)) is False
    assert no_double_complete_ok(before, _facts(completeEventCount=2)) is False
    assert no_double_complete_ok(before, _facts(state="IN_PROGRESS")) is False
    assert no_double_consume_ok({}, _facts()) is False
    assert no_double_complete_ok(None, _facts()) is False
    assert no_double_consume_ok(_facts(consumeEventCount=None), _facts()) is False


def test_tenant_scoped_backup_excludes_other_tenant(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    plat.lots.receive(tenant_id="ta", material="PB_18_WHITE", thickness=18, quantity=3, actor="ops", source="MANUAL")
    plat.lots.receive(tenant_id="tb", material="PB_18_WHITE", thickness=18, quantity=5, actor="ops", source="MANUAL")
    plat.pilot.identity.register_operator(tenant_id="ta", display_name="A")
    plat.pilot.identity.register_operator(tenant_id="tb", display_name="B")
    plat.pilot.stations.register(tenant_id="tb", capabilities=list(STATION_CAPS), actor="ops")
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ta"])
    assert verify_backup(dest)["exactSet"] is True
    restore_pilot(dest, tmp_path / "r-a", tenant_id="ta")
    restored = Platform(root=tmp_path / "r-a", mock_blender=True)
    assert restored.lots.list(tenant_id="tb") == []
    assert restored.lots.list(tenant_id="ta")
    assert not any(o.get("tenantId") == "tb" for o in restored.pilot.identity.operators.values())
    assert restored.pilot.stations.list(tenant_id="tb") == []
    assert restored.pilot.journal.list("tb") == []
    with pytest.raises(PermissionError):
        restore_pilot(dest, tmp_path / "r-b", tenant_id="tb")


def test_verify_rejects_extra_missing_duplicate_traversal(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    plat.lots.receive(tenant_id="ta", material="PB_18_WHITE", thickness=18, quantity=2, actor="ops", source="MANUAL")
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ta"])
    extra = dest / "data" / "lots" / "ghost.json"
    extra.write_text("{}", encoding="utf-8")
    with pytest.raises(BackupError, match="unlisted"):
        verify_backup(dest)
    extra.unlink()
    listed = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))["files"][0]["path"]
    (dest / "data" / Path(listed)).unlink()
    with pytest.raises(BackupError, match="missing"):
        verify_backup(dest)


def test_verify_rejects_duplicate_and_traversal_manifest(tmp_path):
    dest = tmp_path / "bak"
    dest.mkdir()
    (dest / "data").mkdir()
    payload = {
        "schemaVersion": "fox3d.backup.v1",
        "files": [{"path": "../etc/passwd", "sha256": "a", "size": 1}],
        "manifestHash": "x",
    }
    (dest / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError):
        verify_backup(dest)
    payload = {
        "schemaVersion": "fox3d.backup.v1",
        "tenantIds": [],
        "files": [
            {"path": "lots/lots.json", "sha256": "a", "size": 1},
            {"path": "lots/lots.json", "sha256": "a", "size": 1},
        ],
    }
    payload["manifestHash"] = "0" * 64
    (dest / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError):
        verify_backup(dest)


def test_restore_rejects_nonempty_destination_and_extra_files(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    plat.lots.receive(tenant_id="ta", material="PB_18_WHITE", thickness=18, quantity=2, actor="ops", source="MANUAL")
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ta"])
    first = tmp_path / "r1"
    restore_pilot(dest, first, tenant_id="ta")
    with pytest.raises(BackupError, match="unexpected"):
        restore_pilot(dest, first, tenant_id="ta")
    extra = dest / "data" / "injected.json"
    extra.write_text("hack", encoding="utf-8")
    with pytest.raises(BackupError, match="unlisted"):
        restore_pilot(dest, tmp_path / "r2", tenant_id="ta")


def test_backup_snapshot_consistent_or_fail_closed(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    plat.lots.receive(tenant_id="ta", material="PB_18_WHITE", thickness=18, quantity=8, actor="ops", source="MANUAL")
    stop = Event()

    def mutate() -> None:
        n = 0
        while not stop.is_set() and n < 20:
            try:
                plat.lots.receive(
                    tenant_id="ta",
                    material="PB_18_WHITE",
                    thickness=18,
                    quantity=1,
                    actor="ops",
                    source="MANUAL",
                    lot_id=plat.lots.list(tenant_id="ta")[0]["lotId"],
                )
            except Exception:
                pass
            n += 1

    thread = Thread(target=mutate)
    thread.start()
    try:
        dest = tmp_path / "bak"
        try:
            backup_pilot(plat.root, dest, tenant_ids=["ta"])
            verify_backup(dest)
            restore_pilot(dest, tmp_path / "r", tenant_id="ta")
            restored = Platform(root=tmp_path / "r", mock_blender=True)
            assert restored.lots.conservation_ok(tenant_id="ta")["ok"] is True
        except BackupError:
            pass
    finally:
        stop.set()
        thread.join(timeout=5)


def test_tenant_backup_preserves_a_and_excludes_b_full_matrix(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    seed_a = seed_tenant_backup_fixture(plat, tenant_id="ta", actor="ops-a")
    seed_tenant_backup_fixture(plat, tenant_id="tb", actor="ops-b")
    plat.pilot.logistics.import_carrier_quote(
        {"carrier": "X", "service": "ground", "charge": 9, "dimDivisor": 6000}, source="IMPORTED"
    )
    plat.pilot.outbox.prepare(
        {"tenant_id": "tb", "aggregate_type": "Seed", "aggregate_id": "tb-tx", "semantic_key": "tb::seed-tx"}
    )
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ta"])
    restore_pilot(dest, tmp_path / "r-a", tenant_id="ta")
    restored = Platform(root=tmp_path / "r-a", mock_blender=True)
    matrix = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="ta", tenant_b="tb")
    assert matrix["tenantLeakageAbsent"] is True
    assert matrix["tenantRequiredStatePreserved"] is True, matrix["missing"]
    assert restored.lots.list(tenant_id="tb") == []
    assert restored.pilot.logistics.carrier_quotes == {}
    again = restored.pilot.logistics.instantiate_cartons(
        tenant_id="ta",
        work_order_id=seed_a["workOrderId"],
        batch_id=seed_a["batchId"],
        plan={"length": 400, "width": 300, "height": 200},
        quantity=1,
        release_hash=seed_a["releaseHash"],
    )
    assert again[0]["cartonId"] == seed_a["cartonId"]
    assert again[0]["tenantId"] == "ta"
    assert seed_a["workOrderId"] in restored.pilot.workorders.orders
    assert seed_a["releaseId"] in restored.pilot.releases.packets
    assert restored.pilot.releases.get(seed_a["releaseId"])["tenantId"] == "ta"


def test_pallet_derived_kept_and_cross_tenant_or_orphan_fail_closed(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    seed_a = seed_tenant_backup_fixture(plat, tenant_id="ta", actor="ops-a")
    seed_b = seed_tenant_backup_fixture(plat, tenant_id="tb", actor="ops-b")
    dest = tmp_path / "bak"
    man = backup_pilot(plat.root, dest, tenant_ids=["ta"])
    restore_pilot(dest, tmp_path / "r-a", tenant_id="ta")
    restored = Platform(root=tmp_path / "r-a", mock_blender=True)
    assert seed_a["palletPlanId"] in restored.pilot.logistics.pallets
    assert seed_b["palletPlanId"] not in restored.pilot.logistics.pallets
    assert man["collectionPolicy"]["GLOBAL_REFERENCE_POLICY"] == "EXCLUDE_FROM_TENANT_SCOPED"
    logistics = plat.root / "logistics" / "logistics.json"
    payload = read_json(logistics)
    payload["pallets"].append(
        {
            "palletPlanId": "cross-mix",
            "cartonIds": [seed_a["cartonId"], seed_b["cartonId"]],
            "pallets": [{"cartonIds": [seed_a["cartonId"], seed_b["cartonId"]]}],
        }
    )
    atomic_write_json(logistics, payload)
    with pytest.raises(BackupError, match="cross-tenant pallet"):
        backup_pilot(plat.root, tmp_path / "bak-cross", tenant_ids=["ta"])
    payload["pallets"][-1] = {"palletPlanId": "orphan", "cartonIds": ["missing-carton"], "pallets": []}
    atomic_write_json(logistics, payload)
    with pytest.raises(BackupError, match="ambiguous pallet"):
        backup_pilot(plat.root, tmp_path / "bak-orphan", tenant_ids=["ta"])


def test_ambiguous_owned_record_fail_closed(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    plat.lots.receive(tenant_id="ta", material="PB_18_WHITE", thickness=18, quantity=2, actor="ops", source="MANUAL")
    lots_path = plat.root / "lots" / "lots.json"
    payload = read_json(lots_path)
    payload["lots"].append({"lotId": "no-tenant", "material": "PB_18_WHITE", "quantity": 1})
    atomic_write_json(lots_path, payload)
    with pytest.raises(BackupError, match="ambiguous"):
        backup_pilot(plat.root, tmp_path / "bak", tenant_ids=["ta"])


def test_snapshot_detects_new_dam_and_remnant_files(tmp_path, monkeypatch):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    seed_tenant_backup_fixture(plat, tenant_id="ta", actor="ops-a")
    orig = backup_mod._copy_one
    state = {"n": 0}

    def wrapped(src, root, data_root, tids):
        if state["n"] == 0:
            state["n"] += 1
            dam = plat.root / "dam" / "ta" / "race"
            dam.mkdir(parents=True, exist_ok=True)
            (dam / "new.bin").write_bytes(b"dam-a")
            plat.remnants.add_from_nesting(
                {"candidateRemnants": [{"w": 40, "h": 40, "area": 1600, "sheetIndex": 1}]},
                material="PB_18_WHITE",
                thickness=18,
                source_run="race-a",
                tenant_id="ta",
            )
        return orig(src, root, data_root, tids)

    monkeypatch.setattr(backup_mod, "_copy_one", wrapped)
    dest = tmp_path / "bak"
    man = backup_pilot(plat.root, dest, tenant_ids=["ta"])
    assert man["consistentSnapshot"] is True
    assert man["snapshotPathSetBound"] is True
    paths = {row["path"] for row in man["files"]}
    assert any(p.startswith("dam/ta/") and p.endswith("new.bin") for p in paths)
    assert "remnants/ta.json" in paths
    restore_pilot(dest, tmp_path / "r", tenant_id="ta")
    assert (tmp_path / "r" / "dam" / "ta" / "race" / "new.bin").exists()


def test_snapshot_delete_relevant_file_retries_or_fails(tmp_path, monkeypatch):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    seed_tenant_backup_fixture(plat, tenant_id="ta", actor="ops-a")
    files = [p for p in (plat.root / "dam" / "ta").rglob("*") if p.is_file()]
    doomed = files[0]
    orig = backup_mod._copy_one
    state = {"n": 0}

    def wrapped(src, root, data_root, tids):
        if state["n"] == 0 and doomed.exists():
            state["n"] += 1
            doomed.unlink()
        return orig(src, root, data_root, tids)

    monkeypatch.setattr(backup_mod, "_copy_one", wrapped)
    dest = tmp_path / "bak"
    try:
        man = backup_pilot(plat.root, dest, tenant_ids=["ta"])
        assert man["consistentSnapshot"] is True
        listed = {row["path"] for row in man["files"]}
        rel = doomed.relative_to(plat.root).as_posix()
        assert rel not in listed
    except BackupError:
        pass


def test_snapshot_b_churn_does_not_leak_or_invalidate_a(tmp_path, monkeypatch):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    seed_tenant_backup_fixture(plat, tenant_id="ta", actor="ops-a")
    seed_tenant_backup_fixture(plat, tenant_id="tb", actor="ops-b")
    orig = backup_mod._copy_one
    state = {"n": 0}

    def wrapped(src, root, data_root, tids):
        if state["n"] == 0:
            state["n"] += 1
            bdam = plat.root / "dam" / "tb" / "race"
            bdam.mkdir(parents=True, exist_ok=True)
            (bdam / "b.bin").write_bytes(b"only-b")
            plat.remnants.add_from_nesting(
                {"candidateRemnants": [{"w": 30, "h": 30, "area": 900, "sheetIndex": 2}]},
                material="PB_18_WHITE",
                thickness=18,
                source_run="race-b",
                tenant_id="tb",
            )
        return orig(src, root, data_root, tids)

    monkeypatch.setattr(backup_mod, "_copy_one", wrapped)
    dest = tmp_path / "bak"
    man = backup_pilot(plat.root, dest, tenant_ids=["ta"])
    assert man["consistentSnapshot"] is True
    paths = {row["path"] for row in man["files"]}
    assert not any(p.startswith("dam/tb/") for p in paths)
    assert "remnants/tb.json" not in paths
    restore_pilot(dest, tmp_path / "r", tenant_id="ta")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    assert restored.lots.list(tenant_id="tb") == []
    assert not (tmp_path / "r" / "dam" / "tb").exists()
    assert [r for r in restored.remnants.items.values() if r.get("tenantId") == "tb"] == []


def test_snapshot_not_accepted_from_lots_hash_alone(tmp_path, monkeypatch):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    plat.lots.receive(tenant_id="ta", material="PB_18_WHITE", thickness=18, quantity=2, actor="ops", source="MANUAL")
    lots_before = (plat.root / "lots" / "lots.json").read_bytes()
    orig = backup_mod._copy_one
    state = {"n": 0}

    def wrapped(src, root, data_root, tids):
        if state["n"] == 0:
            state["n"] += 1
            d = plat.root / "dam" / "ta" / "extra"
            d.mkdir(parents=True, exist_ok=True)
            (d / "ghost.bin").write_bytes(b"ghost")
        return orig(src, root, data_root, tids)

    monkeypatch.setattr(backup_mod, "_copy_one", wrapped)
    dest = tmp_path / "bak"
    man = backup_pilot(plat.root, dest, tenant_ids=["ta"])
    assert (plat.root / "lots" / "lots.json").read_bytes() == lots_before
    assert any(row["path"].endswith("ghost.bin") for row in man["files"])


def _seed_ab(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    seed_a = seed_tenant_backup_fixture(plat, tenant_id="ta", actor="ops-a")
    seed_tenant_backup_fixture(plat, tenant_id="tb", actor="ops-b")
    return plat, seed_a


def _assert_no_manifest(dest: Path) -> None:
    assert not (dest / "manifest.json").exists()


def test_malformed_cartons_object_fail_closed(tmp_path):
    plat, _ = _seed_ab(tmp_path)
    path = plat.root / "logistics" / "logistics.json"
    payload = read_json(path)
    payload["cartons"] = {c["cartonId"]: c for c in payload["cartons"]}
    atomic_write_json(path, payload)
    dest = tmp_path / "bak"
    with pytest.raises(BackupError, match="malformed"):
        backup_pilot(plat.root, dest, tenant_ids=["ta"])
    _assert_no_manifest(dest)


def test_malformed_operations_object_fail_closed(tmp_path):
    plat, _ = _seed_ab(tmp_path)
    path = plat.root / "workorders" / "workorders.json"
    payload = read_json(path)
    payload["operations"] = {o.get("opId") or str(i): o for i, o in enumerate(payload["operations"])}
    atomic_write_json(path, payload)
    dest = tmp_path / "bak"
    with pytest.raises(BackupError, match="malformed"):
        backup_pilot(plat.root, dest, tenant_ids=["ta"])
    _assert_no_manifest(dest)


def test_malformed_qc_checks_string_fail_closed(tmp_path):
    plat, _ = _seed_ab(tmp_path)
    path = plat.root / "qc" / "qc.json"
    payload = read_json(path)
    payload["checks"] = "not-a-list"
    atomic_write_json(path, payload)
    dest = tmp_path / "bak"
    with pytest.raises(BackupError, match="malformed"):
        backup_pilot(plat.root, dest, tenant_ids=["ta"])
    _assert_no_manifest(dest)


def test_malformed_idem_list_fail_closed(tmp_path):
    plat, _ = _seed_ab(tmp_path)
    path = plat.root / "workorders" / "workorders.json"
    payload = read_json(path)
    payload["idem"] = list((payload.get("idem") or {}).items())
    atomic_write_json(path, payload)
    dest = tmp_path / "bak"
    with pytest.raises(BackupError, match="malformed idem"):
        backup_pilot(plat.root, dest, tenant_ids=["ta"])
    _assert_no_manifest(dest)


def test_malformed_packets_list_fail_closed(tmp_path):
    plat, _ = _seed_ab(tmp_path)
    path = plat.root / "releases" / "releases.json"
    payload = read_json(path)
    payload["packets"] = list((payload.get("packets") or {}).items())
    atomic_write_json(path, payload)
    dest = tmp_path / "bak"
    with pytest.raises(BackupError, match="malformed packets"):
        backup_pilot(plat.root, dest, tenant_ids=["ta"])
    _assert_no_manifest(dest)


def test_malformed_derived_pallets_object_fail_closed(tmp_path):
    plat, _ = _seed_ab(tmp_path)
    path = plat.root / "logistics" / "logistics.json"
    payload = read_json(path)
    payload["pallets"] = {p["palletPlanId"]: p for p in payload["pallets"]}
    atomic_write_json(path, payload)
    dest = tmp_path / "bak"
    with pytest.raises(BackupError, match="malformed"):
        backup_pilot(plat.root, dest, tenant_ids=["ta"])
    _assert_no_manifest(dest)


def test_semantic_preservation_rejects_same_count_lot_replacement(tmp_path):
    plat, _seed = _seed_ab(tmp_path)
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ta"])
    restore_pilot(dest, tmp_path / "r", tenant_id="ta")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    good = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="ta", tenant_b="tb")
    assert good["tenantRequiredStatePreserved"] is True
    assert good["tenantStateDigest"]["equal"] is True
    lot = restored.lots.list(tenant_id="ta")[0]
    rec = dict(restored.lots.lots[lot["lotId"]])
    del restored.lots.lots[lot["lotId"]]
    rec["lotId"] = "swap-" + lot["lotId"]
    restored.lots.lots[rec["lotId"]] = rec
    bad = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="ta", tenant_b="tb")
    assert bad["tenantRequiredStatePreserved"] is False
    assert "materialLots" in bad["identityMismatch"]
    assert tenant_domain_counts(plat, "ta")["materialLots"] == tenant_domain_counts(restored, "ta")["materialLots"]


def test_semantic_preservation_rejects_mutated_lineage(tmp_path):
    plat, seed_a = _seed_ab(tmp_path)
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ta"])
    restore_pilot(dest, tmp_path / "r", tenant_id="ta")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    restored.pilot.workorders.orders[seed_a["workOrderId"]]["releaseHash"] = "0" * 64
    restored.pilot.releases.releases[seed_a["releaseId"]]["releaseHash"] = "0" * 64
    restored.pilot.logistics.pallets[seed_a["palletPlanId"]]["cartonIds"] = ["not-parent"]
    key = next(k for k in restored.pilot.workorders._idem if str(k).startswith("ta::"))
    restored.pilot.workorders._idem[key] = "other-object"
    bad = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="ta", tenant_b="tb")
    assert bad["tenantRequiredStatePreserved"] is False
    assert set(bad["identityMismatch"]) >= {"workOrders", "releases", "palletPlans", "idempotency"}


def test_semantic_preservation_rejects_dam_byte_change(tmp_path):
    plat, _seed = _seed_ab(tmp_path)
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ta"])
    restore_pilot(dest, tmp_path / "r", tenant_id="ta")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    files = [p for p in (restored.root / "dam" / "ta").rglob("*") if p.is_file()]
    files[0].write_bytes(files[0].read_bytes() + b"x")
    bad = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="ta", tenant_b="tb")
    assert bad["tenantRequiredStatePreserved"] is False
    assert "dam" in bad["identityMismatch"]
    assert tenant_domain_counts(plat, "ta")["dam"] == tenant_domain_counts(restored, "ta")["dam"]


def test_semantic_preservation_rejects_journal_id_swap(tmp_path):
    plat, _seed = _seed_ab(tmp_path)
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ta"])
    restore_pilot(dest, tmp_path / "r", tenant_id="ta")
    jpath = tmp_path / "r" / "journal" / "ta.json"
    payload = json.loads(jpath.read_text(encoding="utf-8"))
    payload["events"][0]["eventId"] = "mutated-event"
    jpath.write_text(json.dumps(payload), encoding="utf-8")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    bad = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="ta", tenant_b="tb")
    assert bad["tenantRequiredStatePreserved"] is False
    assert "journal" in bad["identityMismatch"]
    assert tenant_domain_counts(plat, "ta")["journal"] == tenant_domain_counts(restored, "ta")["journal"]
