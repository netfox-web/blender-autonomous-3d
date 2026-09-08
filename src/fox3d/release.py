"""Approval audit trail, staleness, and release-candidate states. Not LIVE_CNC."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow

RC_STATES = (
    "PROTOTYPE",
    "ENGINEERING_VALID",
    "EVIDENCE_VERIFIED",
    "WAITING_APPROVAL",
    "APPROVED_FOR_EXPORT",
)
FORBIDDEN = frozenset({"LIVE_CNC", "LIVE_LASER", "APPROVED_FOR_PRODUCTION", "APPROVED_FOR_MACHINE"})


class ReleaseGate:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.approvals: dict[str, dict[str, Any]] = {}

    def hashes_of(self, entity: dict[str, Any]) -> dict[str, str | None]:
        lin = entity.get("lineage") or {}
        return {
            "engineeringHash": entity.get("engineeringHash") or lin.get("engineeringHash"),
            "bomHash": (entity.get("bom") or {}).get("bomHash") or lin.get("bomHash") or entity.get("bomHash"),
            "nestingHash": (entity.get("nesting") or {}).get("nestingHash") or lin.get("nestingHash") or entity.get("nestingHash"),
            "costHash": lin.get("costHash") or (entity.get("quote") or {}).get("quoteHash") or (entity.get("landed") or {}).get("unitLandedCost") and stable_hash(entity.get("landed")),
            "packagingHash": (entity.get("packing") or {}).get("packagingHash") or lin.get("packagingHash"),
            "evidenceHash": entity.get("evidenceHash") or lin.get("evidenceHash"),
        }

    def audit(
        self,
        *,
        actor: str,
        entity_id: str,
        entity: dict[str, Any],
        decision: str,
        reason: str,
        evidence_hash: str | None = None,
    ) -> dict[str, Any]:
        hashes = self.hashes_of(entity)
        rec = {
            "eventId": new_id(),
            "actor": actor,
            "entityId": entity_id,
            "entityVersion": entity.get("spec", {}).get("revision") if isinstance(entity.get("spec"), dict) else entity.get("version") or 1,
            "engineeringHash": hashes["engineeringHash"],
            "evidenceHash": evidence_hash or hashes["evidenceHash"],
            "hashes": hashes,
            "approvedAt": utcnow().isoformat(),
            "decision": decision,
            "reason": reason,
            "immutable": True,
            "liveMachineControl": False,
        }
        rec["auditHash"] = stable_hash({k: rec[k] for k in rec if k not in {"eventId", "auditHash"}})
        self.events.append(rec)
        return rec

    def is_stale(self, approval: dict[str, Any], entity: dict[str, Any]) -> bool:
        current = self.hashes_of(entity)
        bound = approval.get("hashes") or {}
        for key in ("engineeringHash", "bomHash", "nestingHash", "costHash", "packagingHash"):
            if bound.get(key) and current.get(key) and str(bound[key]) != str(current[key]):
                return True
        return False

    def advance(self, entity_id: str, *, target: str, actor: str, entity: dict[str, Any], evidence_ok: bool = False) -> dict[str, Any]:
        if target in FORBIDDEN or target in {"LIVE_CNC", "LIVE_LASER"}:
            raise PermissionError("LIVE machine states forbidden; liveMachineControl=false")
        if target not in RC_STATES:
            raise ValueError(target)
        current = (self.approvals.get(entity_id) or {}).get("state") or "PROTOTYPE"
        order = list(RC_STATES)
        if order.index(target) < order.index(current):
            raise ValueError(f"cannot regress {current} -> {target}")
        if target == "EVIDENCE_VERIFIED" and not evidence_ok:
            raise PermissionError("evidence verifier must PASS")
        if target == "APPROVED_FOR_EXPORT":
            if current not in {"WAITING_APPROVAL", "EVIDENCE_VERIFIED"}:
                raise PermissionError("export requires WAITING_APPROVAL")
        rec = {
            "entityId": entity_id,
            "state": target,
            "actor": actor,
            "hashes": self.hashes_of(entity),
            "stale": False,
            "liveMachineControl": False,
            "equalsLiveCnc": False,
            "note": "APPROVED_FOR_EXPORT is not LIVE_CNC/LASER",
        }
        rec["audit"] = self.audit(actor=actor, entity_id=entity_id, entity=entity, decision=target, reason="release-gate", evidence_hash=rec["hashes"].get("evidenceHash"))
        self.approvals[entity_id] = rec
        return rec

    def refresh_stale(self, entity_id: str, entity: dict[str, Any]) -> dict[str, Any]:
        rec = self.approvals.get(entity_id)
        if not rec:
            raise KeyError(entity_id)
        if self.is_stale(rec, entity):
            rec = dict(rec)
            rec["stale"] = True
            rec["state"] = "PROTOTYPE"
            rec["reason"] = "upstream hash changed; previous approval void"
            self.approvals[entity_id] = rec
            self.audit(actor="system", entity_id=entity_id, entity=entity, decision="STALE", reason="hash-change")
        return rec
