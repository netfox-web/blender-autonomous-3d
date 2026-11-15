"""Supplier RFQ / quote comparison boundary.

No automatic purchasing. MANUAL/IMPORTED snapshots only unless a real
provider is actually connected. Reuses commerce.ProviderRegistry FX store.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from fox3d.commerce import ProviderRegistry
from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow

ALLOWED_SOURCES = frozenset({"MANUAL", "IMPORTED"})
LIVE_FORBIDDEN_UNLESS_CONNECTED = "LIVE_PROVIDER"


def _now() -> str:
    return utcnow().isoformat()


def _float_value(value: Any, *, code: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    return number


def _first_present(raw: dict[str, Any], keys: tuple[str, ...], default: Any = 0) -> Any:
    # Historical `or` chain: 0 and "" fall through to the next alias.
    for key in keys:
        candidate = raw.get(key)
        if candidate:
            return candidate
    return default


def _cost_component(raw: dict[str, Any], keys: tuple[str, ...]) -> float:
    number = _float_value(_first_present(raw, keys, 0), code="invalid_cost")
    if number < 0 or not math.isfinite(number):
        raise ValueError("invalid_cost")
    return number


def _moq_value(raw: dict[str, Any]) -> int:
    # Decimal strings used to fail int(); float() then int() truncated "1.9" to 1.
    candidate = raw.get("moq")
    if candidate is None or candidate == "":
        return 1
    if isinstance(candidate, str):
        try:
            number = int(candidate.strip(), 10)
        except ValueError as exc:
            raise ValueError("invalid_moq") from exc
    elif isinstance(candidate, bool):
        # bool subclasses int, so True would otherwise be stored as MOQ 1.
        raise ValueError("invalid_moq")
    elif isinstance(candidate, int):
        number = candidate
    elif isinstance(candidate, float):
        if not math.isfinite(candidate) or not candidate.is_integer():
            raise ValueError("invalid_moq")
        number = int(candidate)
    else:
        raise ValueError("invalid_moq")
    if number < 1:
        raise ValueError("invalid_moq")
    return number


def _lead_time_days(raw: dict[str, Any]) -> float:
    candidate = raw.get("leadTimeDays")
    if candidate is None or candidate == "":
        candidate = raw.get("leadTime")
    if candidate is None or candidate == "":
        candidate = 0
    number = _float_value(candidate, code="invalid_lead_time")
    if number < 0 or not math.isfinite(number):
        raise ValueError("invalid_lead_time")
    return number


def _currency_code(quote: dict[str, Any]) -> str:
    normalized = quote.get("normalized") or {}
    raw = str(normalized.get("currency") or quote.get("currency") or "TWD")
    return raw.strip().upper() or "TWD"


class SupplierCapabilityRegistry:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}

    def add(self, profile: dict[str, Any]) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "profileId": profile.get("profileId") or new_id(),
            "supplierId": profile.get("supplierId") or profile.get("name") or new_id(),
            "name": profile.get("name") or "supplier",
            "materials": list(profile.get("materials") or profile.get("supportedMaterials") or []),
            "thicknessMm": list(profile.get("thicknessMm") or profile.get("thickness") or []),
            "maxSheetMm": profile.get("maxSheetMm") or profile.get("maxWorkSize") or [2440, 1220],
            "processType": profile.get("processType") or "panel",
            "moq": int(profile.get("moq") or 1),
            "leadTimeDays": float(profile.get("leadTimeDays") or profile.get("leadTime") or 7),
            "setupCost": float(profile.get("setupCost") or profile.get("toolingCost") or 0),
            "toolingCost": float(profile.get("toolingCost") or 0),
            "currency": profile.get("currency") or "TWD",
            "location": profile.get("location") or "",
            "shippingClass": profile.get("shippingClass") or "standard",
            "validFrom": profile.get("validFrom") or _now(),
            "validUntil": profile.get("validUntil") or profile.get("validity") or "9999-12-31",
            "source": profile.get("source") or "MANUAL",
            "liveProvider": False,
        }
        rec["profileHash"] = stable_hash({k: rec[k] for k in rec if k != "profileHash"})
        self.profiles[rec["profileId"]] = rec
        return rec

    def list(self) -> list[dict[str, Any]]:
        return list(self.profiles.values())


class SupplierQuoteService:
    def __init__(self, providers: ProviderRegistry | None = None) -> None:
        self.capabilities = SupplierCapabilityRegistry()
        self.providers = providers or ProviderRegistry()
        self.quotes: dict[str, dict[str, Any]] = {}
        self.comparisons: dict[str, dict[str, Any]] = {}
        self.rfqs: dict[str, dict[str, Any]] = {}

    def rfq_from_release(self, release: dict[str, Any], *, quantity: int = 1) -> dict[str, Any]:
        snap = release.get("snapshot") or {}
        rfq: dict[str, Any] = {
            "rfqId": new_id(),
            "releaseId": release.get("releaseId"),
            "releaseHash": release.get("releaseHash"),
            "tenantId": release.get("tenantId"),
            "productId": release.get("productId"),
            "productFamily": release.get("productFamily"),
            "quantity": int(quantity),
            "bomHash": release.get("bomHash"),
            "materialSnapshotHash": release.get("materialSnapshotHash"),
            "engineeringHash": release.get("engineeringHash"),
            "sentExternally": False,
            "liveProvider": False,
            "createdAt": _now(),
            "requirements": {
                "sheetSku": (snap.get("nesting") or {}).get("sheetSku"),
                "thickness": (snap.get("nesting") or {}).get("thickness") or (snap.get("sheet") or {}).get("thickness"),
                "family": release.get("productFamily"),
            },
        }
        rfq["rfqHash"] = stable_hash({k: rfq[k] for k in rfq if k not in {"rfqId", "rfqHash"}})
        self.rfqs[rfq["rfqId"]] = rfq
        return rfq

    def _build_quote(
        self,
        row: dict[str, Any],
        *,
        source: str,
        raw: str | None,
        seen: set[Any],
    ) -> dict[str, Any]:
        if source not in ALLOWED_SOURCES:
            if source == LIVE_FORBIDDEN_UNLESS_CONNECTED:
                raise PermissionError("LIVE_PROVIDER quotes require a connected provider; none registered")
            raise ValueError(source)
        raw_text = raw if raw is not None else json.dumps(row, sort_keys=True, default=str)
        quote_id = row.get("quoteId") or new_id()
        if quote_id in self.quotes or quote_id in seen:
            raise ValueError("duplicate_quote_id")
        rec: dict[str, Any] = {
            "quoteId": quote_id,
            "supplierId": row.get("supplierId") or row.get("supplier") or "unknown",
            "source": source,
            "importedAt": _now(),
            "effectiveAt": row.get("effectiveAt") or _now(),
            "validUntil": row.get("validUntil") or row.get("validTo") or "9999-12-31",
            "currency": row.get("currency") or "TWD",
            "rawSourceHash": stable_hash(raw_text),
            "raw": row,
            "liveProvider": False,
            "truthLabel": source,
        }
        rec["normalized"] = self.normalize(rec)
        rec["quoteHash"] = stable_hash({k: rec[k] for k in rec if k not in {"quoteId", "quoteHash"}})
        return rec

    def import_quote(self, row: dict[str, Any], *, source: str, raw: str | None = None) -> dict[str, Any]:
        rec = self._build_quote(row, source=source, raw=raw, seen=set())
        self.quotes[rec["quoteId"]] = rec
        return rec

    def _import_batch(self, rows: list[tuple[dict[str, Any], str]], *, source: str) -> list[dict[str, Any]]:
        # Validate the whole batch, including ids already stored and repeated in this batch,
        # before any quote is inserted. A later duplicate or field error leaves quotes unchanged.
        pending: list[dict[str, Any]] = []
        seen: set[Any] = set()
        for row, raw in rows:
            rec = self._build_quote(row, source=source, raw=raw, seen=seen)
            seen.add(rec["quoteId"])
            pending.append(rec)
        if not pending:
            return []
        staged = dict(self.quotes)
        for rec in pending:
            staged[rec["quoteId"]] = rec
        self.quotes = staged
        return pending

    def import_json(self, text: str, *, source: str) -> list[dict[str, Any]]:
        payload = json.loads(text)
        rows = payload if isinstance(payload, list) else payload.get("items") or payload.get("quotes") or []
        prepared = [(dict(r), json.dumps(r, sort_keys=True, default=str)) for r in rows]
        return self._import_batch(prepared, source=source)

    def import_csv(self, text: str, *, source: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in csv.DictReader(io.StringIO(text))]
        prepared = [(row, csv.writer.__doc__ and ",".join(row.values()) or str(row)) for row in rows]
        return self._import_batch(prepared, source=source)

    def import_fx(self, row: dict[str, Any], *, source: str) -> dict[str, Any]:
        if source not in ALLOWED_SOURCES:
            raise PermissionError("FX remains MANUAL/IMPORTED unless a live FxRateProvider is connected")
        return self.providers.import_rows(self.providers.fx, [row], source=source)[0]

    def normalize(self, quote: dict[str, Any]) -> dict[str, Any]:
        raw = quote.get("raw") or quote
        material = _cost_component(raw, ("material", "materialCost"))
        processing = _cost_component(raw, ("processing", "labor"))
        setup = _cost_component(raw, ("setup", "setupCost", "tooling", "toolingCost"))
        packaging = _cost_component(raw, ("packaging", "packagingCost"))
        freight = _cost_component(raw, ("freight", "shipping"))
        moq = _moq_value(raw)
        lead = _lead_time_days(raw)
        qty = max(int(raw.get("quantity") or moq or 1), 1)
        unit = (material + processing + packaging) + (setup / qty) + freight
        if unit < 0 or not math.isfinite(unit):
            raise ValueError("invalid_cost")
        return {
            "material": round(material, 2),
            "processing": round(processing, 2),
            "setupTooling": round(setup, 2),
            "packaging": round(packaging, 2),
            "freight": round(freight, 2),
            "moq": moq,
            "leadTimeDays": lead,
            "currency": quote.get("currency") or raw.get("currency") or "TWD",
            "landed": round(unit, 2),
            "source": quote.get("source") or "MANUAL",
            "sourceHash": quote.get("rawSourceHash"),
            "rawSnapshotId": quote.get("quoteId"),
            "liveProvider": False,
        }

    def compare(
        self,
        quote_ids: list[str],
        *,
        release_hash: str,
        quantity: int,
        fx_snapshot_id: str | None = None,
        weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        selected = [(qid, self.quotes[qid]) for qid in quote_ids]
        # Record fx_snapshot_id only. Do not convert; mixed currencies are refused.
        if len({_currency_code(q) for _, q in selected}) > 1:
            raise ValueError("currency_mismatch")
        w = {"landed": 0.5, "lead": 0.25, "moq": 0.15, "risk": 0.1, **(weights or {})}
        rows = []
        for qid, q in selected:
            n = q["normalized"]
            landed = float(n["landed"])
            lead = float(n["leadTimeDays"])
            moq = int(n["moq"])
            moq_risk = 1.0 if moq > quantity else 0.0
            validity_risk = 0.0
            if str(q.get("validUntil") or "9999") < _now()[:10]:
                validity_risk = 1.0
            score = w["landed"] * landed + w["lead"] * lead * 10 + w["moq"] * moq_risk * 100 + w["risk"] * validity_risk * 100
            rows.append(
                {
                    "quoteId": qid,
                    "supplierId": q.get("supplierId"),
                    "landed": landed,
                    "leadTimeDays": lead,
                    "moq": moq,
                    "moqRisk": moq_risk,
                    "validityRisk": validity_risk,
                    "score": round(score, 4),
                    "components": {
                        "landed": round(w["landed"] * landed, 4),
                        "lead": round(w["lead"] * lead * 10, 4),
                        "moq": round(w["moq"] * moq_risk * 100, 4),
                        "risk": round(w["risk"] * validity_risk * 100, 4),
                    },
                    "source": q.get("source"),
                    "truthLabel": q.get("truthLabel") or q.get("source"),
                    "liveProvider": False,
                }
            )
        rows.sort(key=lambda r: (r["score"], r["landed"], r["leadTimeDays"]))
        fx = None
        if fx_snapshot_id:
            fx = next((row for row in self.providers.fx.active() if row["snapshotId"] == fx_snapshot_id), None)
            if fx and fx.get("source") == "LIVE_PROVIDER" and not self.providers.live.get("FxRateProvider"):
                raise PermissionError("static FX fixture cannot be labelled LIVE_PROVIDER")
        cmp: dict[str, Any] = {
            "comparisonId": new_id(),
            "releaseHash": release_hash,
            "quantity": int(quantity),
            "fxSnapshotId": fx_snapshot_id,
            "fxSource": (fx or {}).get("source") or "NONE",
            "ranked": rows,
            "winner": rows[0]["quoteId"] if rows else None,
            "stale": False,
            "createdAt": _now(),
            "explainable": True,
        }
        cmp["comparisonHash"] = stable_hash({k: cmp[k] for k in ("releaseHash", "quantity", "fxSnapshotId", "winner")})
        self.comparisons[cmp["comparisonId"]] = cmp
        return cmp

    def comparison_stale(
        self,
        comparison: dict[str, Any],
        *,
        release_hash: str,
        quantity: int,
        fx_snapshot_id: str | None = None,
        material_requirements_hash: str | None = None,
        bound_material_hash: str | None = None,
    ) -> bool:
        if comparison.get("releaseHash") != release_hash:
            return True
        if int(comparison.get("quantity") or 0) != int(quantity):
            return True
        if (comparison.get("fxSnapshotId") or None) != (fx_snapshot_id or None):
            return True
        if material_requirements_hash and bound_material_hash and material_requirements_hash != bound_material_hash:
            return True
        return False
