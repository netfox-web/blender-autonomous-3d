"""Maintenance script for quarantined commerce snapshots."""

import json
import os
from pathlib import Path
from threading import Barrier, Thread

from fox3d.commerce import SnapshotStore
from scripts.assign_commerce_legacy import main


def _legacy(root: Path, kind: str, items: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{kind}.json"
    path.write_text(json.dumps({"kind": kind, "items": items}), encoding="utf-8")
    return path


def _copy(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(source.read_bytes())
    return dest


def _assign_args(root: Path, backup: Path, audit: Path, *, tenant: str, snapshot_ids: list[str], kind: str = "fx") -> list[str]:
    args = [
        "--provider-root",
        str(root),
        "--kind",
        kind,
        "--tenant",
        tenant,
        "--backup",
        str(backup),
        "--audit",
        str(audit),
        "--actor",
        "ops-maintainer",
    ]
    for snapshot_id in snapshot_ids:
        args.extend(["--snapshot-id", snapshot_id])
    return args


def _stderr(capsys) -> dict:
    return json.loads(capsys.readouterr().err)


def _stdout(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_dry_run_lists_claimed_tenant_and_does_not_write(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(
        root,
        "fx",
        [
            {"snapshotId": "plain", "price": 1},
            {"snapshotId": "forged", "tenantId": "tenant-b", "price": 999},
        ],
    )
    before = live.read_bytes()
    code = main(["--provider-root", str(root), "--dry-run", "--kind", "fx"])
    captured = capsys.readouterr()
    assert code == 0
    assert live.read_bytes() == before
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["claimedTenantIdIsNotAuthority"] is True
    rows = {row["snapshotId"]: row for row in report["kinds"][0]["quarantined"]}
    assert rows["forged"]["claimedTenantId"] == "tenant-b"
    assert rows["plain"]["claimedTenantId"] is None
    assert "tenantId" not in rows["forged"]
    store = SnapshotStore(root, kind="fx")
    assert store.active() == []
    assert {row["snapshotId"] for row in store.quarantined()} == {"forged", "plain"}
    assert not (tmp_path / "audit.jsonl").exists()


def test_dry_run_rejects_assignment_options_without_writing(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "tenantId": "tenant-b", "price": 1}])
    before = live.read_bytes()
    code = main(
        ["--provider-root", str(root), "--dry-run", "--kind", "fx", "--snapshot-id", "old", "--tenant", "tenant-a"]
    )
    assert code == 1
    assert live.read_bytes() == before
    assert _stderr(capsys)["error"] == "usage"
    assert SnapshotStore(root, kind="fx").get("old", tenant_id="tenant-a") is None
    assert SnapshotStore(root, kind="fx").get("old", tenant_id="tenant-b") is None


def test_dry_run_unknown_kind_does_not_escape_provider_root(tmp_path, capsys):
    root = tmp_path / "providers"
    root.mkdir()
    code = main(["--provider-root", str(root), "--dry-run", "--kind", "../fx"])
    assert code == 1
    assert _stderr(capsys)["error"] == "invalid-kind"
    assert not (tmp_path / "fx.json").exists()
    assert list(root.iterdir()) == []


def test_dry_run_missing_root_is_not_created(tmp_path, capsys):
    missing = tmp_path / "missing"
    code = main(["--provider-root", str(missing), "--dry-run"])
    assert code == 1
    assert _stderr(capsys)["error"] == "provider-root"
    assert not missing.exists()


def test_dry_run_invalid_json_leaves_file_unchanged(tmp_path, capsys):
    root = tmp_path / "providers"
    root.mkdir()
    live = root / "fx.json"
    live.write_text("{", encoding="utf-8")
    before = live.read_bytes()
    code = main(["--provider-root", str(root), "--dry-run", "--kind", "fx"])
    assert code == 1
    assert live.read_bytes() == before
    assert _stderr(capsys)["error"] == "provider-invalid"


def test_assign_uses_explicit_tenant_not_claimed_tenant(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(
        root,
        "fx",
        [
            {"snapshotId": "forged", "tenantId": "tenant-b", "price": 999},
            {"snapshotId": "plain", "price": 1},
        ],
    )
    backup = _copy(live, tmp_path / "backup" / "fx.json")
    audit = tmp_path / "logs" / "audit.jsonl"
    code = main(_assign_args(root, backup, audit, tenant="tenant-a", snapshot_ids=["forged"]))
    body = _stdout(capsys)
    assert code == 0
    assert body["action"] == "assigned"
    assert body["assignedCount"] == 1
    assert body["tenantId"] == "tenant-a"
    store = SnapshotStore(root, kind="fx")
    opened = store.get("forged", tenant_id="tenant-a")
    assert opened is not None
    assert opened["tenantId"] == "tenant-a"
    assert opened["claimedTenantId"] == "tenant-b"
    assert opened["price"] == 999
    assert store.get("forged", tenant_id="tenant-b") is None
    assert [row["snapshotId"] for row in store.quarantined()] == ["plain"]
    record = json.loads(audit.read_text(encoding="utf-8"))
    assert record["action"] == "assigned"
    assert record["actor"] == "ops-maintainer"
    assert record["snapshotIds"] == ["forged"]
    assert record["backupSha256"]
    assert record["snapshotHashes"]["forged"] == opened["snapshotHash"]


def test_directory_backup_is_accepted(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "material", [{"snapshotId": "mat-1", "price": 4}])
    backup_dir = tmp_path / "backup-dir"
    _copy(live, backup_dir / "material.json")
    audit = tmp_path / "audit.jsonl"
    code = main(_assign_args(root, backup_dir, audit, tenant="tenant-a", snapshot_ids=["mat-1"], kind="material"))
    assert code == 0
    assert _stdout(capsys)["action"] == "assigned"
    assert SnapshotStore(root, kind="material").get("mat-1", tenant_id="tenant-a")["price"] == 4


def test_repeat_assign_does_not_write_again(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(
        root,
        "fx",
        [
            {"snapshotId": "old", "tenantId": "tenant-b", "price": 2},
            {"snapshotId": "other", "price": 3},
        ],
    )
    backup = _copy(live, tmp_path / "backup" / "fx.json")
    audit = tmp_path / "audit.jsonl"
    args = _assign_args(root, backup, audit, tenant="tenant-a", snapshot_ids=["old", "other"])
    assert main(args) == 0
    first = _stdout(capsys)
    after = live.read_bytes()
    hashes = dict(first["snapshotHashes"])
    assert main(args) == 0
    second = _stdout(capsys)
    assert live.read_bytes() == after
    assert second["action"] == "already-assigned"
    assert second["assignedCount"] == 0
    assert second["snapshotHashes"] == hashes
    store = SnapshotStore(root, kind="fx")
    assert store.quarantined() == []
    assert store.get("old", tenant_id="tenant-a")["snapshotHash"] == hashes["old"]
    assert store.get("other", tenant_id="tenant-a")["snapshotHash"] == hashes["other"]
    assert store.get("old", tenant_id="tenant-b") is None
    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [line["action"] for line in lines] == ["assigned", "already-assigned"]
    assert lines[0]["assignedCount"] == 2
    assert lines[1]["assignedCount"] == 0
    assert lines[1]["snapshotHashes"] == hashes


def test_destination_conflict_is_refused(tmp_path, capsys):
    root = tmp_path / "providers"
    root.mkdir()
    live = root / "fx.json"
    live.write_text(
        json.dumps(
            {
                "kind": "fx",
                "formatVersion": 2,
                "items": [
                    {
                        "snapshotId": "old",
                        "tenantId": "tenant-a",
                        "price": 5,
                        "kind": "fx",
                        "source": "MANUAL",
                        "snapshotHash": "kept-hash",
                    }
                ],
                "legacyItems": [{"snapshotId": "old", "claimedTenantId": "tenant-b", "price": 1}],
            }
        ),
        encoding="utf-8",
    )
    before = live.read_bytes()
    backup = _copy(live, tmp_path / "backup" / "fx.json")
    audit = tmp_path / "audit.jsonl"
    code = main(_assign_args(root, backup, audit, tenant="tenant-a", snapshot_ids=["old"]))
    assert code == 1
    assert live.read_bytes() == before
    assert _stderr(capsys)["error"] == "destination-exists"
    record = json.loads(audit.read_text(encoding="utf-8"))
    assert record["action"] == "refused"
    assert record["reason"] == "destination-exists"
    assert record["assignedCount"] == 0
    store = SnapshotStore(root, kind="fx")
    assert store.get("old", tenant_id="tenant-a")["price"] == 5
    assert store.get("old", tenant_id="tenant-a")["snapshotHash"] == "kept-hash"
    assert store.get("old", tenant_id="tenant-b") is None
    assert [row["snapshotId"] for row in store.quarantined()] == ["old"]


def test_other_tenant_cannot_take_an_assigned_snapshot(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "tenantId": "tenant-b", "price": 8}])
    backup = _copy(live, tmp_path / "backup" / "fx.json")
    audit = tmp_path / "audit.jsonl"
    assert main(_assign_args(root, backup, audit, tenant="tenant-a", snapshot_ids=["old"])) == 0
    capsys.readouterr()
    after = live.read_bytes()
    fresh = _copy(live, tmp_path / "backup" / "fx-after.json")
    code = main(_assign_args(root, fresh, audit, tenant="tenant-b", snapshot_ids=["old"]))
    assert code == 1
    assert live.read_bytes() == after
    assert _stderr(capsys)["error"] == "missing"
    store = SnapshotStore(root, kind="fx")
    assert store.get("old", tenant_id="tenant-a")["price"] == 8
    assert store.get("old", tenant_id="tenant-b") is None


def test_backup_must_match_before_write(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "price": 1}])
    before = live.read_bytes()
    backup = tmp_path / "backup" / "fx.json"
    backup.parent.mkdir()
    backup.write_text("{}", encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    code = main(_assign_args(root, backup, audit, tenant="tenant-a", snapshot_ids=["old"]))
    assert code == 1
    assert live.read_bytes() == before
    assert _stderr(capsys)["error"] == "backup-mismatch"
    assert json.loads(audit.read_text(encoding="utf-8"))["reason"] == "backup-mismatch"
    assert SnapshotStore(root, kind="fx").quarantined()[0]["snapshotId"] == "old"


def test_missing_backup_and_live_backup_do_not_assign(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "price": 1}])
    before = live.read_bytes()
    audit = tmp_path / "audit.jsonl"
    missing = main(_assign_args(root, tmp_path / "no-backup.json", audit, tenant="tenant-a", snapshot_ids=["old"]))
    assert missing == 1
    assert _stderr(capsys)["error"] == "backup-missing"
    assert live.read_bytes() == before
    live_backup = main(_assign_args(root, live, audit, tenant="tenant-a", snapshot_ids=["old"]))
    assert live_backup == 1
    assert _stderr(capsys)["error"] == "backup-is-live"
    assert live.read_bytes() == before
    provider_dir = main(_assign_args(root, root, audit, tenant="tenant-a", snapshot_ids=["old"]))
    assert provider_dir == 1
    assert _stderr(capsys)["error"] == "backup-is-live"
    assert live.read_bytes() == before
    assert [row["snapshotId"] for row in SnapshotStore(root, kind="fx").quarantined()] == ["old"]


