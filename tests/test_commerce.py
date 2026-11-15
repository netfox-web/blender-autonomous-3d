import json

import pytest

from fox3d.commerce import ProviderRegistry, SnapshotStore, mixed_landed_cost, quote_binding


@pytest.mark.parametrize(
    ("kind", "provider"),
    [
        ("material", "SupplierPriceProvider"),
        ("hardware", "HardwarePriceProvider"),
        ("packaging", "PackagingPriceProvider"),
        ("logistics", "LogisticsRateProvider"),
        ("fx", "FxRateProvider"),
    ],
)
def test_live_import_requires_matching_connection(kind, provider):
    registry = ProviderRegistry()
    store = getattr(registry, kind)
    with pytest.raises(PermissionError):
        registry.import_rows(store, [{"rate": 31}], source="LIVE_PROVIDER")
    assert store.items == {}
    # A different connected provider must not authorize this kind.
    other = next(name for name in registry.live if name != provider)
    registry.live[other] = True
    with pytest.raises(PermissionError):
        registry.import_rows(store, [{"rate": 31}], source="LIVE_PROVIDER")
    registry.live[provider] = True
    assert registry.import_rows(store, [{"rate": 31}], source="LIVE_PROVIDER")[0]["liveProvider"] is True


def test_unknown_store_kind_cannot_claim_live():
    registry = ProviderRegistry()
    with pytest.raises(PermissionError):
        registry.import_rows(SnapshotStore(kind="unknown"), [{}], source="LIVE_PROVIDER")


@pytest.mark.parametrize("source", ["MANUAL", "IMPORTED"])
def test_csv_and_json_import_and_persistence(tmp_path, source):
    registry = ProviderRegistry(tmp_path)
    csv_rows = registry.import_csv(registry.fx, "pair,rate\nUSD/TWD,31\n", source=source)
    json_rows = registry.import_json(registry.fx, json.dumps({"items": [{"pair": "EUR/TWD", "rate": 34}]}), source=source)
    assert csv_rows[0]["rate"] == "31"
    assert json_rows[0]["rate"] == 34
    assert all(row["source"] == source and row["liveProvider"] is False for row in csv_rows + json_rows)
    assert ProviderRegistry(tmp_path).fx.items == registry.fx.items


def test_active_includes_effective_and_expiry_boundaries():
    store = SnapshotStore(kind="fx")
    row = store.add({"effectiveAt": "2026-01-10", "expiresAt": "2026-01-20"}, source="MANUAL")
    for at, expected in [("2026-01-09", []), ("2026-01-10", [row]), ("2026-01-20", [row]), ("2026-01-21", [])]:
        assert store.active(at=at) == expected


def test_mixed_landed_cost_requires_explicit_live_connection():
    components = [{"amount": 31, "source": "LIVE_PROVIDER"}, {"amount": 2, "source": "MANUAL"}]
    disconnected = mixed_landed_cost(components)
    assert disconnected["components"][0]["source"] == "CONFIG_ESTIMATE"
    assert disconnected["sources"] == ["CONFIG_ESTIMATE", "MANUAL"]
    assert disconnected["liveProviderReady"] is False
    connected = mixed_landed_cost(components, live_connected=True)
    assert connected["components"][0]["source"] == "LIVE_PROVIDER"
    assert connected["liveProviderReady"] is True
    assert connected["total"] == disconnected["total"] == 33
    assert components[0]["source"] == "LIVE_PROVIDER"


def test_quote_binding_hash_stable_for_same_content():
    entity = {"engineeringHash": "engineering", "bom": {"bomHash": "bom"}, "nesting": {"nestingHash": "nesting"}}
    args = {"snapshot_ids": ["snapshot"], "valid_from": "2026-01-01", "valid_to": "2026-12-31"}
    first = quote_binding(entity, **args)
    second = quote_binding(entity, **args)
    assert first["quoteId"] != second["quoteId"]
    assert first["quoteBindingHash"] == second["quoteBindingHash"]
    assert first["quoteBindingHash"] != quote_binding(entity, **{**args, "snapshot_ids": ["other"]})["quoteBindingHash"]
