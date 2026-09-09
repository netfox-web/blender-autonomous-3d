"""Phase 601–660 prototype validation loop. REAL_LOGIC / FIXTURE / MANUAL_EVIDENCE — not Production Ready."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.mfg_release import FAMILY_STEPS
from fox3d.parametric import CabinetSpec

UNIT_STATES = (
    "PLANNED",
    "WAITING_HUMAN_START",
    "IN_BUILD",
    "WAITING_VALIDATION",
    "VALIDATED",
    "HOLD",
    "REWORK",
    "SCRAPPED",
)
READINESS_STATES = (
    "NOT_SELECTED",
    "READY_FOR_PROTOTYPE",
    "PROTOTYPE_IN_PROGRESS",
    "WAITING_PHYSICAL_EVIDENCE",
    "HOLD",
    "NEEDS_ECO",
    "PROTOTYPE_VALIDATED",
    "READY_FOR_MANUAL_PILOT_BATCH",
    "READY_FOR_HUMAN_GO_NO_GO",
)
DECISIONS = ("PASS_AS_BUILT", "REWORK_CURRENT_UNIT", "CREATE_ECO", "HOLD_SKU", "SCRAP_UNIT")
EVIDENCE_SOURCES = frozenset({"MANUAL", "IMPORTED", "FIXTURE"})
REQUIRED_MEASUREMENTS = ("widthMm", "depthMm", "heightMm", "assembledWeightKg", "assemblyMinutes")
PACK_MEASUREMENTS = ("cartonLengthMm", "cartonWidthMm", "cartonHeightMm", "packedWeightKg")
DEFAULT_TOLERANCE = {
    "dimMm": 3.0,
    "dimPct": 0.02,
    "weightKg": 0.5,
    "assemblyMinutes": 15.0,
    "label": "ENGINEERING_POLICY",
    "certification": False,
}


def _now() -> str:
    return utcnow().isoformat()


def _finite_number(value: Any, field: str, *, allow_zero: bool = False) -> float:
    if value is None or isinstance(value, bool) or isinstance(value, (list, dict)):
        raise PrototypeError("BLOCKED", f"invalid {field}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PrototypeError("BLOCKED", f"non-numeric {field}") from None
    if not math.isfinite(number):
        raise PrototypeError("BLOCKED", f"non-finite {field}")
    if number < 0 or (number == 0 and not allow_zero):
        raise PrototypeError("BLOCKED", f"invalid {field}")
    return number


def variance(target: float | None, actual: float | None) -> dict[str, Any]:
    if target is None or actual is None:
        return {"target": target, "actual": actual, "abs": None, "pct": None, "complete": False}
    diff = actual - target
    pct = (diff / target) if target else None
    return {"target": target, "actual": actual, "abs": diff, "pct": pct, "complete": True}


class PrototypeError(PermissionError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.status = "BLOCKED"


class PrototypeFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.root = Path(platform.root) / "prototype"
        self.root.mkdir(parents=True, exist_ok=True)
        self.selections: dict[str, dict[str, Any]] = {}
        self.units: dict[str, dict[str, Any]] = {}
        self.measurements: dict[str, dict[str, Any]] = {}
        self.ecos: dict[str, dict[str, Any]] = {}
        self.costs: dict[str, dict[str, Any]] = {}
        self.checklists: dict[str, dict[str, Any]] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.idem: dict[str, str] = {}
        self.load()

    def _path(self) -> Path:
        return self.root / "prototype.json"

    def load(self) -> None:
        payload = read_json(self._path()) or {}
        self.selections = {r["selectionId"]: r for r in payload.get("selections") or [] if isinstance(r, dict) and r.get("selectionId")}
        self.units = {r["prototypeUnitId"]: r for r in payload.get("units") or [] if isinstance(r, dict) and r.get("prototypeUnitId")}
        self.measurements = {r["measurementId"]: r for r in payload.get("measurements") or [] if isinstance(r, dict) and r.get("measurementId")}
        self.ecos = {r["ecoId"]: r for r in payload.get("ecos") or [] if isinstance(r, dict) and r.get("ecoId")}
        self.costs = {r["costId"]: r for r in payload.get("costs") or [] if isinstance(r, dict) and r.get("costId")}
        self.checklists = {r["checklistId"]: r for r in payload.get("checklists") or [] if isinstance(r, dict) and r.get("checklistId")}
        self.decisions = {r["decisionId"]: r for r in payload.get("decisions") or [] if isinstance(r, dict) and r.get("decisionId")}
        raw_idem = payload.get("idem") or {}
        self.idem = dict(raw_idem) if isinstance(raw_idem, dict) else {}

    def persist(self) -> None:
        atomic_write_json(
            self._path(),
            {
                "selections": list(self.selections.values()),
                "units": list(self.units.values()),
                "measurements": list(self.measurements.values()),
                "ecos": list(self.ecos.values()),
                "costs": list(self.costs.values()),
                "checklists": list(self.checklists.values()),
                "decisions": list(self.decisions.values()),
                "idem": self.idem,
                "liveMachineControl": False,
                "truthLabel": "REAL_LOGIC",
            },
        )

    def _require_tenant(self, rec: dict[str, Any], tenant_id: str) -> None:
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: prototype")

    def _identity(self, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        ident = self.platform.pilot.identity.require_active(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        return ident

    def _is_fixture(self, ident: dict[str, Any]) -> bool:
        op = ident.get("operator") or {}
        caps = {str(c).upper() for c in (op.get("capabilities") or [])}
        name = str(op.get("displayName") or "").lower()
        return "FIXTURE" in caps or name.startswith("fixture")

    def _source_for(self, ident: dict[str, Any], requested: str) -> str:
        source = str(requested or "").upper()
        if source not in EVIDENCE_SOURCES:
            raise PrototypeError("BLOCKED", "evidence source must be MANUAL/IMPORTED/FIXTURE")
        if self._is_fixture(ident):
            if source in {"MANUAL", "IMPORTED"}:
                raise PrototypeError("BLOCKED", "fixture actor cannot produce MANUAL_EVIDENCE")
            return "FIXTURE"
        if source == "FIXTURE":
            return "FIXTURE"
        return source

    def _idem(self, key: str, factory) -> dict[str, Any]:
        if key in self.idem:
            existing = self.idem[key]
            for store in (self.selections, self.units, self.measurements, self.ecos, self.costs, self.checklists, self.decisions):
                if existing in store:
                    return store[existing]
            raise PrototypeError("BLOCKED", "idempotent key missing record")
        rec = factory()
        rid = rec.get("prototypeUnitId") or rec.get("measurementId") or rec.get("ecoId") or rec.get("costId") or rec.get("checklistId") or rec.get("decisionId") or rec.get("selectionId")
        self.idem[key] = str(rid)
        self.persist()
        return rec

    def select(
        self,
        *,
        tenant_id: str,
        candidate_id: str,
        operator_id: str,
        shift_id: str,
        reason: str,
        ranking_id: str | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if not reason:
            raise PrototypeError("BLOCKED", "selection requires reason")
        rec = self.platform.portfolio.candidates[candidate_id]
        self.platform.portfolio._require_tenant(rec, tenant_id)
        if rec.get("state") in {"REJECTED_DFM", "NEEDS_INPUT", "SUPERSEDED"}:
            raise PrototypeError("BLOCKED", "stale/superseded/rejected candidate cannot be selected")
        ranking = None
        if ranking_id:
            ranking = self.platform.portfolio.rankings[ranking_id]
            self.platform.portfolio._require_tenant(ranking, tenant_id)
        else:
            ranking = next(
                (r for r in self.platform.portfolio.rankings.values() if r.get("portfolioId") == rec.get("portfolioId") and r.get("tenantId") == tenant_id),
                None,
            )
        if not ranking:
            raise PrototypeError("BLOCKED", "ranking required for selection")
        top = next((row for row in (ranking.get("top10") or []) if row.get("candidateId") == candidate_id), None)
        if not top:
            raise PrototypeError("BLOCKED", "candidate not in Top 10")
        commercial = rec.get("commercial") or {}
        if commercial.get("stale") or commercial.get("engineeringHash") != rec.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "stale candidate lineage")
        fixture = self._is_fixture(ident)
        key = f"{tenant_id}::select::{candidate_id}::{rec.get('engineeringHash')}"

        def _make():
            body = {
                "selectionId": new_id(),
                "tenantId": tenant_id,
                "portfolioId": rec.get("portfolioId"),
                "candidateId": candidate_id,
                "canonicalHash": rec.get("canonicalHash"),
                "engineeringHash": rec.get("engineeringHash"),
                "bomHash": rec.get("bomHash"),
                "nestingHash": rec.get("nestingHash") or (rec.get("dfm") or {}).get("lineage", {}).get("nestingHash"),
                "costSnapshotHash": commercial.get("costSnapshotHash"),
                "rankingPolicyHash": ranking.get("rankingPolicyHash"),
                "score": top.get("score"),
                "selectedAt": _now(),
                "selectedBy": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "reason": reason,
                "fixtureActor": fixture,
                "truthLabel": "FIXTURE" if fixture else "MANUAL_EVIDENCE",
                "liveMachineControl": False,
            }
            if body["truthLabel"] == "MANUAL_EVIDENCE" and fixture:
                raise PrototypeError("BLOCKED", "fixture actor cannot produce MANUAL_EVIDENCE")
            self.selections[body["selectionId"]] = body
            self.persist()
            return body

        return self._idem(key, _make)

    def select_four(self, *, tenant_id: str, portfolio_id: str, operator_id: str, shift_id: str, reason: str) -> list[dict[str, Any]]:
        ranking = next(
            (r for r in self.platform.portfolio.rankings.values() if r.get("portfolioId") == portfolio_id and r.get("tenantId") == tenant_id),
            None,
        )
        if not ranking or len(ranking.get("top10") or []) < 4:
            raise PrototypeError("BLOCKED", "Top 10 required")
        return [
            self.select(
                tenant_id=tenant_id,
                candidate_id=row["candidateId"],
                operator_id=operator_id,
                shift_id=shift_id,
                reason=reason,
                ranking_id=ranking["rankingId"],
            )
            for row in ranking["top10"][:4]
        ]

    def create_unit(
        self,
        *,
        tenant_id: str,
        selection_id: str,
        operator_id: str,
        shift_id: str,
        seq: int = 1,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        sel = self.selections[selection_id]
        self._require_tenant(sel, tenant_id)
        cand = self.platform.portfolio.candidates[sel["candidateId"]]
        if cand.get("state") == "SUPERSEDED" or cand.get("engineeringHash") != sel.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "superseded engineering version cannot create prototype unit")
        key = f"{tenant_id}::unit::{selection_id}::{seq}"

        def _make():
            pack = None
            try:
                if cand.get("state") == "APPROVED_FOR_PROTOTYPE":
                    pack = self.platform.portfolio.prototype_pack(cand["candidateId"], tenant_id=tenant_id)
            except Exception:
                pack = None
            steps = FAMILY_STEPS.get("KD_FURNITURE") or ["assembly", "packaging"]
            traveler = (pack or {}).get("traveler") or {
                "family": "KD_FURNITURE",
                "steps": [
                    {"seq": i + 1, "operation": op, "kind": "operator_instruction", "machineCommand": False, "liveCnc": False, "liveLaser": False}
                    for i, op in enumerate(steps)
                ],
                "label": "MANUAL_STATION",
            }
            body = {
                "prototypeUnitId": new_id(),
                "tenantId": tenant_id,
                "selectionId": selection_id,
                "candidateId": sel["candidateId"],
                "seq": int(seq),
                "state": "PLANNED",
                "engineeringHash": sel["engineeringHash"],
                "canonicalHash": sel["canonicalHash"],
                "bomHash": sel["bomHash"],
                "nestingHash": sel["nestingHash"],
                "costSnapshotHash": sel["costSnapshotHash"],
                "rankingPolicyHash": sel["rankingPolicyHash"],
                "traveler": traveler,
                "consumesInventory": False,
                "materialConsumed": False,
                "physicalPrototypeValidated": False,
                "createdBy": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "createdAt": _now(),
                "liveCnc": False,
                "liveLaser": False,
                "liveMachineControl": False,
                "truthLabel": "FIXTURE" if self._is_fixture(ident) else "REAL_LOGIC",
            }
            self.units[body["prototypeUnitId"]] = body
            self.persist()
            return body

        return self._idem(key, _make)

    def start_unit(self, prototype_unit_id: str, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        rec = self.units[prototype_unit_id]
        self._require_tenant(rec, tenant_id)
        cand = self.platform.portfolio.candidates[rec["candidateId"]]
        if cand.get("state") == "SUPERSEDED" or cand.get("engineeringHash") != rec.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "superseded engineering version cannot silently continue")
        if rec["state"] in {"IN_BUILD", "WAITING_VALIDATION", "VALIDATED"}:
            return rec
        if rec["state"] not in {"PLANNED", "WAITING_HUMAN_START", "REWORK"}:
            raise PrototypeError("BLOCKED", f"cannot start from {rec['state']}")
        rec["state"] = "IN_BUILD"
        rec["startedAt"] = _now()
        self.persist()
        return rec

    def complete_build(self, prototype_unit_id: str, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        rec = self.units[prototype_unit_id]
        self._require_tenant(rec, tenant_id)
        if rec["state"] == "WAITING_VALIDATION":
            return rec
        if rec["state"] != "IN_BUILD":
            raise PrototypeError("BLOCKED", "complete requires IN_BUILD")
        rec["state"] = "WAITING_VALIDATION"
        rec["buildCompletedAt"] = _now()
        self.persist()
        return rec

    def consume_material_once(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        sheets: int,
        operator_id: str,
        shift_id: str,
    ) -> dict[str, Any]:
        self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        rec = self.units[prototype_unit_id]
        self._require_tenant(rec, tenant_id)
        qty = int(_finite_number(sheets, "sheets"))
        if rec.get("materialConsumed"):
            if rec.get("consumedSheets") != qty:
                raise PrototypeError("BLOCKED", "no double consume after restart/retry")
            return rec
        rec["materialConsumed"] = True
        rec["consumedSheets"] = qty
        rec["consumesInventory"] = True
        self.persist()
        return rec

    def record_as_built(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        source: str,
        values: dict[str, Any],
        dam_refs: list[dict[str, Any]] | None = None,
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        cand = self.platform.portfolio.candidates[unit["candidateId"]]
        if values.get("engineeringHash") and values.get("engineeringHash") != unit.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "wrong engineeringHash")
        if values.get("prototypeUnitId") and values.get("prototypeUnitId") != prototype_unit_id:
            raise PrototypeError("BLOCKED", "wrong prototypeUnitId")
        src = self._source_for(ident, source)
        numeric: dict[str, float] = {}
        for field in list(REQUIRED_MEASUREMENTS) + list(PACK_MEASUREMENTS):
            if field in values:
                numeric[field] = _finite_number(values[field], field, allow_zero=False)
        spec = cand.get("spec") or {}
        pack = ((cand.get("sku") or {}).get("packing") or {})
        weight = ((cand.get("sku") or {}).get("weight") or {})
        targets = {
            "widthMm": spec.get("width"),
            "depthMm": spec.get("depth"),
            "heightMm": spec.get("height"),
            "assembledWeightKg": weight.get("grossKg") or weight.get("netKg"),
            "assemblyMinutes": (cand.get("dfm") or {}).get("assemblyMinutes"),
            "cartonLengthMm": pack.get("length"),
            "cartonWidthMm": pack.get("width"),
            "cartonHeightMm": pack.get("height"),
            "packedWeightKg": weight.get("grossKg"),
        }
        vars_ = {k: variance(float(targets[k]) if targets.get(k) is not None else None, numeric.get(k)) for k in targets}
        refs = []
        for ref in dam_refs or []:
            if not isinstance(ref, dict):
                raise PrototypeError("BLOCKED", "malformed DAM ref")
            if ref.get("tenantId") and ref.get("tenantId") != tenant_id:
                raise PrototypeError("BLOCKED", "cross-tenant DAM/evidence reference")
            if src == "IMPORTED" and (not ref.get("sha256") or not ref.get("size")):
                raise PrototypeError("BLOCKED", "imported evidence requires SHA/size")
            refs.append(ref)
        missing = [f for f in REQUIRED_MEASUREMENTS if f not in numeric]
        label = "FIXTURE" if src == "FIXTURE" else ("IMPORTED_EVIDENCE" if src == "IMPORTED" else "MANUAL_EVIDENCE")
        body = {
            "measurementId": new_id(),
            "tenantId": tenant_id,
            "prototypeUnitId": prototype_unit_id,
            "candidateId": unit["candidateId"],
            "engineeringHash": unit["engineeringHash"],
            "source": src,
            "truthLabel": label,
            "values": numeric,
            "targets": targets,
            "variance": vars_,
            "tolerance": dict(DEFAULT_TOLERANCE),
            "notes": notes or {},
            "damRefs": refs,
            "missingRequired": missing,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "recordedAt": _now(),
            "liveMachineControl": False,
        }
        self.measurements[body["measurementId"]] = body
        unit["latestMeasurementId"] = body["measurementId"]
        unit["evidenceSource"] = src
        if missing:
            unit["state"] = "WAITING_VALIDATION"
            unit["physicalPrototypeValidated"] = False
        elif src == "FIXTURE":
            unit["physicalPrototypeValidated"] = False
            unit["state"] = "WAITING_VALIDATION"
        self.persist()
        return body

    def record_actual_cost(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        source: str,
        components: dict[str, Any],
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        src = self._source_for(ident, source)
        cand = self.platform.portfolio.candidates[unit["candidateId"]]
        estimate = dict(cand.get("commercial") or {})
        observed: dict[str, Any] = {}
        sources: dict[str, str] = {}
        missing: list[str] = []
        for key, raw in (components or {}).items():
            if raw is None:
                missing.append(key)
                observed[key] = None
                sources[key] = "MISSING"
                continue
            observed[key] = _finite_number(raw, key, allow_zero=True)
            sources[key] = src
        complete = not missing and bool(components)
        total = None
        if complete:
            total = sum(float(v) for v in observed.values() if v is not None)
        label = "FIXTURE" if src == "FIXTURE" else ("PARTIAL" if not complete else ("IMPORTED" if src == "IMPORTED" else "MANUAL"))
        body = {
            "costId": new_id(),
            "tenantId": tenant_id,
            "prototypeUnitId": prototype_unit_id,
            "engineeringHash": unit["engineeringHash"],
            "estimateSnapshot": {k: estimate.get(k) for k in ("landedCost", "materialCost", "laborCost", "packagingCost", "costSnapshotHash", "engineeringHash", "truthLabel")},
            "observed": observed,
            "componentSources": sources,
            "missing": missing,
            "total": total,
            "source": src,
            "truthLabel": label,
            "liveProvider": False,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "recordedAt": _now(),
        }
        body["costSnapshotHash"] = stable_hash({k: body[k] for k in body if k not in {"costId", "costSnapshotHash", "recordedAt"}})
        self.costs[body["costId"]] = body
        unit["actualCostId"] = body["costId"]
        self.persist()
        return body

    def packaging_checklist(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        source: str,
        observed: dict[str, Any],
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        src = self._source_for(ident, source)
        meas = self.measurements.get(unit.get("latestMeasurementId") or "")
        if meas and meas.get("engineeringHash") != unit.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "predicted vs observed engineering version mismatch")
        packed = observed.get("packedWeightKg")
        if packed is None:
            raise PrototypeError("BLOCKED", "missing packed weight")
        packed_n = _finite_number(packed, "packedWeightKg")
        longest = max(
            _finite_number(observed.get("cartonLengthMm") or 1, "cartonLengthMm"),
            _finite_number(observed.get("cartonWidthMm") or 1, "cartonWidthMm"),
            _finite_number(observed.get("cartonHeightMm") or 1, "cartonHeightMm"),
        )
        oversize = longest > 1500
        overweight = packed_n > 30
        ok = not oversize and not overweight
        reason = "ok" if ok else ("oversize" if oversize else "overweight")
        if not ok:
            unit["state"] = "HOLD"
        body = {
            "checklistId": new_id(),
            "tenantId": tenant_id,
            "prototypeUnitId": prototype_unit_id,
            "engineeringHash": unit["engineeringHash"],
            "source": src,
            "truthLabel": "FIXTURE" if src == "FIXTURE" else "MANUAL_EVIDENCE",
            "carrierTruth": "CONFIG_ESTIMATE",
            "barcodeHardware": "PARTIAL",
            "certification": False,
            "ok": ok,
            "reason": reason,
            "observed": observed,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "recordedAt": _now(),
        }
        self.checklists[body["checklistId"]] = body
        unit["packagingChecklistId"] = body["checklistId"]
        self.persist()
        return body

    def decide(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if decision not in DECISIONS:
            raise PrototypeError("BLOCKED", "unknown decision")
        if not reason:
            raise PrototypeError("BLOCKED", "decision requires reason")
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        meas = self.measurements.get(unit.get("latestMeasurementId") or "")
        if decision == "PASS_AS_BUILT":
            if not meas or meas.get("missingRequired"):
                raise PrototypeError("BLOCKED", "missing required measurements cannot validate")
            if meas.get("engineeringHash") != unit.get("engineeringHash"):
                raise PrototypeError("BLOCKED", "old prototype evidence cannot validate a new engineeringHash")
            if meas.get("source") == "FIXTURE" or meas.get("truthLabel") == "FIXTURE":
                unit["physicalPrototypeValidated"] = False
                unit["state"] = "WAITING_VALIDATION"
            else:
                unit["physicalPrototypeValidated"] = True
                unit["state"] = "VALIDATED"
        elif decision == "REWORK_CURRENT_UNIT":
            unit["state"] = "REWORK"
            unit["physicalPrototypeValidated"] = False
        elif decision == "HOLD_SKU":
            unit["state"] = "HOLD"
        elif decision == "SCRAP_UNIT":
            unit["state"] = "SCRAPPED"
            unit["physicalPrototypeValidated"] = False
        elif decision == "CREATE_ECO":
            eco = self.create_eco(unit["candidateId"], tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id, reason=reason)
            unit["ecoId"] = eco["ecoId"]
            unit["state"] = "HOLD"
        body = {
            "decisionId": new_id(),
            "tenantId": tenant_id,
            "prototypeUnitId": prototype_unit_id,
            "candidateId": unit["candidateId"],
            "engineeringHash": unit["engineeringHash"],
            "decision": decision,
            "reason": reason,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "fixtureActor": self._is_fixture(ident),
            "at": _now(),
            "liveMachineControl": False,
        }
        self.decisions[body["decisionId"]] = body
        self.persist()
        return body

    def create_eco(
        self,
        candidate_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        reason: str,
        accept: bool = True,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if not reason:
            raise PrototypeError("BLOCKED", "ECO requires reason")
        old = self.platform.portfolio.candidates[candidate_id]
        self.platform.portfolio._require_tenant(old, tenant_id)
        old_hash = old.get("engineeringHash")
        eco_id = new_id()
        if not accept:
            body = {
                "ecoId": eco_id,
                "tenantId": tenant_id,
                "candidateId": candidate_id,
                "fromEngineeringHash": old_hash,
                "toEngineeringHash": None,
                "status": "REJECTED",
                "reason": reason,
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "at": _now(),
                "truthLabel": "REAL_LOGIC",
            }
            self.ecos[eco_id] = body
            self.persist()
            return body
        spec = CabinetSpec.model_validate(old["spec"])
        sku = self.platform.kd.build_sku(
            tenant_id=tenant_id,
            kind=old["kind"],
            render=False,
            width=spec.width,
            depth=spec.depth,
            height=spec.height,
            boardThickness=spec.boardThickness,
        )
        new_spec = CabinetSpec.model_validate(sku["spec"])
        new_spec.revision = int(spec.revision or 1) + 1
        new_spec.metadata = {**(new_spec.metadata or {}), "ecoParentEngineeringHash": old_hash, "ecoId": eco_id}
        sku["spec"] = new_spec.model_dump(mode="json")
        sku["engineeringHash"] = new_spec.engineering_hash()
        intent = self.platform.portfolio.get_intent(old["portfolioId"], tenant_id=tenant_id)
        nest = sku.get("nesting") or {}
        new_cand = {
            "candidateId": new_id(),
            "tenantId": tenant_id,
            "portfolioId": old["portfolioId"],
            "productId": sku["spec"].get("productId"),
            "kind": old["kind"],
            "family": "KD_FURNITURE",
            "spec": sku["spec"],
            "report": sku.get("report") or {},
            "engineeringHash": sku["engineeringHash"],
            "canonicalHash": stable_hash({"eco": eco_id, "parent": old.get("canonicalHash"), "revision": new_spec.revision}),
            "bomHash": (sku.get("bom") or {}).get("bomHash"),
            "nestingHash": nest.get("nestingHash"),
            "state": "CANDIDATE",
            "rejectionCodes": [],
            "dfm": self.platform.portfolio._scorecard(sku),
            "commercial": self.platform.portfolio._commercial(sku, intent),
            "demand": dict(old.get("demand") or intent.get("demand") or {}),
            "sku": {k: sku.get(k) for k in ("packing", "weight", "difficulty", "shipping", "gate", "commonParts", "bom", "nesting", "landed") if k in sku},
            "ecoOf": old["candidateId"],
            "createdAt": _now(),
            "liveCnc": False,
        }
        self.platform.portfolio.candidates[new_cand["candidateId"]] = new_cand
        old["state"] = "SUPERSEDED"
        old["supersededBy"] = new_cand["candidateId"]
        old["supersededAt"] = _now()
        self.platform.portfolio.persist()
        body = {
            "ecoId": eco_id,
            "tenantId": tenant_id,
            "candidateId": candidate_id,
            "newCandidateId": new_cand["candidateId"],
            "fromEngineeringHash": old_hash,
            "toEngineeringHash": new_cand["engineeringHash"],
            "fromBomHash": old.get("bomHash"),
            "toBomHash": new_cand.get("bomHash"),
            "fromNestingHash": old.get("nestingHash"),
            "toNestingHash": new_cand.get("nestingHash"),
            "fromCostSnapshotHash": (old.get("commercial") or {}).get("costSnapshotHash"),
            "toCostSnapshotHash": (new_cand.get("commercial") or {}).get("costSnapshotHash"),
            "status": "ACCEPTED",
            "reason": reason,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "at": _now(),
            "truthLabel": "REAL_LOGIC",
        }
        if body["fromEngineeringHash"] == body["toEngineeringHash"]:
            raise PrototypeError("BLOCKED", "ECO must change engineering hash")
        self.ecos[eco_id] = body
        self.persist()
        return body

    def approve_pilot_batch(
        self,
        candidate_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        reason: str,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if self._is_fixture(ident):
            raise PrototypeError("BLOCKED", "fixture actor cannot approve pilot batch")
        if not reason:
            raise PrototypeError("BLOCKED", "pilot batch requires reason")
        board = self.readiness(candidate_id, tenant_id=tenant_id)
        if board["state"] not in {"PROTOTYPE_VALIDATED", "READY_FOR_HUMAN_GO_NO_GO"}:
            raise PrototypeError("BLOCKED", "incomplete validation blocks pilot readiness")
        if board.get("demandLabel") == "REAL":
            raise PrototypeError("BLOCKED", "MOCK demand cannot be labeled REAL")
        rec = {
            "decisionId": new_id(),
            "tenantId": tenant_id,
            "candidateId": candidate_id,
            "decision": "READY_FOR_MANUAL_PILOT_BATCH",
            "reason": reason,
            "demandLabel": board.get("demandLabel"),
            "demandDidNotUpgrade": True,
            "productionReady": False,
            "liveMachineControl": False,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "at": _now(),
        }
        self.decisions[rec["decisionId"]] = rec
        self.persist()
        return rec

    def readiness(self, candidate_id: str, *, tenant_id: str) -> dict[str, Any]:
        cand = self.platform.portfolio.candidates[candidate_id]
        self.platform.portfolio._require_tenant(cand, tenant_id)
        sel = next((s for s in self.selections.values() if s.get("candidateId") == candidate_id and s.get("tenantId") == tenant_id), None)
        unit = next((u for u in self.units.values() if u.get("candidateId") == candidate_id and u.get("tenantId") == tenant_id), None)
        meas = self.measurements.get((unit or {}).get("latestMeasurementId") or "")
        cost = self.costs.get((unit or {}).get("actualCostId") or "")
        pack = self.checklists.get((unit or {}).get("packagingChecklistId") or "")
        eco = next((e for e in self.ecos.values() if e.get("candidateId") == candidate_id and e.get("status") == "ACCEPTED"), None)
        demand = (cand.get("demand") or {}).get("truthLabel") or "MOCK"
        state = "NOT_SELECTED"
        if sel:
            state = "READY_FOR_PROTOTYPE"
        if unit:
            if unit["state"] in {"PLANNED", "WAITING_HUMAN_START", "IN_BUILD", "REWORK"}:
                state = "PROTOTYPE_IN_PROGRESS"
            elif unit["state"] == "WAITING_VALIDATION":
                state = "WAITING_PHYSICAL_EVIDENCE"
            elif unit["state"] == "HOLD":
                state = "HOLD"
            elif unit["state"] == "SCRAPPED":
                state = "HOLD"
            elif unit["state"] == "VALIDATED" and unit.get("physicalPrototypeValidated"):
                state = "PROTOTYPE_VALIDATED"
            elif unit["state"] == "VALIDATED":
                state = "WAITING_PHYSICAL_EVIDENCE"
        if eco:
            state = "NEEDS_ECO"
        if pack and pack.get("ok") is False:
            state = "HOLD"
        if demand == "REAL":
            raise PrototypeError("BLOCKED", "MOCK demand cannot influence GO state")
        human_pilot = any(d.get("candidateId") == candidate_id and d.get("decision") == "READY_FOR_MANUAL_PILOT_BATCH" for d in self.decisions.values())
        if human_pilot and state == "PROTOTYPE_VALIDATED" and pack and pack.get("ok") and unit and unit.get("physicalPrototypeValidated"):
            state = "READY_FOR_MANUAL_PILOT_BATCH"
        return {
            "candidateId": candidate_id,
            "tenantId": tenant_id,
            "state": state,
            "rankingScore": sel.get("score") if sel else None,
            "rankingPolicyHash": sel.get("rankingPolicyHash") if sel else None,
            "conservationOk": (cand.get("dfm") or {}).get("conservationOk"),
            "prototypeStatus": (unit or {}).get("state"),
            "dimensionalVariance": (meas or {}).get("variance"),
            "observedCostLabel": (cost or {}).get("truthLabel"),
            "packagingOk": None if not pack else pack.get("ok"),
            "physicalPrototypeValidated": bool((unit or {}).get("physicalPrototypeValidated")),
            "demandLabel": demand,
            "liveMachineControl": False,
            "productionReady": False,
            "blockers": [k for k, ok in (
                ("not_selected", not sel),
                ("no_unit", not unit),
                ("fixture_evidence", (meas or {}).get("source") == "FIXTURE"),
                ("missing_measurements", bool((meas or {}).get("missingRequired"))),
                ("packaging", pack.get("ok") is False if pack else False),
                ("eco", bool(eco)),
            ) if ok],
        }

    def decision_board(self, portfolio_id: str, *, tenant_id: str) -> dict[str, Any]:
        ranking = next(
            (r for r in self.platform.portfolio.rankings.values() if r.get("portfolioId") == portfolio_id and r.get("tenantId") == tenant_id),
            None,
        )
        rows = []
        for item in (ranking or {}).get("top10") or []:
            rows.append(self.readiness(item["candidateId"], tenant_id=tenant_id))
        return {
            "portfolioId": portfolio_id,
            "tenantId": tenant_id,
            "rows": rows,
            "liveMachineControl": False,
            "globalProductionReady": False,
            "truthLabel": "REAL_LOGIC",
        }


def run_prototype_scenario(
    plat: Any,
    *,
    tenant_a: str = "pv-a",
    tenant_b: str = "pv-b",
    render: bool = False,
    evidence_commit: str | None = None,
) -> dict[str, Any]:
    from fox3d.portfolio import run_portfolio_scenario

    portfolio = run_portfolio_scenario(plat, tenant_a=tenant_a, tenant_b=tenant_b, render=render, evidence_commit=evidence_commit)
    ident = plat.pilot.identity
    fixture = ident.register_operator(tenant_id=tenant_a, display_name="fixture-pm", capabilities=["FIXTURE"])
    human = ident.register_operator(tenant_id=tenant_a, display_name="builder", capabilities=["MANUAL"])
    other = ident.register_operator(tenant_id=tenant_b, display_name="other")
    shift = ident.open_shift(tenant_id=tenant_a, operator_id=fixture["operatorId"], station_id="st-proto")
    human_shift = ident.open_shift(tenant_id=tenant_a, operator_id=human["operatorId"], station_id="st-proto")
    closed = ident.open_shift(tenant_id=tenant_a, operator_id=fixture["operatorId"], station_id="st-closed")
    ident.close_shift(closed["shiftId"], tenant_id=tenant_a, operator_id=fixture["operatorId"])
    ident.register_operator(tenant_id=tenant_a, display_name="disabled", operator_id="op-off", enabled=False)
    pf = plat.prototype
    selected = pf.select_four(
        tenant_id=tenant_a,
        portfolio_id=portfolio["portfolioId"],
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        reason="pilot-four",
    )
    units = []
    for i, sel in enumerate(selected, start=1):
        unit = pf.create_unit(tenant_id=tenant_a, selection_id=sel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"], seq=1)
        unit = pf.start_unit(unit["prototypeUnitId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
        unit = pf.complete_build(unit["prototypeUnitId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
        spec = plat.portfolio.candidates[sel["candidateId"]]["spec"]
        pf.record_as_built(
            unit["prototypeUnitId"],
            tenant_id=tenant_a,
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            source="FIXTURE",
            values={
                "widthMm": spec["width"],
                "depthMm": spec["depth"],
                "heightMm": spec["height"],
                "assembledWeightKg": 12,
                "assemblyMinutes": 40,
                "cartonLengthMm": 800,
                "cartonWidthMm": 400,
                "cartonHeightMm": 200,
                "packedWeightKg": 13,
            },
        )
        pf.record_actual_cost(
            unit["prototypeUnitId"],
            tenant_id=tenant_a,
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            source="FIXTURE",
            components={"laborMinutes": 40, "hardwareConsumed": None},
        )
        pf.packaging_checklist(
            unit["prototypeUnitId"],
            tenant_id=tenant_a,
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            source="FIXTURE",
            observed={"cartonLengthMm": 800, "cartonWidthMm": 400, "cartonHeightMm": 200, "packedWeightKg": 13},
        )
        units.append(unit)
    board = pf.decision_board(portfolio["portfolioId"], tenant_id=tenant_a)
    physical = any(u.get("physicalPrototypeValidated") for u in pf.units.values())
    return {
        "ok": True,
        "portfolio": portfolio,
        "selected": selected,
        "units": [pf.units[u["prototypeUnitId"]] for u in units],
        "board": board,
        "physicalPrototypeValidated": physical,
        "fixtureCannotValidate": physical is False,
        "demandLabel": portfolio.get("demandLabel"),
        "liveMachineControl": False,
        "media": portfolio.get("media") or [],
        "label": "FIXTURE/REAL_LOGIC",
        "closedShiftId": closed["shiftId"],
        "disabledOperatorId": "op-off",
        "otherTenantOperatorId": other["operatorId"],
        "human": human,
        "humanShift": human_shift,
        "fixture": fixture,
        "fixtureShift": shift,
    }
