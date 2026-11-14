"""Approval audit trail, staleness, and release-candidate states. Not LIVE_CNC.

Release states advance strictly one step at a time along ``RC_STATES`` (no skipping).
``WAITING_APPROVAL`` and ``APPROVED_FOR_EXPORT`` require having reached ``EVIDENCE_VERIFIED``
because sequential advancement enforces that path. Approval records are keyed by
``(tenantId, entityId)`` so tenants cannot collide on the same entity id.
"""

from __future__ import annotations

import threading
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
        self.approvals: dict[tuple[str, str], dict[str, Any]] = {}
        self._locks_guard = threading.Lock()
        self._key_locks: dict[tuple[str, str], threading.RLock] = {}

    def _entity_lock(self, key: tuple[str, str]) -> threading.RLock:
        with self._locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._key_locks[key] = lock
            return lock

    def _key(self, tenant_id: str, entity_id: str) -> tuple[str, str]:
        return (tenant_id, entity_id)

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
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        hashes = self.hashes_of(entity)
        rec = {
            "eventId": new_id(),
            "actor": actor,
            "tenantId": tenant_id,
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

    def _require_bound_hashes(self, approval: dict[str, Any] | None, entity: dict[str, Any]) -> None:
        if not approval or not approval.get("hashes"):
            return
        if self.is_stale(approval, entity):
            raise PermissionError(
                "entity hashes changed since last gate state; re-verify from ENGINEERING_VALID"
            )

    def advance(
        self,
        entity_id: str,
        *,
        tenant_id: str,
        target: str,
        actor: str,
        entity: dict[str, Any],
        evidence_ok: bool = False,
    ) -> dict[str, Any]:
        if target in FORBIDDEN or target in {"LIVE_CNC", "LIVE_LASER"}:
            raise PermissionError("LIVE machine states forbidden; liveMachineControl=false")
        if target not in RC_STATES:
            raise ValueError(target)
        key = self._key(tenant_id, entity_id)
        with self._entity_lock(key):
            approval = self.approvals.get(key)
            current = (approval or {}).get("state") or "PROTOTYPE"
            order = list(RC_STATES)
            cur_idx = order.index(current)
            tgt_idx = order.index(target)
            if tgt_idx < cur_idx:
                raise ValueError(f"cannot regress {current} -> {target}")
            if tgt_idx > cur_idx + 1:
                raise ValueError(f"cannot skip from {current} to {target}; advance one state at a time")
            if target == "EVIDENCE_VERIFIED" and not evidence_ok:
                raise PermissionError("evidence verifier must PASS")
            if target == "APPROVED_FOR_EXPORT" and current != "WAITING_APPROVAL":
                raise PermissionError("export requires WAITING_APPROVAL")
            self._require_bound_hashes(approval, entity)
            hashes = self.hashes_of(entity)
            bound = (approval or {}).get("hashes") or {}
            if bound:
                hashes = {**bound, **{k: v for k, v in hashes.items() if v and not bound.get(k)}}
            rec = {
                "tenantId": tenant_id,
                "entityId": entity_id,
                "state": target,
                "actor": actor,
                "hashes": hashes,
                "stale": False,
                "liveMachineControl": False,
                "equalsLiveCnc": False,
                "note": "APPROVED_FOR_EXPORT is not LIVE_CNC/LASER",
            }
            rec["audit"] = self.audit(
                actor=actor,
                entity_id=entity_id,
                entity=entity,
                decision=target,
                reason="release-gate",
                evidence_hash=hashes.get("evidenceHash"),
                tenant_id=tenant_id,
            )
            self.approvals[key] = rec
            return rec

    def refresh_stale(self, entity_id: str, *, tenant_id: str, entity: dict[str, Any]) -> dict[str, Any]:
        key = self._key(tenant_id, entity_id)
        with self._entity_lock(key):
            rec = self.approvals.get(key)
            if not rec:
                raise KeyError(entity_id)
            if self.is_stale(rec, entity):
                rec = dict(rec)
                rec["stale"] = True
                rec["state"] = "PROTOTYPE"
                rec["reason"] = "upstream hash changed; previous approval void"
                self.approvals[key] = rec
                self.audit(
                    actor="system",
                    entity_id=entity_id,
                    entity=entity,
                    decision="STALE",
                    reason="hash-change",
                    tenant_id=tenant_id,
                )
            return rec