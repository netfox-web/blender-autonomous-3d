"""Unified AI Physical Product OS V1.

Adapter/registry over existing Twin/Queue/DAM/Engineering. Does not rewrite CabinetSpec.
"""

from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fox3d.acrylic import ACRYLIC_FAMILIES, AcrylicFactory
from fox3d.infra import utcnow
from fox3d.kd import FLATPACK_PRODUCT_TYPES, auto_redesign_candidates, common_hardware_optimizer, common_panel_optimizer
from fox3d.packaging import BOX_FAMILIES, StructuralPackagingFactory
from fox3d.release import (
    atomic_write_tenant_json,
    file_sig,
    find_legacy_tenant_file,
    read_validated_tenant_json,
    reentrant_store_lock,
    safe_tenant_filename,
    sorted_tenant_json_paths,
)
from fox3d.retail_fixture import FIXTURE_FAMILIES, RetailFixtureFactory

PHYSICAL_FAMILIES = {
    "KD_FURNITURE": {"kinds": list(FLATPACK_PRODUCT_TYPES), "pipeline": ["CabinetSpec", "BOM", "NestingV3", "WasteV2", "Packing", "Approval"]},
    "RETAIL_FIXTURE": {"kinds": list(FIXTURE_FAMILIES), "pipeline": ["RETAIL_DISPLAY", "Planogram", "BOM", "NestingV3", "Packing", "Approval"]},
    "PACKAGING_STRUCTURE": {"kinds": list(BOX_FAMILIES), "pipeline": ["PackagingEngineering", "Dieline", "NestingV3", "FoldPreview", "Approval"]},
    "ACRYLIC_SHEET": {"kinds": list(ACRYLIC_FAMILIES), "pipeline": ["AcrylicParts", "NestingV3", "CutBend", "Packing", "Approval"]},
}


class PhysicalProductFamilyRegistry:
    def list(self) -> list[str]:
        return list(PHYSICAL_FAMILIES)

    def get(self, family: str) -> dict[str, Any]:
        rec: dict[str, Any] = dict(PHYSICAL_FAMILIES[family])
        rec["family"] = family
        rec["reuses"] = ["TwinStore", "JobQueue", "DAM", "EngineeringRuleEngine", "NestingStrategyRegistry"]
        rec["rewritesCabinetSpec"] = False
        return rec


MAX_BENCHMARKS_PER_TENANT = 20


