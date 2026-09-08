"""Supplier RFQ / quote comparison boundary.

No automatic purchasing. MANUAL/IMPORTED snapshots only unless a real
provider is actually connected. Reuses commerce.ProviderRegistry FX store.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fox3d.commerce import ProviderRegistry
from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow

ALLOWED_SOURCES = frozenset({"MANUAL", "IMPORTED"})
LIVE_FORBIDDEN_UNLESS_CONNECTED = "LIVE_PROVIDER"


def _now() -> str:
    return utcnow().isoformat()


class SupplierCapabilityRegistry:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}

    def add(self, profile: dict[str, Any]) -> dict[str, Any]:
        rec = {
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
        rfq = {
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

    def import_quote(self, row: dict[str, Any], *, source: str, raw: str | None = None) -> dict[str, Any]:
        if source not in ALLOWED_SOURCES:
            if source == LIVE_FORBIDDEN_UNLESS_CONNECTED:
                raise PermissionError("LIVE_PROVIDER quotes require a connected provider; none registered")
            raise ValueError(source)
        raw_text = raw if raw is not None else json.dumps(row, sort_keys=True, default=str)
        rec = {
            "quoteId": row.get("quoteId") or new_id(),
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
        self.quotes[rec["quoteId"]] = rec
        return rec

    def import_json(self, text: str, *, source: str) -> list[dict[str, Any]]:
        payload = json.loads(text)
        rows = payload if isinstance(payload, list) else payload.get("items") or payload.get("quotes") or []
        return [self.import_quote(dict(r), source=source, raw=json.dumps(r, sort_keys=True, default=str)) for r in rows]

    def import_csv(self, text: str, *, source: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in csv.DictReader(io.StringIO(text))]
        return [self.import_quote(r, source=source, raw=csv.writer.__doc__ and ",".join(r.values()) or str(r)) for r in rows]

    def import_fx(self, row: dict[str, Any], *, source: str) -> dict[str, Any]:
        if source not in ALLOWED_SOURCES:
            raise PermissionError("FX remains MANUAL/IMPORTED unless a live FxRateProvider is connected")
        return self.providers.import_rows(self.providers.fx, [row], source=source)[0]

    def normalize(self, quote: dict[str, Any]) -> dict[str, Any]:
        raw = quote.get("raw") or quote
        material = float(raw.get("material") or raw.get("materialCost") or 0)
        processing = float(raw.get("processing") or raw.get("labor") or 0)
        setup = float(raw.get("setup") or raw.get("setupCost") or raw.get("tooling") or raw.get("toolingCost") or 0)
        packaging = float(raw.get("packaging") or raw.get("packagingCost") or 0)
        freight = float(raw.get("freight") or raw.get("shipping") or 0)
        qty = max(int(raw.get("quantity") or raw.get("moq") or 1), 1)
        unit = (material + processing + packaging) + (setup / qty) + freight
        return {
            "material": round(material, 2),
            "processing": round(processing, 2),
            "setupTooling": round(setup, 2),
            "packaging": round(packaging, 2),
            "freight": round(freight, 2),
            "moq": int(raw.get("moq") or 1),
            "leadTimeDays": float(raw.get("leadTimeDays") or raw.get("leadTime") or 0),
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
        w = {"landed": 0.5, "lead": 0.25, "moq": 0.15, "risk": 0.1, **(weights or {})}
        rows = []
        for qid in quote_ids:
            q = self.quotes[qid]
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
            fx = self.providers.fx.items.get(fx_snapshot_id)
            if fx and fx.get("source") == "LIVE_PROVIDER" and not self.providers.live.get("FxRateProvider"):
                raise PermissionError("static FX fixture cannot be labelled LIVE_PROVIDER")
        cmp = {
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
