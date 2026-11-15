"""Supplier quote import and comparison. No FX conversion, no live provider."""

from __future__ import annotations

import json
from typing import Any

import pytest

from fox3d.supplier import SupplierQuoteService


def _quote(svc: SupplierQuoteService, quote_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "quoteId": quote_id,
        "supplierId": quote_id,
        "material": 100,
        "processing": 0,
        "setup": 0,
        "packaging": 0,
        "freight": 0,
        "moq": 1,
        "leadTimeDays": 5,
        "currency": "TWD",
        "validUntil": "9999-12-31",
    }
    row.update(overrides)
    return svc.import_quote(row, source="MANUAL")


def _stored(svc: SupplierQuoteService) -> dict[str, str]:
    return {qid: quote["quoteHash"] for qid, quote in svc.quotes.items()}


def test_compare_rejects_currency_mismatch() -> None:
    svc = SupplierQuoteService()
    twd = _quote(svc, "twd", material=300, currency="TWD")
    usd = _quote(svc, "usd", material=10, currency="USD")
    fx = svc.import_fx({"pair": "USD/TWD", "rate": 32.1}, source="MANUAL")
    with pytest.raises(ValueError, match="^currency_mismatch$") as caught:
        svc.compare(
            [twd["quoteId"], usd["quoteId"]],
            release_hash="rel-1",
            quantity=1,
            fx_snapshot_id=fx["snapshotId"],
        )
    assert str(caught.value) == "currency_mismatch"
    assert svc.comparisons == {}

    eur = _quote(svc, "eur", material=8, currency="EUR")
    with pytest.raises(ValueError, match="^currency_mismatch$"):
        svc.compare([twd["quoteId"], usd["quoteId"], eur["quoteId"]], release_hash="rel-1", quantity=1)

    same = SupplierQuoteService()
    high = _quote(same, "high", material=300, currency=" twd ")
    low = _quote(same, "low", material=10, currency="TWD")
    fx_same = same.import_fx({"pair": "USD/TWD", "rate": 32.1}, source="MANUAL")
    compared = same.compare(
        [high["quoteId"], low["quoteId"]],
        release_hash="rel-1",
        quantity=1,
        fx_snapshot_id=fx_same["snapshotId"],
    )
    assert compared["winner"] == "low"
    assert compared["ranked"][0]["landed"] == 10
    assert compared["fxSnapshotId"] == fx_same["snapshotId"]
    assert compared["fxSource"] == "MANUAL"


def test_same_currency_ranks_by_landed_lead_moq_and_validity() -> None:
    svc = SupplierQuoteService()
    cheap = _quote(svc, "cheap", material=100)
    dear = _quote(svc, "dear", material=300)
    by_landed = svc.compare([dear["quoteId"], cheap["quoteId"]], release_hash="r", quantity=10)
    assert [row["quoteId"] for row in by_landed["ranked"]] == ["cheap", "dear"]
    assert by_landed["winner"] == "cheap"
    assert by_landed["ranked"][0]["components"]["landed"] < by_landed["ranked"][1]["components"]["landed"]

    svc = SupplierQuoteService()
    fast = _quote(svc, "fast", leadTimeDays=3)
    slow = _quote(svc, "slow", leadTimeDays=14)
    by_lead = svc.compare([slow["quoteId"], fast["quoteId"]], release_hash="r", quantity=10)
    assert [row["quoteId"] for row in by_lead["ranked"]] == ["fast", "slow"]
    assert by_lead["ranked"][0]["leadTimeDays"] < by_lead["ranked"][1]["leadTimeDays"]

    svc = SupplierQuoteService()
    flexible = _quote(svc, "flex", moq=1)
    batch = _quote(svc, "batch", moq=50)
    by_moq = svc.compare([batch["quoteId"], flexible["quoteId"]], release_hash="r", quantity=10)
    assert [row["quoteId"] for row in by_moq["ranked"]] == ["flex", "batch"]
    assert by_moq["ranked"][0]["moqRisk"] == 0
    assert by_moq["ranked"][1]["moqRisk"] == 1

    svc = SupplierQuoteService()
    fresh = _quote(svc, "fresh", validUntil="9999-12-31")
    expired = _quote(svc, "old", validUntil="1999-12-31")
    by_validity = svc.compare([expired["quoteId"], fresh["quoteId"]], release_hash="r", quantity=10)
    assert [row["quoteId"] for row in by_validity["ranked"]] == ["fresh", "old"]
    assert by_validity["ranked"][0]["validityRisk"] == 0
    assert by_validity["ranked"][1]["validityRisk"] == 1


