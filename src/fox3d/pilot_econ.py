"""Pilot unit economics / variance loop.

Freeze cost at ManufacturingRelease approval. Do not silently recompute history.
"""

from __future__ import annotations

import json
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.rdloop import import_outcomes

CATEGORIES = ("material", "processing", "hardware", "packaging", "freight", "scrap", "rework")


def _now() -> str:
    return utcnow().isoformat()


class PilotEconomics:
    def __init__(self) -> None:
        self.actuals: dict[str, dict[str, Any]] = {}
        self.observations: list[dict[str, Any]] = []

    def freeze_from_release(self, release: dict[str, Any]) -> dict[str, Any]:
        frozen = release.get("frozenCost")
        if not frozen:
            raise PermissionError("cost freeze requires an approved ManufacturingRelease")
        return dict(frozen)

    def import_actuals(
        self,
        *,
        work_order_id: str,
        release_hash: str,
        rows: dict[str, float],
        source: str,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        if source not in {"MANUAL", "IMPORTED"}:
            raise ValueError(source)
        amounts = {k: float(rows.get(k) or 0) for k in CATEGORIES}
        rec = {
            "actualId": new_id(),
            "workOrderId": work_order_id,
            "releaseHash": release_hash,
            "batchId": batch_id,
            "amounts": amounts,
            "total": round(sum(amounts.values()), 2),
            "source": source,
            "truthLabel": source,
            "importedAt": _now(),
            "liveProvider": False,
        }
        rec["actualHash"] = stable_hash({k: rec[k] for k in rec if k not in {"actualId", "actualHash"}})
        self.actuals[rec["actualId"]] = rec
        return rec

    def variance(self, *, frozen: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
        est_total = float(frozen.get("estimatedCost") or 0)
        breakdown = frozen.get("breakdown") or {}
        mapping = {
            "material": breakdown.get("SheetCost") or breakdown.get("material") or est_total * 0.4,
            "processing": breakdown.get("ProcessingCost") or breakdown.get("processing") or est_total * 0.2,
            "hardware": breakdown.get("HardwareCost") or 0,
            "packaging": breakdown.get("PackagingCost") or breakdown.get("packaging") or 0,
            "freight": breakdown.get("freight") or 0,
            "scrap": breakdown.get("SheetWasteCost") or 0,
            "rework": 0,
        }
        by_cat = []
        for cat in CATEGORIES:
            e = float(mapping.get(cat) or 0)
            a = float((actual.get("amounts") or {}).get(cat) or 0)
            delta = a - e
            pct = (delta / e) if abs(e) > 1e-9 else (1.0 if a else 0.0)
            by_cat.append({"category": cat, "estimate": round(e, 2), "actual": round(a, 2), "delta": round(delta, 2), "pct": round(pct, 4)})
        act_total = float(actual.get("total") or 0)
        return {
            "byCategory": by_cat,
            "estimateTotal": round(est_total, 2),
            "actualTotal": round(act_total, 2),
            "delta": round(act_total - est_total, 2),
            "pct": round(((act_total - est_total) / est_total) if abs(est_total) > 1e-9 else 0.0, 4),
            "historyUnchanged": True,
            "freezeHash": frozen.get("freezeHash"),
        }

    def waste_economics(
        self,
        *,
        true_scrap_mm2: float,
        remnant_mm2: float,
        recovered_mm2: float,
        cost_per_m2: float,
        remnant_usability: float = 0.7,
        recovered_factor: float = 0.5,
    ) -> dict[str, Any]:
        scrap_m2 = float(true_scrap_mm2) / 1e6
        rem_m2 = float(remnant_mm2) / 1e6
        rec_m2 = float(recovered_mm2) / 1e6
        # recovered credit comes only from recovered remnant usage — not from remaining inventory and not from scrap
        scrap_cost = scrap_m2 * cost_per_m2
        remnant_value = rem_m2 * cost_per_m2 * float(remnant_usability)
        recovered_credit = rec_m2 * cost_per_m2 * float(recovered_factor)
        if rec_m2 - rem_m2 > 1e-9:
            raise ValueError("recovered remnant cannot exceed remnant inventory (double-credit)")
        return {
            "trueScrapCost": round(scrap_cost, 2),
            "reusableRemnantInventoryValue": round(remnant_value, 2),
            "recoveredRemnantUsageCredit": round(recovered_credit, 2),
            "netWasteCost": round(scrap_cost - recovered_credit, 2),
            "doubleCredit": False,
            "costPerM2": cost_per_m2,
            "source": "CONFIG_ESTIMATE",
        }

    def contribution_margin(self, *, price: float, cost: float) -> dict[str, Any]:
        cm = float(price) - float(cost)
        return {
            "price": round(float(price), 2),
            "cost": round(float(cost), 2),
            "contributionMargin": round(cm, 2),
            "marginRatio": round(cm / float(price), 4) if price else 0.0,
            "paymentProcessing": False,
        }

    def break_even(self, *, setup: float, tooling: float, price: float, unit_variable: float, moq: int = 1) -> dict[str, Any]:
        contrib = float(price) - float(unit_variable)
        fixed = float(setup) + float(tooling)
        qty = None if contrib <= 0 else max(int(moq), int((fixed / contrib) + 0.9999))
        curve = []
        for q in (1, 5, 10, 20, 50, 100, moq):
            unit = unit_variable + (fixed / max(int(q), 1))
            curve.append({"qty": int(q), "unitCost": round(unit, 2), "unitMargin": round(float(price) - unit, 2)})
        return {
            "breakEvenQty": qty,
            "fixed": round(fixed, 2),
            "unitVariable": round(float(unit_variable), 2),
            "price": round(float(price), 2),
            "moq": int(moq),
            "curve": curve,
            "source": "IMPORTED_QUOTE",
        }

    def rd_observation(self, *, sku_id: str, product_version: Any, window: str, metrics: dict[str, Any], source: str = "MANUAL") -> dict[str, Any]:
        row = {
            "skuId": sku_id,
            "productVersion": product_version,
            "timeWindow": window,
            "source": source,
            "sales": metrics.get("sales"),
            "traffic": metrics.get("traffic"),
            "margin": metrics.get("margin"),
            "returns": metrics.get("returns"),
            "feedback": metrics.get("feedback") or "pilot-observation",
        }
        imported = import_outcomes(json.dumps([row]), fmt="json", source=source if source in {"IMPORTED", "MANUAL"} else "MANUAL")[0]
        imported["demand"] = "MOCK"
        imported["market"] = "MARKET_UNVERIFIED"
        imported["kind"] = "observation"
        self.observations.append(imported)
        return imported

    def history_intact(self, frozen: dict[str, Any], original_hash: str) -> bool:
        return frozen.get("freezeHash") == original_hash
