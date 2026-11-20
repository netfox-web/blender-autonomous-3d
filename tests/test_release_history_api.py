"""Read-only release history and commerce snapshot queries."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.release import MAX_EVENTS_PER_TENANT

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ACTOR_A = "only-tenant-a"
ACTOR_B = "only-tenant-b"


@pytest.fixture()
def client(platform):  # noqa: ANN001
    return TestClient(create_app(platform))


def _headers(tenant_id: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id}


def _entity(entity_id: str) -> dict:
    return {
        "spec": {"productId": entity_id, "revision": 1},
        "engineeringHash": "eng-a",
        "evidenceHash": "ev-a",
        "lineage": {"engineeringHash": "eng-a", "bomHash": "bom-a", "evidenceHash": "ev-a"},
        "bom": {"bomHash": "bom-a"},
    }


def _advance(client: TestClient, tenant_id: str, entity_id: str, *, actor: str = ACTOR_A) -> dict:
    response = client.post(
        "/api/release/advance",
        json={
            "entityId": entity_id,
            "target": "ENGINEERING_VALID",
            "actor": actor,
            "entity": _entity(entity_id),
        },
        headers=_headers(tenant_id),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _event_ids(client: TestClient, tenant_id: str, *, entity_id: str | None = None) -> list[str]:
    collected: list[str] = []
    offset = 0
    while True:
        params: dict[str, str | int] = {"limit": MAX_EVENTS_PER_TENANT, "offset": offset}
        if entity_id is not None:
            params["entityId"] = entity_id
        response = client.get("/api/release/events", params=params, headers=_headers(tenant_id))
        assert response.status_code == 200, response.text
        body = response.json()
        collected.extend(row["eventId"] for row in body["items"])
        if not body["hasMore"]:
            return collected
        offset += body["limit"]


def test_release_events_page_includes_archive_and_hides_other_tenants(client: TestClient, platform) -> None:  # noqa: ANN001
    ids: list[str] = []
    for index in range(MAX_EVENTS_PER_TENANT + 1):
        advanced = _advance(client, TENANT_A, f"hist-{index:02d}")
        ids.append(advanced["audit"]["eventId"])
    foreign = _advance(client, TENANT_B, "hist-00", actor=ACTOR_B)

    listed = _event_ids(client, TENANT_A)
    assert listed == ids
    assert foreign["audit"]["eventId"] not in listed
    first = client.get(
        "/api/release/events",
        params={"limit": MAX_EVENTS_PER_TENANT, "offset": 0},
        headers=_headers(TENANT_A),
    ).json()
    assert first["total"] == MAX_EVENTS_PER_TENANT + 1
    assert first["archivedCount"] == 1
    assert first["activeCount"] == MAX_EVENTS_PER_TENANT
    assert first["hasMore"] is True
    assert first["tenantId"] == TENANT_A
    assert ids[0] in {row["eventId"] for row in first["items"]}

    past = client.get(
        "/api/release/events",
        params={"limit": MAX_EVENTS_PER_TENANT, "offset": MAX_EVENTS_PER_TENANT + 5},
        headers=_headers(TENANT_A),
    )
    assert past.status_code == 200
    past_body = past.json()
    assert past_body["items"] == []
    assert past_body["total"] == MAX_EVENTS_PER_TENANT + 1
    assert past_body["hasMore"] is False

    archived = client.get(
        "/api/release/events",
        params={"entityId": "hist-00"},
        headers=_headers(TENANT_A),
    )
    assert archived.status_code == 200
    archived_body = archived.json()
    assert [row["eventId"] for row in archived_body["items"]] == [ids[0]]
    assert archived_body["archivedCount"] == 1
    assert archived_body["activeCount"] == 0
    assert archived_body["items"][0]["released"] is False

    missing = client.get(
        "/api/release/events",
        params={"entityId": "does-not-exist"},
        headers=_headers(TENANT_A),
    )
    assert missing.status_code == 200
    assert missing.json()["items"] == []
    assert missing.json()["total"] == 0

    leaked = client.get(
        "/api/release/events",
        params={"entityId": "hist-00"},
        headers=_headers(TENANT_B),
    )
    assert leaked.status_code == 200
    leaked_body = leaked.json()
    assert leaked_body["items"]
    assert all(row["tenantId"] == TENANT_B for row in leaked_body["items"])
    assert ids[0] not in {row["eventId"] for row in leaked_body["items"]}
    assert ACTOR_A not in leaked.text
    assert leaked_body["items"][0]["eventId"] == foreign["audit"]["eventId"]

    other_entity = client.get(
        "/api/release/events",
        params={"entityId": "hist-01"},
        headers=_headers(TENANT_B),
    )
    assert other_entity.status_code == 200
    assert other_entity.json()["items"] == []
    assert other_entity.json()["total"] == 0
    assert ids[1] not in other_entity.text
    assert ACTOR_A not in other_entity.text

    before = len(platform.release.events)
    again = client.get("/api/release/events", headers=_headers(TENANT_A))
    repeated = client.get("/api/release/events", headers=_headers(TENANT_A))
    assert again.json() == repeated.json()
    assert len(platform.release.events) == before


@pytest.mark.parametrize(
    ("params",),
    [
        ({"limit": 0},),
        ({"limit": -1},),
        ({"offset": -1},),
        ({"limit": MAX_EVENTS_PER_TENANT + 1},),
        ({"limit": "nope"},),
        ({"entityId": ""},),
        ({"entityId": "../other"},),
        ({"entityId": "has space"},),
    ],
)
def test_release_events_reject_out_of_range_input(client: TestClient, params: dict) -> None:
    response = client.get("/api/release/events", params=params, headers=_headers(TENANT_A))
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert "PermissionError" not in response.text
    assert TENANT_B not in response.text


def test_release_approvals_compute_stale_without_writing(client: TestClient, platform) -> None:  # noqa: ANN001
    created = client.post(
        "/api/acrylic/products",
        json={"kind": "SIGN_HOLDER"},
        headers=_headers(TENANT_A),
    )
    assert created.status_code == 200, created.text
    product = created.json()
    entity_id = product["productId"]
    advanced = client.post(
        "/api/release/advance",
        json={
            "entityId": entity_id,
            "target": "ENGINEERING_VALID",
            "actor": ACTOR_A,
            "entity": product,
        },
        headers=_headers(TENANT_A),
    )
    assert advanced.status_code == 200, advanced.text
    _advance(client, TENANT_B, "b-approval", actor=ACTOR_B)

    stored = platform.release.approvals[(TENANT_A, entity_id)]
    before = copy.deepcopy(stored)
    listed = client.get("/api/release/approvals", headers=_headers(TENANT_A))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["tenantId"] == TENANT_A
    match = next(row for row in body["items"] if row["entityId"] == entity_id)
    assert match["stale"] is False
    assert match["released"] is False
    assert match["state"] == "ENGINEERING_VALID"
    after = platform.release.approvals[(TENANT_A, entity_id)]
    assert after["state"] == before["state"]
    assert after["stale"] == before["stale"]
    assert after["hashes"] == before["hashes"]
    assert "released" not in after

    stored_product = platform.physical.acrylic.items[entity_id]
    stored_product["engineeringHash"] = "changed-hash-for-stale"
    stored_product["lineage"]["engineeringHash"] = "changed-hash-for-stale"
    stale = client.get("/api/release/approvals", headers=_headers(TENANT_A))
    assert stale.status_code == 200
    stale_row = next(row for row in stale.json()["items"] if row["entityId"] == entity_id)
    assert stale_row["stale"] is True
    assert stale_row["released"] is False
    assert stale_row["blocked"] is False
    unchanged = platform.release.approvals[(TENANT_A, entity_id)]
    assert unchanged["stale"] is False
    assert unchanged["state"] == "ENGINEERING_VALID"
    assert unchanged["hashes"]["engineeringHash"] != "changed-hash-for-stale"

    foreign = client.get("/api/release/approvals", headers=_headers(TENANT_B))
    assert foreign.status_code == 200
    foreign_ids = [row["entityId"] for row in foreign.json()["items"]]
    assert foreign_ids == ["b-approval"]
    assert all(row["actor"] == ACTOR_B for row in foreign.json()["items"])
    assert entity_id not in foreign.text
    assert ACTOR_A not in foreign.text
    assert "changed-hash-for-stale" not in foreign.text

    repeated = client.get("/api/release/approvals", headers=_headers(TENANT_A))
    assert repeated.json()["items"] == stale.json()["items"]


def test_release_approvals_released_only_when_export_is_current(client: TestClient, platform, monkeypatch) -> None:  # noqa: ANN001
    entity_id = "export-ready"
    entity = _entity(entity_id)
    steps = (
        ("ENGINEERING_VALID", False),
        ("EVIDENCE_VERIFIED", True),
        ("WAITING_APPROVAL", False),
        ("APPROVED_FOR_EXPORT", False),
    )
    for target, evidence_ok in steps:
        response = client.post(
            "/api/release/advance",
            json={
                "entityId": entity_id,
                "target": target,
                "actor": ACTOR_A,
                "entity": entity,
                "evidenceOk": evidence_ok,
            },
            headers=_headers(TENANT_A),
        )
        assert response.status_code == 200, response.text

    missing = client.get("/api/release/approvals", headers=_headers(TENANT_A)).json()
    missing_row = next(item for item in missing["items"] if item["entityId"] == entity_id)
    assert missing_row["verificationAvailable"] is False
    assert missing_row["released"] is False
    monkeypatch.setattr(platform.physical, "find_entity", lambda *args, **kwargs: entity)
    listed = client.get("/api/release/approvals", headers=_headers(TENANT_A)).json()
    row = next(item for item in listed["items"] if item["entityId"] == entity_id)
    assert row["state"] == "APPROVED_FOR_EXPORT"
    assert row["stale"] is False
    assert row["released"] is True

    mutated = copy.deepcopy(entity)
    mutated["engineeringHash"] = "eng-b"
    mutated["lineage"] = {**entity["lineage"], "engineeringHash": "eng-b"}
    platform.release.refresh_stale(entity_id, tenant_id=TENANT_A, entity=mutated)
    refreshed = client.get("/api/release/approvals", headers=_headers(TENANT_A)).json()
    stale_row = next(item for item in refreshed["items"] if item["entityId"] == entity_id)
    assert stale_row["stale"] is True
    assert stale_row["released"] is False
    assert stale_row["state"] == "PROTOTYPE"
    events = client.get(
        "/api/release/events",
        params={"entityId": entity_id},
        headers=_headers(TENANT_A),
    ).json()
    stale_events = [item for item in events["items"] if item["decision"] == "STALE"]
    assert stale_events
    assert stale_events[-1]["stale"] is True
    assert stale_events[-1]["released"] is False
    approved_events = [item for item in events["items"] if item["decision"] == "APPROVED_FOR_EXPORT"]
    assert approved_events
    assert approved_events[-1]["released"] is True
    assert approved_events[-1]["stale"] is False


def test_commerce_snapshots_are_active_paged_and_tenant_scoped(client: TestClient, platform) -> None:  # noqa: ANN001
    rows = [
        {"snapshotId": "snap-old", "pair": "OLD", "effectiveAt": "2020-01-01", "expiresAt": "2020-02-01"},
        {"snapshotId": "snap-now", "pair": "NOW", "effectiveAt": "2020-01-01", "expiresAt": "2099-01-01"},
        {"snapshotId": "snap-next", "pair": "FUTURE", "effectiveAt": "2099-01-01", "expiresAt": "2099-12-01"},
    ]
    imported = client.post(
        "/api/commerce/import",
        json={"kind": "fx", "source": "MANUAL", "rows": rows},
        headers=_headers(TENANT_A),
    )
    assert imported.status_code == 200, imported.text
    assert all(row["tenantId"] == TENANT_A for row in imported.json()["items"])
    hostile = client.post(
        "/api/commerce/import",
        json={
            "kind": "material",
            "source": "MANUAL",
            "rows": [{"snapshotId": "snap-hostile", "tenantId": TENANT_B, "price": 1}],
        },
        headers=_headers(TENANT_A),
    )
    assert hostile.status_code == 200, hostile.text
    assert hostile.json()["items"][0]["tenantId"] == TENANT_A
    other = client.post(
        "/api/commerce/import",
        json={"kind": "fx", "source": "MANUAL", "rows": [{"snapshotId": "snap-b", "pair": "B"}]},
        headers=_headers(TENANT_B),
    )
    assert other.status_code == 200, other.text
    platform.providers.fx.add({"snapshotId": "snap-unscoped", "pair": "LEAK"}, source="MANUAL")
    platform.providers.logistics.add(
        {"snapshotId": "snap-foreign-direct", "tenantId": TENANT_B, "zone": "SECRET"},
        source="MANUAL",
    )

    current = client.get("/api/commerce/snapshots", headers=_headers(TENANT_A))
    assert current.status_code == 200, current.text
    current_ids = [row["snapshotId"] for row in current.json()["items"]]
    assert "snap-now" in current_ids
    assert "snap-hostile" in current_ids
    assert "snap-old" not in current_ids
    assert "snap-next" not in current_ids
    assert "snap-b" not in current_ids
    assert "snap-unscoped" not in current_ids
    assert "snap-foreign-direct" not in current_ids
    assert "SECRET" not in current.text
    assert all(row["tenantId"] == TENANT_A for row in current.json()["items"])

    at_old = client.get("/api/commerce/snapshots", params={"at": "2020-01-15"}, headers=_headers(TENANT_A))
    assert at_old.status_code == 200
    old_ids = {row["snapshotId"] for row in at_old.json()["items"]}
    assert "snap-old" in old_ids
    assert "snap-now" in old_ids
    assert "snap-next" not in old_ids

    at_future = client.get("/api/commerce/snapshots", params={"at": "2099-06-01"}, headers=_headers(TENANT_A))
    future_ids = {row["snapshotId"] for row in at_future.json()["items"]}
    assert future_ids == {"snap-next", "snap-hostile"}

    paged_rows = [{"snapshotId": f"page-{index:02d}", "price": index} for index in range(5)]
    paged = client.post(
        "/api/commerce/import",
        json={"kind": "hardware", "source": "IMPORTED", "rows": paged_rows},
        headers=_headers(TENANT_A),
    )
    assert paged.status_code == 200
    full = client.get(
        "/api/commerce/snapshots",
        params={"limit": 100, "offset": 0, "at": "2026-06-01"},
        headers=_headers(TENANT_A),
    )
    assert full.status_code == 200
    ordered = [row["snapshotId"] for row in full.json()["items"]]
    assert ordered == ["snap-now", "page-00", "page-01", "page-02", "page-03", "page-04", "snap-hostile"]
    page0 = client.get(
        "/api/commerce/snapshots",
        params={"limit": 2, "offset": 0, "at": "2026-06-01"},
        headers=_headers(TENANT_A),
    )
    assert page0.status_code == 200
    assert [row["snapshotId"] for row in page0.json()["items"]] == ["snap-now", "page-00"]
    assert page0.json()["hasMore"] is True
    middle = client.get(
        "/api/commerce/snapshots",
        params={"limit": 2, "offset": 4, "at": "2026-06-01"},
        headers=_headers(TENANT_A),
    ).json()
    assert [row["snapshotId"] for row in middle["items"]] == ["page-03", "page-04"]
    assert middle["hasMore"] is True
    past = client.get(
        "/api/commerce/snapshots",
        params={"limit": 2, "offset": 1000, "at": "2026-06-01"},
        headers=_headers(TENANT_A),
    )
    assert past.status_code == 200
    assert past.json()["items"] == []
    assert past.json()["total"] == 7
    assert past.json()["hasMore"] is False

    foreign = client.get("/api/commerce/snapshots", params={"at": "2026-06-01"}, headers=_headers(TENANT_B))
    assert foreign.status_code == 200
    foreign_ids = {row["snapshotId"] for row in foreign.json()["items"]}
    assert foreign_ids == {"snap-b", "snap-foreign-direct"}
    assert "snap-now" not in foreign.text
    assert "snap-hostile" not in foreign.text
    assert "page-00" not in foreign.text

    before = len(platform.providers.fx.items)
    first = client.get("/api/commerce/snapshots", headers=_headers(TENANT_A)).json()
    second = client.get("/api/commerce/snapshots", headers=_headers(TENANT_A)).json()
    assert first["items"] == second["items"]
    assert first["total"] == second["total"]
    assert len(platform.providers.fx.items) == before


@pytest.mark.parametrize(
    ("params",),
    [
        ({"limit": 0},),
        ({"limit": -1},),
        ({"offset": -1},),
        ({"limit": 101},),
        ({"at": ""},),
        ({"at": "yesterday"},),
        ({"at": "2026-13-01"},),
    ],
)
def test_commerce_snapshots_reject_out_of_range_input(client: TestClient, params: dict) -> None:
    response = client.get("/api/commerce/snapshots", params=params, headers=_headers(TENANT_A))
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert "snap-" not in response.text


def test_readiness_history_markup_keeps_tables_in_scroll_containers() -> None:
    base = Path(__file__).resolve().parents[1] / "src/fox3d/static/pages"
    html = (base / "readiness.html").read_text(encoding="utf-8")
    css = (base / "readiness.css").read_text(encoding="utf-8")
    js = (base / "readiness.js").read_text(encoding="utf-8")
    for element_id in ("rd-history-table", "rd-approvals-table", "rd-snap-table"):
        assert f'class="rd-table-wrap" id="{element_id}"' in html
    assert 'id="rd-history"' in html
    assert 'id="rd-snapshots"' in html
    assert "overflow-x:auto" in css
    assert "innerHTML" not in js
    verdict = js[js.index("function releaseVerdict") : js.index("function cellText")]
    assert verdict.index("已過期") < verdict.index("已放行")
    assert verdict.index("已封鎖") < verdict.index("已放行")
    assert "/api/release/events" in js
    assert "/api/release/approvals" in js
    assert "/api/commerce/snapshots" in js


def test_legacy_snapshot_quarantine_and_explicit_assignment(client: TestClient, platform) -> None:  # noqa: ANN001
    import json

    store = platform.providers.fx
    # Pre-upgrade file: the old import endpoint kept caller-supplied tenantIds, including forged ones.
    (store.root / "fx.json").write_text(
        json.dumps(
            {
                "kind": "fx",
                "items": [
                    {"snapshotId": "legacy", "price": 5},
                    {"snapshotId": "forged-b", "tenantId": TENANT_B, "price": 666},
                ],
            }
        )
    )
    store.load()
    for tenant in (TENANT_A, TENANT_B):
        body = client.get("/api/commerce/snapshots", headers=_headers(tenant)).json()
        assert body["items"] == [] and body["total"] == 0
    # New imports rewrite the file but must not promote legacy rows.
    assert client.post("/api/commerce/import", headers=_headers(TENANT_A), json={"kind": "fx", "rows": [{"snapshotId": "new-a"}]}).status_code == 200
    assert not client.get("/api/commerce/snapshots", headers=_headers(TENANT_B)).json()["items"]
    # Pin `at`: the response echoes it, and a wall-clock timestamp can itself contain "666".
    leak = client.get("/api/commerce/snapshots", params={"at": "2026-11-20T00:00:00+00:00"}, headers=_headers(TENANT_B))
    assert leak.status_code == 200 and leak.json()["at"] == "2026-11-20T00:00:00+00:00"
    assert "666" not in leak.text and "forged-b" not in leak.text
    store.assign_legacy(["legacy"], tenant_id=TENANT_A)
    ids = {row["snapshotId"] for row in client.get("/api/commerce/snapshots", headers=_headers(TENANT_A)).json()["items"]}
    assert ids == {"legacy", "new-a"}
    assert not client.get("/api/commerce/snapshots", headers=_headers(TENANT_B)).json()["items"]


def test_same_snapshot_id_is_isolated_by_tenant(client: TestClient) -> None:
    for tenant, price in ((TENANT_A, 1), (TENANT_B, 2)):
        response = client.post("/api/commerce/import", headers=_headers(tenant), json={"kind": "fx", "rows": [{"snapshotId": "same", "price": price}]})
        assert response.status_code == 200
    for tenant, price in ((TENANT_A, 1), (TENANT_B, 2)):
        rows = client.get("/api/commerce/snapshots", headers=_headers(tenant)).json()["items"]
        assert len(rows) == 1 and rows[0]["price"] == price


def test_snapshot_api_timezone_and_date_boundaries(client: TestClient) -> None:
    response = client.post("/api/commerce/import", headers=_headers(TENANT_A), json={"kind": "fx", "rows": [{"snapshotId": "date", "effectiveAt": "2026-11-19T10:00:00+08:00", "expiresAt": "2026-11-19"}]})
    assert response.status_code == 200
    for at, expected in (("2026-11-19T03:00:00+00:00", 1), ("2026-11-20T00:00:00Z", 0)):
        assert client.get("/api/commerce/snapshots", params={"at": at}, headers=_headers(TENANT_A)).json()["total"] == expected
    assert client.get("/api/commerce/snapshots", params={"at": "0001-01-01T00:00:00+23:00"}, headers=_headers(TENANT_A)).status_code == 422