def test_hardlink_backup_is_refused(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "price": 1}])
    backup = tmp_path / "backup" / "fx.json"
    backup.parent.mkdir()
    os.link(live, backup)
    before = live.read_bytes()
    code = main(_assign_args(root, backup, tmp_path / "audit.jsonl", tenant="tenant-a", snapshot_ids=["old"]))
    assert code == 1
    assert _stderr(capsys)["error"] == "backup-is-live"
    assert live.read_bytes() == before


def test_audit_path_cannot_overwrite_provider_or_backup(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "price": 1}])
    backup = _copy(live, tmp_path / "backup" / "fx.json")
    before = live.read_bytes()
    backup_before = backup.read_bytes()
    as_provider = main(_assign_args(root, backup, live, tenant="tenant-a", snapshot_ids=["old"]))
    assert as_provider == 1
    assert _stderr(capsys)["error"] == "audit-failed"
    assert live.read_bytes() == before
    as_backup = main(_assign_args(root, backup, backup, tenant="tenant-a", snapshot_ids=["old"]))
    assert as_backup == 1
    assert _stderr(capsys)["error"] == "audit-failed"
    assert live.read_bytes() == before
    assert backup.read_bytes() == backup_before
    assert SnapshotStore(root, kind="fx").get("old", tenant_id="tenant-a") is None