def test_expired_quote_validity_risk_is_one() -> None:
    svc = SupplierQuoteService()
    fresh = _quote(svc, "fresh", validUntil="9999-12-31")
    expired = _quote(svc, "expired", validUntil="1999-12-31")
    compared = svc.compare([fresh["quoteId"], expired["quoteId"]], release_hash="r", quantity=10)
    by_id = {row["quoteId"]: row for row in compared["ranked"]}
    assert by_id["expired"]["validityRisk"] == 1
    assert by_id["fresh"]["validityRisk"] == 0
    assert compared["winner"] == "fresh"


def test_comparison_stale_four_conditions() -> None:
    svc = SupplierQuoteService()
    quote = _quote(svc, "a")
    fx = svc.import_fx({"pair": "USD/TWD", "rate": 32.0}, source="MANUAL")
    compared = svc.compare(
        [quote["quoteId"]],
        release_hash="rel-1",
        quantity=10,
        fx_snapshot_id=fx["snapshotId"],
    )
    same = dict(release_hash="rel-1", quantity=10, fx_snapshot_id=fx["snapshotId"])
    assert svc.comparison_stale(compared, **same, material_requirements_hash="bom-1", bound_material_hash="bom-1") is False
    assert svc.comparison_stale(compared, release_hash="rel-2", quantity=10, fx_snapshot_id=fx["snapshotId"]) is True
    assert svc.comparison_stale(compared, release_hash="rel-1", quantity=11, fx_snapshot_id=fx["snapshotId"]) is True
    assert svc.comparison_stale(compared, release_hash="rel-1", quantity=10, fx_snapshot_id="other-fx") is True
    assert svc.comparison_stale(
        compared,
        release_hash="rel-1",
        quantity=10,
        fx_snapshot_id=fx["snapshotId"],
        material_requirements_hash="bom-1",
        bound_material_hash="bom-2",
    ) is True


def test_live_provider_quote_raises_permission_error() -> None:
    svc = SupplierQuoteService()
    with pytest.raises(PermissionError, match="LIVE_PROVIDER"):
        svc.import_quote({"supplierId": "X", "material": 1, "quoteId": "live"}, source="LIVE_PROVIDER")
    with pytest.raises(PermissionError, match="LIVE_PROVIDER"):
        svc.import_json('[{"supplierId": "X", "material": 1, "quoteId": "live-json"}]', source="LIVE_PROVIDER")
    with pytest.raises(PermissionError, match="LIVE_PROVIDER"):
        svc.import_csv("supplierId,material,quoteId\nX,1,live-csv\n", source="LIVE_PROVIDER")
    assert svc.quotes == {}


def test_import_json_and_csv() -> None:
    svc = SupplierQuoteService()
    payload = [
        {
            "quoteId": "j1",
            "supplierId": "A",
            "material": 400,
            "processing": 100,
            "setup": 50,
            "packaging": 20,
            "freight": 40,
            "moq": 1,
            "leadTimeDays": 4,
            "currency": "TWD",
        },
        {
            "quoteId": "j2",
            "supplierId": "B",
            "material": 350,
            "processing": 140,
            "setup": 200,
            "packaging": 20,
            "freight": 80,
            "moq": 50,
            "leadTimeDays": 14,
            "currency": "TWD",
        },
    ]
    imported = svc.import_json(json.dumps({"quotes": payload}), source="IMPORTED")
    assert [row["quoteId"] for row in imported] == ["j1", "j2"]
    assert imported[0]["source"] == "IMPORTED"
    assert imported[0]["liveProvider"] is False
    assert imported[0]["normalized"]["landed"] == 610

    fresh = SupplierQuoteService()
    listed = fresh.import_json(json.dumps(payload), source="IMPORTED")
    assert [row["quoteId"] for row in listed] == ["j1", "j2"]
    assert listed[0]["normalized"]["landed"] == 610

    csv_text = "\n".join(
        [
            "quoteId,supplierId,material,processing,setup,packaging,freight,moq,leadTimeDays,currency,validUntil",
            "c1,C,410,90,40,25,35,5,6,TWD,9999-12-31",
            "c2,D,100,0,0,0,0,1,4,TWD,9999-12-31",
        ]
    )
    csv_rows = fresh.import_csv(csv_text, source="IMPORTED")
    assert [row["quoteId"] for row in csv_rows] == ["c1", "c2"]
    assert csv_rows[0]["normalized"]["landed"] == 568
    assert csv_rows[1]["normalized"]["landed"] == 100
    assert csv_rows[1]["normalized"]["currency"] == "TWD"
    compared = fresh.compare(["j1", "j2", "c1", "c2"], release_hash="rel", quantity=10)
    assert compared["winner"] == "c2"
    assert all(row["liveProvider"] is False for row in compared["ranked"])


