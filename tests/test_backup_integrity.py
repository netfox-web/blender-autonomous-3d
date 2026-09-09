"""Phase 481–540 backup/restore integrity. FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread

import pytest

from fox3d.backup import (
    BackupError,
    backup_pilot,
    no_double_complete_ok,
    no_double_consume_ok,
    restore_pilot,
    verify_backup,
)
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