def test_duplicate_blank_and_missing_ids_do_not_assign(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "price": 1}])
    backup = _copy(live, tmp_path / "backup" / "fx.json")
    before = live.read_bytes()
    audit = tmp_path / "audit.jsonl"
    duplicate = main(_assign_args(root, backup, audit, tenant="tenant-a", snapshot_ids=["old", "old"]))
    assert duplicate == 1
    assert _stderr(capsys)["error"] == "duplicate-ids"
    blank_tenant = main(
        [
            "--provider-root",
            str(root),
            "--kind",
            "fx",
            "--snapshot-id",
            "old",
            "--tenant",
            "  ",
            "--backup",
            str(backup),
            "--audit",
            str(audit),
            "--actor",
            "ops-maintainer",
        ]
    )
    assert blank_tenant == 1
    assert _stderr(capsys)["error"] == "invalid-tenant"
    missing = main(_assign_args(root, backup, audit, tenant="tenant-a", snapshot_ids=["missing"]))
    assert missing == 1
    assert _stderr(capsys)["error"] == "missing"
    blank_id = main(_assign_args(root, backup, audit, tenant="tenant-a", snapshot_ids=[" "]))
    assert blank_id == 1
    assert _stderr(capsys)["error"] == "invalid-snapshot"
    assert live.read_bytes() == before
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [record["reason"] for record in records] == ["duplicate-ids", "invalid-tenant", "missing", "invalid-snapshot"]
    assert records[0]["snapshotIds"] == ["old", "old"]
    assert records[3]["snapshotIds"] == []
    assert SnapshotStore(root, kind="fx").active() == []