def test_import_quote_does_not_overwrite_existing_quote_id() -> None:
    svc = SupplierQuoteService()
    first = svc.import_quote(
        {"quoteId": "dup", "supplierId": "A", "material": 80, "currency": "TWD"},
        source="MANUAL",
    )
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_quote(
            {"quoteId": "dup", "supplierId": "B", "material": -500, "currency": "USD"},
            source="IMPORTED",
        )
    assert list(svc.quotes) == ["dup"]
    assert svc.quotes["dup"]["supplierId"] == "A"
    assert svc.quotes["dup"]["raw"]["material"] == 80
    assert svc.quotes["dup"]["quoteHash"] == first["quoteHash"]

    before = _stored(svc)
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_json(
            json.dumps(
                [
                    {"quoteId": "new", "supplierId": "C", "material": 5, "currency": "TWD"},
                    {"quoteId": "new", "supplierId": "D", "material": 9, "currency": "TWD"},
                ]
            ),
            source="IMPORTED",
        )
    assert "new" not in svc.quotes
    assert _stored(svc) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("material", -500),
        ("material", "-500"),
        ("material", float("nan")),
        ("material", float("inf")),
        ("material", float("-inf")),
        ("material", "nan"),
        ("materialCost", -1),
        ("processing", -1),
        ("labor", float("nan")),
        ("setup", -0.01),
        ("toolingCost", float("inf")),
        ("packaging", -2),
        ("freight", float("-inf")),
        ("shipping", -3),
    ],
)
def test_normalize_rejects_negative_or_non_finite_costs(field: str, value: float | str) -> None:
    svc = SupplierQuoteService()
    with pytest.raises(ValueError, match="invalid_cost"):
        svc.import_quote({"supplierId": "A", "quoteId": "bad", field: value, "currency": "TWD"}, source="MANUAL")
    assert "bad" not in svc.quotes


@pytest.mark.parametrize("moq", [0, -1, 0.5, "0", float("nan"), float("inf"), float("-inf")])
def test_normalize_rejects_moq_below_one(moq: float | str) -> None:
    svc = SupplierQuoteService()
    with pytest.raises(ValueError, match="invalid_moq"):
        svc.import_quote({"supplierId": "A", "quoteId": "bad", "material": 10, "moq": moq}, source="MANUAL")
    assert "bad" not in svc.quotes


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("leadTimeDays", -1),
        ("leadTimeDays", -0.5),
        ("leadTime", -2),
        ("leadTimeDays", float("nan")),
        ("leadTimeDays", float("inf")),
        ("leadTime", float("-inf")),
    ],
)
def test_normalize_rejects_negative_or_non_finite_lead_time(field: str, value: float) -> None:
    svc = SupplierQuoteService()
    with pytest.raises(ValueError, match="invalid_lead_time"):
        svc.import_quote({"supplierId": "A", "quoteId": "bad", "material": 10, field: value}, source="MANUAL")
    assert "bad" not in svc.quotes


def test_zero_cost_and_zero_lead_time_are_accepted() -> None:
    svc = SupplierQuoteService()
    quote = svc.import_quote(
        {
            "quoteId": "zero",
            "supplierId": "A",
            "material": 0,
            "processing": 0,
            "setup": 0,
            "packaging": 0,
            "freight": 0,
            "moq": 1,
            "leadTimeDays": 0,
            "currency": "TWD",
        },
        source="MANUAL",
    )
    assert quote["normalized"]["landed"] == 0
    assert quote["normalized"]["leadTimeDays"] == 0
    assert quote["normalized"]["moq"] == 1
    compared = svc.compare([quote["quoteId"]], release_hash="r", quantity=1)
    assert compared["winner"] == "zero"
    assert compared["ranked"][0]["validityRisk"] == 0


