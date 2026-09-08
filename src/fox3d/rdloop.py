"""Closed-loop R&D / outcome import / ranking. No CRM/ERP."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.safety import evaluate_product


OUTCOME_FIELDS = ("skuId", "productVersion", "timeWindow", "source", "sales", "traffic", "margin", "returns", "feedback")


def outcome_schema() -> dict[str, Any]:
    return {"fields": list(OUTCOME_FIELDS), "crm": False, "erp": False}


class DemandRegistryV2:
    def __init__(self) -> None:
        self.providers: dict[str, str] = {"default": "UNAVAILABLE"}

    def register(self, name: str, label: str) -> None:
        if label not in {"LIVE_PROVIDER", "IMPORTED", "MANUAL", "MOCK", "UNAVAILABLE"}:
            raise ValueError(label)
        self.providers[name] = label

    def signal(self, *, kind: str, name: str = "default") -> dict[str, Any]:
        label = self.providers.get(name) or "UNAVAILABLE"
        live = label == "LIVE_PROVIDER"
        return {
            "kind": kind,
            "provider": name,
            "label": label,
            "market": "VERIFIED" if live else "MARKET_UNVERIFIED",
            "score": None if not live else 0.5,
        }


def import_outcomes(text: str, *, fmt: str = "json", source: str) -> list[dict[str, Any]]:
    if source not in {"IMPORTED", "MANUAL", "FIXTURE"}:
        raise ValueError(source)
    if fmt == "csv":
        rows = [dict(r) for r in csv.DictReader(io.StringIO(text))]
    else:
        payload = json.loads(text)
        rows = payload if isinstance(payload, list) else payload.get("items") or []
    out = []
    for r in rows:
        rec = {k: r.get(k) for k in OUTCOME_FIELDS}
        rec["source"] = source
        rec["realMarketData"] = source in {"IMPORTED", "MANUAL"} and source != "FIXTURE"
        if source == "FIXTURE":
            rec["realMarketData"] = False
            rec["label"] = "FIXTURE"
        rec["importedAt"] = utcnow().isoformat()
        rec["outcomeId"] = new_id()
        out.append(rec)
    return out


def experiment_lineage(*, product_version: Any, release_id: str | None, recipe_id: str | None, window: str) -> dict[str, Any]:
    rec = {
        "experimentId": new_id(),
        "productVersion": product_version,
        "publicationRelease": release_id,
        "recipeId": recipe_id,
        "outcomeWindow": window,
        "mixVersionsForbidden": True,
    }
    rec["lineageHash"] = stable_hash(rec)
    return rec


def evidence_weighted_rank(candidates: list[dict[str, Any]], outcomes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    by_sku = {str(o.get("skuId")): o for o in (outcomes or []) if o.get("realMarketData")}
    ranked = []
    for c in candidates:
        sku = str(c.get("productId") or c.get("skuId") or "")
        market = by_sku.get(sku)
        engineering = float(c.get("materialUtilization") or 0) - float(c.get("trueScrap") or 0)
        row = dict(c)
        if market:
            row["rankScore"] = 0.5 * engineering + 0.5 * float(market.get("margin") or 0)
            row["rankSource"] = "ENGINEERING+MARKET"
        else:
            row["rankScore"] = engineering
            row["rankSource"] = "ENGINEERING_MATERIAL_ONLY"
            row["market"] = "MARKET_UNVERIFIED"
        ranked.append(row)
    ranked.sort(key=lambda r: (-(r.get("rankScore") or 0), str(r.get("kind") or "")))
    return {"ranked": ranked, "marketUsed": bool(by_sku)}


def inventory_rd_v2(candidates: list[dict[str, Any]], *, safety: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = []
    for c in candidates:
        saf = (safety or {}).get(str(c.get("productId") or ""), {})
        score = (
            float(c.get("materialUtilization") or 0) * 0.25
            + (1 - float(c.get("trueScrap") or 0)) * 0.2
            + float(c.get("commonParts") or 0) * 0.1
            + (1 - float(c.get("assembly") or 0)) * 0.1
            + float(c.get("estimatedMargin") or 0) * 0.2
            - (0.3 if saf.get("veto") else 0)
        )
        out.append(
            {
                **c,
                "rdScoreV2": round(score, 4),
                "safetyVeto": bool(saf.get("veto")),
                "demand": "MOCK",
                "market": "MARKET_UNVERIFIED",
            }
        )
    out.sort(key=lambda r: -r["rdScoreV2"])
    return out


def substitution_candidates(need: dict[str, Any], snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    alts = []
    for s in snapshots:
        compatible = abs(float(s.get("thickness") or 0) - float(need.get("thickness") or 0)) < 0.5
        alts.append(
            {
                "snapshotId": s.get("snapshotId"),
                "compatible": compatible,
                "price": s.get("price"),
                "newVersionRequired": True,
                "reapprovalRequired": True,
                "immutableVersionOnChange": True,
            }
        )
    return {"need": need, "alternatives": alts, "autoSwapForbidden": True}


def kpi_read_model(platform: Any) -> dict[str, Any]:
    remnants = list(getattr(platform.remnants, "items", {}) .values()) if getattr(platform, "remnants", None) else []
    available = [r for r in remnants if r.get("status") == "available"]
    approvals = getattr(getattr(platform, "release", None), "approvals", {}) or {}
    stale = sum(1 for a in approvals.values() if a.get("stale"))
    return {
        "trueScrap": "see nesting trueWasteRatio",
        "remnantReuseCount": len([r for r in remnants if r.get("status") == "consumed"]),
        "availableRemnants": len(available),
        "approvalStale": stale,
        "labels": {
            "REAL": ["coreRender", "kdPrototype", "retailPrototype"],
            "MOCK": ["vision", "video", "demand"],
            "PARTIAL": ["osSandbox", "ar", "printPreflight"],
            "BLOCKED": ["LIVE_CNC", "LIVE_LASER", "electrical"],
            "CONFIG_ESTIMATE": ["costWithoutImport"],
        },
        "liveMachineControl": False,
        "sameAdmin": True,
    }