def test_mixed_batch_assigns_nothing(tmp_path, capsys):
    root = tmp_path / "providers"
    root.mkdir()
    live = root / "fx.json"
    live.write_text(
        json.dumps(
            {
                "kind": "fx",
                "formatVersion": 2,
                "items": [{"snapshotId": "done", "tenantId": "tenant-a", "price": 3, "snapshotHash": "done-hash"}],
                "legacyItems": [{"snapshotId": "wait", "price": 4}],
            }
        ),
        encoding="utf-8",
    )
    before = live.read_bytes()
    backup = _copy(live, tmp_path / "backup" / "fx.json")
    code = main(_assign_args(root, backup, tmp_path / "audit.jsonl", tenant="tenant-a", snapshot_ids=["done", "wait"]))
    assert code == 1
    assert live.read_bytes() == before
    assert _stderr(capsys)["error"] == "mixed-state"
    store = SnapshotStore(root, kind="fx")
    assert store.get("done", tenant_id="tenant-a")["price"] == 3
    assert store.get("wait", tenant_id="tenant-a") is None
    assert [row["snapshotId"] for row in store.quarantined()] == ["wait"]


def test_usage_without_flags_does_not_touch_provider_or_audit(tmp_path, capsys):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "price": 1}])
    before = live.read_bytes()
    code = main(["--provider-root", str(root), "--kind", "fx"])
    assert code == 1
    assert _stderr(capsys)["error"] == "usage"
    assert live.read_bytes() == before
    assert list(tmp_path.rglob("audit.jsonl")) == []


def test_concurrent_calls_assign_one_tenant_only(tmp_path):
    root = tmp_path / "providers"
    live = _legacy(root, "fx", [{"snapshotId": "old", "tenantId": "claimed-b", "price": 6}])
    backup = _copy(live, tmp_path / "backup" / "fx.json")
    audit = tmp_path / "audit.jsonl"
    barrier = Barrier(2)
    codes: list[int] = []

    def run(tenant: str) -> None:
        barrier.wait(30)
        codes.append(
            main(
                [
                    "--provider-root",
                    str(root),
                    "--kind",
                    "fx",
                    "--snapshot-id",
                    "old",
                    "--tenant",
                    tenant,
                    "--backup",
                    str(backup),
                    "--audit",
                    str(audit),
                    "--actor",
                    tenant,
                ]
            )
        )

    threads = [Thread(target=run, args=(tenant,)) for tenant in ("tenant-a", "tenant-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    assert sorted(codes) == [0, 1]
    store = SnapshotStore(root, kind="fx")
    owners = [tenant for tenant in ("tenant-a", "tenant-b") if store.get("old", tenant_id=tenant) is not None]
    assert len(owners) == 1
    assert store.get("old", tenant_id=owners[0])["price"] == 6
    other = "tenant-b" if owners[0] == "tenant-a" else "tenant-a"
    assert store.get("old", tenant_id=other) is None
    assert store.quarantined() == []
    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert sorted(line["action"] for line in lines) == ["assigned", "refused"]
    assert [line["tenantId"] for line in lines if line["action"] == "assigned"] == owners
    assert [line["reason"] for line in lines if line["action"] == "refused"] == ["missing"]
    assert all(line["assignedCount"] == (1 if line["action"] == "assigned" else 0) for line in lines)