class PhysicalProductOS:
    def __init__(self, platform: Any = None, *, root: Path | None = None) -> None:
        self.platform = platform
        plat_root = getattr(platform, "root", None)
        base_root = Path(root) if root else (
            Path(plat_root) / "physical_os" if plat_root is not None else None
        )
        self.root = base_root
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
        self.families = PhysicalProductFamilyRegistry()
        self.retail = RetailFixtureFactory(platform)
        self.packaging = StructuralPackagingFactory(platform)
        self.acrylic = AcrylicFactory(platform)
        self.approvals: dict[tuple[str, str], dict[str, Any]] = {}
        self.benchmarks: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._lock_state: dict[str, int] = {"depth": 0}
        self._sigs: dict[str, tuple[int, int, int, int] | None] = {}
        if self.root is not None:
            self.load()

    def _lock_path(self) -> Path | None:
        return (self.root / "physical_os.lock") if self.root is not None else None

    @contextmanager
    def _locked_store(self) -> Iterator[None]:
        with reentrant_store_lock(self._lock, self._lock_state, self._lock_path()):
            yield

    def _normalize_tenant(self, tenant_id: str | None) -> str:
        tid = str(tenant_id or "default").strip()
        return tid or "default"

    def _tenant_path(self, tenant_id: str) -> Path | None:
        if self.root is None:
            return None
        return self.root / f"{safe_tenant_filename(self._normalize_tenant(tenant_id))}.json"

    def _candidate_dirs(self) -> list[Path]:
        if self.root is None:
            return []
        dirs = [self.root]
        alt = self.root.parent / "physical"
        if alt != self.root and alt.is_dir():
            dirs.append(alt)
        return dirs

    def _parse_tenant_file(
        self, path: Path
    ) -> tuple[str, dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
        payload = read_validated_tenant_json(path, required_lists=("approvals",))
        tid = str(payload["tenantId"])
        approvals: dict[tuple[str, str], dict[str, Any]] = {}
        for rec in payload["approvals"]:
            if not isinstance(rec, dict):
                raise ValueError(f"corrupt state file {path}: approval must be an object")
            eid = rec.get("entityId")
            actor = rec.get("actor")
            approved_at = rec.get("approvedAt")
            if not isinstance(eid, str) or not eid.strip():
                raise ValueError(f"corrupt state file {path}: approval missing entityId")
            if rec.get("tenantId") != tid:
                raise ValueError(f"corrupt state file {path}: approval tenantId mismatch")
            if not isinstance(actor, str) or not actor.strip():
                raise ValueError(f"corrupt state file {path}: approval missing actor")
            if not isinstance(approved_at, str) or not approved_at.strip():
                raise ValueError(f"corrupt state file {path}: approval missing approvedAt")
            approvals[(tid, eid)] = rec
        benchmarks: list[dict[str, Any]] = []
        if "benchmarks" in payload:
            raw_bench = payload["benchmarks"]
            if not isinstance(raw_bench, list):
                raise ValueError(f"corrupt state file {path}: invalid benchmarks list")
            for b in raw_bench:
                if not isinstance(b, dict) or b.get("tenantId") != tid:
                    raise ValueError(f"corrupt state file {path}: invalid benchmark entry")
                benchmarks.append(b)
        return tid, approvals, benchmarks

    def load(self) -> None:
        if self.root is None:
            return
        with self._locked_store():
            new_approvals: dict[tuple[str, str], dict[str, Any]] = {}
            new_benchmarks: list[dict[str, Any]] = []
            new_sigs: dict[str, tuple[int, int, int, int] | None] = {}
            legacy_to_migrate: list[tuple[Path, str]] = []
            for folder in self._candidate_dirs():
                for path in sorted_tenant_json_paths(folder):
                    tid, approvals, benchmarks = self._parse_tenant_file(path)
                    new_approvals.update(approvals)
                    new_benchmarks.extend(benchmarks)
                    if folder == self.root:
                        canonical = self._tenant_path(tid)
                        if canonical is not None and path != canonical:
                            legacy_to_migrate.append((path, tid))
                        else:
                            new_sigs[tid] = file_sig(path)
            self.approvals.clear()
            self.approvals.update(new_approvals)
            self.benchmarks[:] = new_benchmarks
            self._sigs.clear()
            self._sigs.update(new_sigs)
            for legacy_path, tid in legacy_to_migrate:
                self._persist_tenant_unlocked(tid)
                if legacy_path.exists() and legacy_path != self._tenant_path(tid):
                    legacy_path.unlink(missing_ok=True)

    def _sync_tenant(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        with self._locked_store():
            sig = file_sig(path)
            if sig is None:
                legacy_path = find_legacy_tenant_file(self.root, tid)
                if legacy_path is not None:
                    _, approvals, benchmarks = self._parse_tenant_file(legacy_path)
                    for key in [k for k in self.approvals if k[0] == tid]:
                        self.approvals.pop(key, None)
                    self.approvals.update(approvals)
                    other_bench = [b for b in self.benchmarks if b.get("tenantId") != tid]
                    self.benchmarks[:] = [*other_bench, *benchmarks]
                    self._persist_tenant_unlocked(tid)
                    if legacy_path.exists() and legacy_path != path:
                        legacy_path.unlink(missing_ok=True)
                    return
                if tid in self._sigs:
                    for key in [k for k in self.approvals if k[0] == tid]:
                        self.approvals.pop(key, None)
                    self.benchmarks[:] = [b for b in self.benchmarks if b.get("tenantId") != tid]
                    self._sigs.pop(tid, None)
                return
            if self._sigs.get(tid) == sig:
                return
            _, approvals, benchmarks = self._parse_tenant_file(path)
            for key in [k for k in self.approvals if k[0] == tid]:
                self.approvals.pop(key, None)
            self.approvals.update(approvals)
            other_bench = [b for b in self.benchmarks if b.get("tenantId") != tid]
            self.benchmarks[:] = [*other_bench, *benchmarks]
            self._sigs[tid] = file_sig(path)

    def _persist_tenant_unlocked(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        tenant_approvals = [rec for (t, _), rec in self.approvals.items() if t == tid]
        tenant_benchmarks = [b for b in self.benchmarks if b.get("tenantId") == tid]
        if tenant_approvals or tenant_benchmarks:
            atomic_write_tenant_json(
                path,
                {
                    "tenantId": tid,
                    "approvals": tenant_approvals,
                    "benchmarks": tenant_benchmarks,
                },
            )
            self._sigs[tid] = file_sig(path)
        else:
            path.unlink(missing_ok=True)
            self._sigs.pop(tid, None)

    def persist(self, *, tenant_id: str | None = None) -> None:
        if self.root is None:
            return
        with self._locked_store():
            if tenant_id is not None:
                self._persist_tenant_unlocked(tenant_id)
                return
            tenants = {t for (t, _) in self.approvals} | {
                self._normalize_tenant(b.get("tenantId")) for b in self.benchmarks
            }
            for tid in sorted(tenants):
                self._persist_tenant_unlocked(tid)

    def find_entity(self, entity_id: str, *, tenant_id: str) -> dict[str, Any] | None:
        tid = self._normalize_tenant(tenant_id)
        for factory in (self.acrylic, self.packaging, self.retail):
            factory._sync_tenant(tid)
            item = factory.items.get(entity_id)
            if item is not None:
                return item if self._normalize_tenant(item.get("tenantId")) == tid else None
        pkg_engine = getattr(self.platform, "packaging", None)
        if pkg_engine is not None and pkg_engine is not self.packaging and hasattr(pkg_engine, "items"):
            if hasattr(pkg_engine, "_sync_tenant"):
                pkg_engine._sync_tenant(tid)
            item = pkg_engine.items.get(entity_id)
            if item is not None:
                return item if self._normalize_tenant(item.get("tenantId")) == tid else None
        kd = getattr(self.platform, "kd", None)
        if kd is not None:
            kd._sync_tenant(tid)
            cand = kd.candidates.get(entity_id)
            if cand is not None:
                return cand if kd._candidate_tenant(cand) == tid else None
            batch = kd.batches.get(entity_id)
            if batch is not None:
                return batch if self._normalize_tenant(batch.get("tenantId")) == tid else None
        return None

    def is_foreign_entity(self, entity_id: str, *, tenant_id: str) -> bool:
        tid = self._normalize_tenant(tenant_id)
        if self.find_entity(entity_id, tenant_id=tid) is not None:
            return False
        for factory in (self.acrylic, self.packaging, self.retail):
            item = factory.items.get(entity_id)
            if item is not None and self._normalize_tenant(item.get("tenantId")) != tid:
                return True
        pkg_engine = getattr(self.platform, "packaging", None)
        if pkg_engine is not None and pkg_engine is not self.packaging and hasattr(pkg_engine, "items"):
            item = pkg_engine.items.get(entity_id)
            if item is not None and self._normalize_tenant(item.get("tenantId")) != tid:
                return True
        kd = getattr(self.platform, "kd", None)
        if kd is not None:
            cand = kd.candidates.get(entity_id)
            if cand is not None and kd._candidate_tenant(cand) != tid:
                return True
            batch = kd.batches.get(entity_id)
            if batch is not None and self._normalize_tenant(batch.get("tenantId")) != tid:
                return True
        return False

    def record_benchmark(
        self,
        result: dict[str, Any],
        *,
        tenant_id: str,
        max_per_tenant: int = MAX_BENCHMARKS_PER_TENANT,
    ) -> dict[str, Any]:
        tid = self._normalize_tenant(tenant_id)
        entry = {**result, "tenantId": tid}
        with self._locked_store():
            self._sync_tenant(tid)
            other = [b for b in self.benchmarks if b.get("tenantId") != tid]
            same = [b for b in self.benchmarks if b.get("tenantId") == tid]
            if max_per_tenant <= 0:
                self.benchmarks[:] = other
                self._persist_tenant_unlocked(tid)
                return entry
            kept_same = same[-(max_per_tenant - 1) :] if max_per_tenant > 1 else []
            self.benchmarks[:] = [*other, *kept_same, entry]
            self._persist_tenant_unlocked(tid)
            return entry

    def reverse_rd(self, *, tenant_id: str, sheets: list[dict[str, Any]] | None = None, remnants: list[dict[str, Any]] | None = None, lots: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        remnants = remnants or self.platform.remnants.available(tenant_id=tenant_id)
        max_l = max((float(r.get("w") or 0) for r in remnants), default=800)
        max_w = max((float(r.get("h") or 0) for r in remnants), default=600)
        kd = self.platform.kd.reverse_from_remnants(tenant_id=tenant_id, remnants=remnants or [{"w": max_l, "h": max_w, "thickness": 18, "materialCode": "WOOD_WHITE"}])
        scored = []
        for item in kd:
            rec = self.platform.kd.candidates.get(item["productId"]) or self.platform.kd.build_sku(tenant_id=tenant_id, kind=item["kind"], render=False)
            nest = rec.get("nesting") or {}
            pack = rec.get("packing") or {}
            scored.append(
                {
                    **item,
                    "family": "KD_FURNITURE",
                    "materialUtilization": nest.get("utilizationRatio"),
                    "trueScrap": nest.get("trueWasteRatio"),
                    "remnantConsumption": nest.get("remnantConsumedArea") or 0,
                    "commonParts": (rec.get("commonParts") or {}).get("commonPartRatio"),
                    "packing": {"L": pack.get("length"), "W": pack.get("width"), "H": pack.get("height")},
                    "assembly": (rec.get("difficulty") or {}).get("score"),
                    "estimatedMargin": (rec.get("landed") or {}).get("grossMargin"),
                    "market": "MARKET_UNVERIFIED",
                    "demand": "MOCK",
                }
            )
        scored.sort(key=lambda r: (-(r.get("materialUtilization") or 0), r.get("trueScrap") or 1))
        return {
            "tenantId": tenant_id,
            "lots": [l.get("lotId") for l in (lots or [])],
            "newSheets": sheets or [],
            "candidates": scored,
            "market": "MARKET_UNVERIFIED",
            "note": "Demand provider is MOCK — not claimed as bestselling.",
        }

    def approve(self, *, entity_id: str, actor: str, tenant_id: str = "default", kind: str = "product", entity: dict[str, Any] | None = None) -> dict[str, Any]:
        tid = self._normalize_tenant(tenant_id)
        with self._locked_store():
            self._sync_tenant(tid)
            found = self.find_entity(entity_id, tenant_id=tid)
            if found is None:
                raise KeyError(entity_id)
            if isinstance(entity, dict) and entity.get("tenantId") not in (None, "", tid):
                raise KeyError(entity_id)
            key = (tid, entity_id)
            existing = self.approvals.get(key)
            if existing is not None:
                return copy.deepcopy(existing)
            target_entity = entity if isinstance(entity, dict) and entity else found
            approved_at = utcnow().isoformat()
            rec: dict[str, Any] = {
                "entityId": entity_id,
                "tenantId": tid,
                "kind": kind,
                "actor": actor,
                "approvedAt": approved_at,
                "status": "WAITING_APPROVAL",
                "liveMachineControl": False,
                "forbidden": ["LIVE_CNC", "LIVE_LASER", "APPROVED_FOR_PRODUCTION"],
            }
            gate = getattr(self.platform, "release", None)
            if gate is not None:
                rec["audit"] = gate.audit(
                    actor=actor,
                    tenant_id=tid,
                    entity_id=entity_id,
                    entity=target_entity,
                    decision="WAITING_APPROVAL",
                    reason="human-approval-gate",
                )
                rec["approvedAt"] = rec["audit"]["approvedAt"]
                rec["hashes"] = rec["audit"].get("hashes")
            self.approvals[key] = rec
            kd = getattr(self.platform, "kd", None)
            if kd is not None and entity_id in kd.candidates:
                cand = kd.candidates.get(entity_id)
                if isinstance(cand, dict) and kd._candidate_tenant(cand) == tid:
                    updated_cand = dict(cand)
                    updated_cand["physicalApproved"] = True
                    kd.candidates[entity_id] = updated_cand
                    kd._mark_or_persist(tid)
            self._persist_tenant_unlocked(tid)
            return copy.deepcopy(rec)

    def readiness(self, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        from fox3d.readiness import scoped_readiness

        ev = evidence or {}
        matrix = scoped_readiness(evidence=ev)
        matrix["kdFurnitureE2E"] = {"label": "REAL" if ev.get("kd") else "PARTIAL", "ready": bool(ev.get("kd") or matrix.get("kdPrototypeReady"))}
        matrix["retailFixtureE2E"] = {"label": "REAL" if ev.get("retail") else "PARTIAL", "ready": bool(ev.get("retail") or matrix.get("retailPrototypeReady"))}
        matrix["packagingOrAcrylicE2E"] = {"label": "REAL" if ev.get("pack_or_acr") else "PARTIAL", "ready": bool(ev.get("pack_or_acr"))}
        matrix["estimatedCost"] = {"label": "CONFIG_ESTIMATE", "ready": True}
        matrix["realProviderCost"] = {"label": "BLOCKED", "ready": False}
        matrix["vision"] = {"label": "MOCK", "ready": False}
        matrix["demand"] = {"label": "MOCK", "ready": False}
        matrix["video"] = {"label": "MOCK", "ready": False}
        matrix["osSandbox"] = {"label": "PARTIAL", "ready": False}
        matrix["liveMachineControl"] = {"label": "BLOCKED", "ready": False}
        matrix["structuralCertification"] = {"label": "PARTIAL", "ready": False}
        matrix["electricalCompliance"] = {"label": "BLOCKED", "ready": False}
        matrix["ciEvidence"] = {"label": "MOCK" if not ev.get("ci") else "REAL", "ready": bool(ev.get("ci")), "note": "pytest mock suite only unless GitHub GREEN recorded"}
        matrix["productionReadyScope"] = "physicalProductOsV2-prototype-boundary"
        matrix["globalProductionReady"] = False
        return matrix

    def kd_optimized_board(self, *, tenant_id: str, count: int = 10) -> dict[str, Any]:
        kinds = ["DESK_RISER", "BEDSIDE_CABINET", "OPEN_SHELF", "PET_FURNITURE", "STORAGE_BENCH", "MOBILE_SIDE_TABLE", "NARROW_BOOKCASE", "APPLIANCE_RACK", "STUDENT_DESK", "GARMENT_RACK"]
        rows = []
        recs = []
        with self.platform.kd.batch_write(tenant_id=tenant_id):
            for kind in kinds[:count]:
                before = self.platform.kd.build_sku(tenant_id=tenant_id, kind=kind, render=False)
                recs.append(before)
                hw = common_hardware_optimizer([before])
                panel = common_panel_optimizer(before)
                redesign = auto_redesign_candidates(self.platform.cabinets, before, tenant_id=tenant_id)
                after = before
                if redesign.get("triggered") and redesign.get("candidates"):
                    c0 = redesign["candidates"][0]
                    after = self.platform.kd.build_sku(tenant_id=tenant_id, kind=kind, width=c0["width"], depth=c0["depth"], height=c0["height"], render=False)
                rows.append(
                    {
                        "kind": kind,
                        "before": {
                            "waste": (before.get("nesting") or {}).get("trueWasteRatio"),
                            "carton": {"L": before["packing"]["length"], "W": before["packing"]["width"], "H": before["packing"]["height"]},
                            "weight": before["weight"]["grossKg"],
                            "commonPartRatio": before["commonParts"]["commonPartRatio"],
                            "assembly": before["difficulty"]["score"],
                        },
                        "after": {
                            "waste": (after.get("nesting") or {}).get("trueWasteRatio"),
                            "carton": {"L": after["packing"]["length"], "W": after["packing"]["width"], "H": after["packing"]["height"]},
                            "weight": after["weight"]["grossKg"],
                            "commonPartRatio": after["commonParts"]["commonPartRatio"],
                            "assembly": after["difficulty"]["score"],
                        },
                        "commonHardwareRatio": hw["commonHardwareRatio"],
                        "commonPanel": panel["commonPanelRatio"],
                        "redesignTriggered": bool(redesign.get("triggered")),
                        "demand": "MOCK",
                    }
                )
        family_hw = common_hardware_optimizer(recs)
        return {
            "candidates": rows,
            "familyHardware": family_hw,
            "demand": "MOCK",
            "note": "Not claimed as market bestsellers.",
        }