def test_json_batch_failure_leaves_quotes_unchanged_and_retry_succeeds() -> None:
    svc = SupplierQuoteService()
    kept = _quote(svc, "kept", material=80)
    before = _stored(svc)
    assert svc.import_json("[]", source="IMPORTED") == []
    assert svc.import_json("{}", source="IMPORTED") == []
    assert _stored(svc) == before

    duplicate = json.dumps(
        [
            {"quoteId": "a", "supplierId": "A", "material": 10, "moq": 1, "currency": "TWD"},
            {"quoteId": "a", "supplierId": "B", "material": 12, "moq": 1, "currency": "TWD"},
        ]
    )
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_json(duplicate, source="IMPORTED")
    assert _stored(svc) == before
    assert "a" not in svc.quotes

    conflict = json.dumps(
        [
            {"quoteId": "fresh", "supplierId": "F", "material": 11, "moq": 1, "currency": "TWD"},
            {"quoteId": "kept", "supplierId": "Z", "material": 9, "moq": 1, "currency": "TWD"},
        ]
    )
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_json(conflict, source="IMPORTED")
    assert _stored(svc) == before
    assert "fresh" not in svc.quotes
    assert svc.quotes["kept"]["supplierId"] == "kept"

    bad_cost = json.dumps(
        [
            {"quoteId": "ok", "supplierId": "O", "material": 15, "moq": 1, "currency": "TWD"},
            {"quoteId": "bad", "supplierId": "B", "material": -1, "moq": 1, "currency": "TWD"},
        ]
    )
    with pytest.raises(ValueError, match="invalid_cost"):
        svc.import_json(bad_cost, source="IMPORTED")
    assert _stored(svc) == before
    assert "ok" not in svc.quotes

    for moq in ("1.9", 1.9):
        fractional = json.dumps(
            [
                {"quoteId": "ok", "supplierId": "O", "material": 15, "moq": 1, "currency": "TWD"},
                {"quoteId": "frac", "supplierId": "P", "material": 16, "moq": moq, "currency": "TWD"},
            ]
        )
        with pytest.raises(ValueError, match="invalid_moq"):
            svc.import_json(fractional, source="IMPORTED")
        assert _stored(svc) == before
        assert "ok" not in svc.quotes
        assert "frac" not in svc.quotes

    with pytest.raises(json.JSONDecodeError):
        svc.import_json("{", source="IMPORTED")
    assert _stored(svc) == before

    fixed = json.dumps(
        [
            {"quoteId": "a", "supplierId": "A", "material": 10, "moq": 1, "currency": "TWD"},
            {"quoteId": "b", "supplierId": "B", "material": 12, "moq": 2, "currency": "TWD"},
        ]
    )
    imported = svc.import_json(fixed, source="IMPORTED")
    assert [row["quoteId"] for row in imported] == ["a", "b"]
    assert svc.quotes["kept"]["quoteHash"] == kept["quoteHash"]
    assert svc.quotes["a"]["normalized"]["moq"] == 1
    assert svc.quotes["b"]["normalized"]["moq"] == 2
    compared = svc.compare(["b"], release_hash="r", quantity=1)
    assert compared["ranked"][0]["moq"] == 2
    assert compared["ranked"][0]["moqRisk"] == 1

    stored = _stored(svc)
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_json(fixed, source="IMPORTED")
    assert _stored(svc) == stored

    overlap = json.dumps(
        [
            {"quoteId": "c", "supplierId": "C", "material": 7, "moq": 1, "currency": "TWD"},
            {"quoteId": "a", "supplierId": "Z", "material": 8, "moq": 1, "currency": "TWD"},
        ]
    )
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_json(overlap, source="IMPORTED")
    assert "c" not in svc.quotes
    assert svc.quotes["a"]["supplierId"] == "A"
    assert svc.quotes["kept"]["quoteHash"] == kept["quoteHash"]


