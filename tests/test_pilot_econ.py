"""Unit tests for fox3d.pilot_econ.PilotEconomics (issue #389)."""

from __future__ import annotations

import pytest

from fox3d.pilot_econ import PilotEconomics


@pytest.fixture()
def econ():
    return PilotEconomics()


# ---------------------------------------------------------------- contribution_margin


def test_contribution_margin_price_zero_has_zero_ratio(econ):
    out = econ.contribution_margin(price=0, cost=10)
    assert out["contributionMargin"] == -10.0
    assert out["marginRatio"] == 0.0
    assert out["paymentProcessing"] is False


def test_contribution_margin_normal_and_negative(econ):
    out = econ.contribution_margin(price=100, cost=60)
    assert out["contributionMargin"] == 40.0
    assert out["marginRatio"] == 0.4
    loss = econ.contribution_margin(price=50, cost=75)
    assert loss["contributionMargin"] == -25.0
    assert loss["marginRatio"] == -0.5


# ---------------------------------------------------------------- break_even


def _qtys(be):
    return [row["qty"] for row in be["curve"]]


def test_break_even_qty_rounds_up_and_respects_moq(econ):
    be = econ.break_even(setup=200, tooling=100, price=50, unit_variable=20, moq=1)
    assert be["breakEvenQty"] == 10  # 300 / 30 exactly
    be = econ.break_even(setup=200, tooling=101, price=50, unit_variable=20, moq=1)
    assert be["breakEvenQty"] == 11
    be = econ.break_even(setup=200, tooling=100, price=50, unit_variable=20, moq=500)
    assert be["breakEvenQty"] == 500


@pytest.mark.parametrize("moq", [1, 5, 10, 20, 50, 100])
def test_break_even_curve_dedupes_moq_in_default_points(econ, moq):
    be = econ.break_even(setup=200, tooling=100, price=50, unit_variable=20, moq=moq)
    assert _qtys(be) == [1, 5, 10, 20, 50, 100]


def test_break_even_curve_sorted_with_custom_moq(econ):
    be = econ.break_even(setup=200, tooling=100, price=50, unit_variable=20, moq=7)
    assert _qtys(be) == [1, 5, 7, 10, 20, 50, 100]
    be = econ.break_even(setup=200, tooling=100, price=50, unit_variable=20, moq=250)
    assert _qtys(be) == [1, 5, 10, 20, 50, 100, 250]


def test_break_even_curve_values(econ):
    be = econ.break_even(setup=200, tooling=100, price=50, unit_variable=20, moq=10)
    row = {r["qty"]: r for r in be["curve"]}
    assert row[10]["unitCost"] == 50.0
    assert row[10]["unitMargin"] == 0.0
    assert row[100]["unitCost"] == 23.0
    assert row[1]["unitMargin"] == -270.0


@pytest.mark.parametrize("price,unit_variable", [(20, 20), (10, 20), (0, 5)])
def test_break_even_none_when_price_not_above_variable(econ, price, unit_variable):
    be = econ.break_even(setup=100, tooling=0, price=price, unit_variable=unit_variable, moq=1)
    assert be["breakEvenQty"] is None
    assert _qtys(be) == [1, 5, 10, 20, 50, 100]


def test_break_even_zero_moq_does_not_add_zero_row(econ):
    be = econ.break_even(setup=100, tooling=0, price=50, unit_variable=20, moq=0)
    assert _qtys(be) == [1, 5, 10, 20, 50, 100]
    assert be["breakEvenQty"] == 4


# ---------------------------------------------------------------- history_intact / freeze


def test_history_intact(econ):
    frozen = {"freezeHash": "abc", "estimatedCost": 10}
    assert econ.history_intact(frozen, "abc") is True
    assert econ.history_intact(frozen, "abd") is False
    assert econ.history_intact({}, "abc") is False
    assert econ.history_intact({}, None) is True


def test_history_intact_after_variance_does_not_mutate_frozen(econ):
    frozen = {"freezeHash": "h1", "estimatedCost": 100.0, "breakdown": {"SheetCost": 40.0}}
    snapshot = dict(frozen)
    actual = econ.import_actuals(work_order_id="wo", release_hash="r", rows={"material": 55}, source="MANUAL")
    var = econ.variance(frozen=frozen, actual=actual)
    assert var["historyUnchanged"] is True
    assert frozen == snapshot
    assert econ.history_intact(frozen, "h1") is True


def test_freeze_from_release_requires_frozen_cost(econ):
    with pytest.raises(PermissionError):
        econ.freeze_from_release({})
    src = {"frozenCost": {"freezeHash": "x"}}
    out = econ.freeze_from_release(src)
    out["freezeHash"] = "changed"
    assert src["frozenCost"]["freezeHash"] == "x"


def test_import_actuals_rejects_unknown_source(econ):
    with pytest.raises(ValueError):
        econ.import_actuals(work_order_id="wo", release_hash="r", rows={}, source="LIVE")