def test_csv_batch_failure_leaves_quotes_unchanged_and_retry_succeeds() -> None:
    svc = SupplierQuoteService()
    kept = _quote(svc, "kept", material=80)
    before = _stored(svc)
    header = "quoteId,supplierId,material,processing,setup,packaging,freight,moq,leadTimeDays,currency"
    assert svc.import_csv(header + "\n", source="IMPORTED") == []
    assert _stored(svc) == before

    def csv_text(*lines: str) -> str:
        return "\n".join((header, *lines)) + "\n"

    duplicate = csv_text(
        "a,A,10,0,0,0,0,1,4,TWD",
        "a,B,12,0,0,0,0,1,4,TWD",
    )
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_csv(duplicate, source="IMPORTED")
    assert _stored(svc) == before
    assert "a" not in svc.quotes

    conflict = csv_text(
        "fresh,F,11,0,0,0,0,1,4,TWD",
        "kept,Z,9,0,0,0,0,1,4,TWD",
    )
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_csv(conflict, source="IMPORTED")
    assert _stored(svc) == before
    assert "fresh" not in svc.quotes
    assert svc.quotes["kept"]["raw"]["material"] == 80

    bad_cost = csv_text(
        "ok,O,15,0,0,0,0,1,4,TWD",
        "bad,B,-1,0,0,0,0,1,4,TWD",
    )
    with pytest.raises(ValueError, match="invalid_cost"):
        svc.import_csv(bad_cost, source="IMPORTED")
    assert _stored(svc) == before
    assert "ok" not in svc.quotes

    fractional = csv_text(
        "ok,O,15,0,0,0,0,1,4,TWD",
        "frac,P,16,0,0,0,0,1.9,4,TWD",
    )
    with pytest.raises(ValueError, match="invalid_moq"):
        svc.import_csv(fractional, source="IMPORTED")
    assert _stored(svc) == before
    assert "ok" not in svc.quotes
    assert "frac" not in svc.quotes

    fixed = csv_text(
        "a,A,10,0,0,0,0,1,4,TWD",
        "b,B,12,0,0,0,0,2,4,TWD",
    )
    imported = svc.import_csv(fixed, source="IMPORTED")
    assert [row["quoteId"] for row in imported] == ["a", "b"]
    assert svc.quotes["kept"]["quoteHash"] == kept["quoteHash"]
    assert svc.quotes["a"]["normalized"]["moq"] == 1
    assert svc.quotes["b"]["normalized"]["moq"] == 2
    compared = svc.compare(["a", "b"], release_hash="r", quantity=1)
    by_id = {row["quoteId"]: row for row in compared["ranked"]}
    assert by_id["a"]["moqRisk"] == 0
    assert by_id["b"]["moq"] == 2
    assert by_id["b"]["moqRisk"] == 1

    stored = _stored(svc)
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_csv(fixed, source="IMPORTED")
    assert _stored(svc) == stored

    overlap = csv_text(
        "c,C,7,0,0,0,0,1,4,TWD",
        "a,Z,8,0,0,0,0,1,4,TWD",
    )
    with pytest.raises(ValueError, match="duplicate_quote_id"):
        svc.import_csv(overlap, source="IMPORTED")
    assert "c" not in svc.quotes
    assert svc.quotes["a"]["supplierId"] == "A"
    assert svc.quotes["kept"]["quoteHash"] == kept["quoteHash"]


@pytest.mark.parametrize("moq", ["1.9", 1.9, "2.5", 2.5, "1.0", "2.0", True, False])
def test_non_integer_moq_is_rejected_and_compare_keeps_real_risk(moq: object) -> None:
    svc = SupplierQuoteService()
    with pytest.raises(ValueError, match="invalid_moq"):
        svc.import_quote(
            {"supplierId": "A", "quoteId": "bad", "material": 10, "moq": moq, "currency": "TWD"},
            source="MANUAL",
        )
    assert "bad" not in svc.quotes
    assert svc.comparisons == {}

    # Quantity 1 would have looked compliant if moq "1.9" had been truncated to 1.
    above = _quote(svc, "above", moq=2)
    exact = _quote(svc, "exact", moq="1")
    compared = svc.compare([above["quoteId"], exact["quoteId"]], release_hash="r", quantity=1)
    by_id = {row["quoteId"]: row for row in compared["ranked"]}
    assert by_id["above"]["moq"] == 2
    assert by_id["above"]["moqRisk"] == 1
    assert by_id["exact"]["moq"] == 1
    assert by_id["exact"]["moqRisk"] == 0
    assert "bad" not in {row["quoteId"] for row in compared["ranked"]}


def test_whole_number_float_moq_keeps_integer_risk() -> None:
    svc = SupplierQuoteService()
    one = _quote(svc, "one", moq=1.0)
    two = _quote(svc, "two", moq=2.0)
    assert one["normalized"]["moq"] == 1
    assert two["normalized"]["moq"] == 2
    low = svc.compare(["one", "two"], release_hash="r", quantity=1)
    by_id = {row["quoteId"]: row for row in low["ranked"]}
    assert by_id["one"]["moqRisk"] == 0
    assert by_id["two"]["moq"] == 2
    assert by_id["two"]["moqRisk"] == 1
    at_two = svc.compare(["two"], release_hash="r", quantity=2)
    assert at_two["ranked"][0]["moqRisk"] == 0
