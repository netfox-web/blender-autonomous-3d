"""Immutable Manufacturing Release Package V1.

Human-executable packet, not machine control. APPROVED_FOR_MANUAL_RELEASE
is not LIVE_CNC. Reuses existing BOM / nesting / packing SoT.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import emit
from fox3d.manufacturing import HARDWARE_REGISTRY, NestingEngine, edge_banding_edges, edge_banding_length_mm

RELEASE_STATES = (
    "DRAFT",
    "VALIDATED",
    "WAITING_APPROVAL",
    "APPROVED_FOR_MANUAL_RELEASE",
    "RELEASED_FOR_MANUAL_EXECUTION",
    "STALE",
    "CANCELLED",
)
FORBIDDEN_STATES = frozenset({"LIVE_CNC", "LIVE_LASER", "APPROVED_FOR_PRODUCTION", "APPROVED_FOR_MACHINE"})
HASH_KEYS = ("engineeringHash", "bomHash", "nestingHash", "packagingHash", "materialSnapshotHash", "costPolicyHash", "qcPlanHash")

FAMILY_STEPS = {
    "KD_FURNITURE": ["panel_cutting", "edge_banding", "drilling_routing", "hardware_prep", "assembly", "surface_inspection", "packaging"],
    "RETAIL_FIXTURE": ["panel_cutting", "edge_banding", "drilling_routing", "hardware_prep", "fixture_assembly", "load_label", "packaging"],
    "PACKAGING_STRUCTURE": ["blank_cutting", "creasing", "folding", "gluing", "print_inspection", "packing"],
    "ACRYLIC_SHEET": ["sheet_cutting", "edge_finishing", "bend", "assembly", "inspection", "packaging"],
}


def _now() -> str:
    return utcnow().isoformat()


def _csv(rows: list[dict[str, Any]], fields: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fields})
    return buf.getvalue()


def _digest(text: str) -> dict[str, Any]:
    data = text.encode("utf-8")
    return {"sha256": sha256_bytes(data), "bytes": len(data)}


def product_snapshot(rec: dict[str, Any], *, family: str | None = None) -> dict[str, Any]:
    """Normalize KD / retail / packaging / acrylic SoT into a release input."""
    spec = rec.get("spec") if isinstance(rec.get("spec"), dict) else {}
    eng = rec.get("engineering") if isinstance(rec.get("engineering"), dict) else {}
    packing = rec.get("packing") or rec.get("packaging") or {}
    nesting = rec.get("nesting") or {}
    bom = rec.get("bom") or {}
    fam = family or rec.get("family") or rec.get("productFamily") or spec.get("physicalProductFamily") or "KD_FURNITURE"
    product_id = rec.get("productId") or rec.get("fixtureId") or rec.get("packageId") or spec.get("productId") or new_id()
    snap = {
        "productId": product_id,
        "productVersion": rec.get("productVersion") or spec.get("revision") or bom.get("revision") or 1,
        "productFamily": fam,
        "kind": rec.get("kind") or rec.get("family") or spec.get("productType") or spec.get("fixtureFamily") or eng.get("family"),
        "tenantId": rec.get("tenantId") or "default",
        "engineeringHash": rec.get("engineeringHash") or eng.get("engineeringHash") or (rec.get("lineage") or {}).get("engineeringHash"),
        "bom": bom,
        "bomHash": rec.get("bomHash") or bom.get("bomHash") or (rec.get("lineage") or {}).get("bomHash"),
        "nesting": nesting,
        "nestingHash": rec.get("nestingHash") or nesting.get("nestingHash") or (rec.get("lineage") or {}).get("nestingHash"),
        "packing": packing,
        "packagingHash": rec.get("packagingHash") or packing.get("packagingHash") or (rec.get("lineage") or {}).get("packagingHash"),
        "quote": rec.get("quote") or rec.get("landed") or rec.get("cost") or {},
        "instructions": rec.get("instructions") or {},
        "planogram": rec.get("planogram"),
        "capacity": rec.get("capacity"),
        "lighting": rec.get("lighting"),
        "cutBend": rec.get("cutBend"),
        "sheet": rec.get("sheet"),
        "dimensions": rec.get("dimensions") or spec,
        "spec": spec,
        "engineering": eng,
        "materialSnapshotIds": list(rec.get("materialSnapshotIds") or []),
        "costPolicyHash": rec.get("costPolicyHash") or stable_hash((rec.get("quote") or rec.get("landed") or rec.get("cost") or {}).get("breakdown") or rec.get("quote") or rec.get("cost") or {}),
        "liveMachineControl": False,
    }
    snap["materialSnapshotHash"] = stable_hash(snap["materialSnapshotIds"] + [ (rec.get("sheet") or {}).get("sku"), (nesting.get("sheetSku")) ])
    return snap


def _bound_hashes(snap: dict[str, Any]) -> dict[str, str | None]:
    return {k: snap.get(k) for k in HASH_KEYS}


class ManufacturingReleaseService:
    def __init__(self, dam: Any | None = None, root: Path | None = None) -> None:
        self.dam = dam
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self.releases: dict[str, dict[str, Any]] = {}
        self.packets: dict[str, dict[str, str]] = {}
        self._idem: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "releases.json") or {}
        self.releases = {r["releaseId"]: r for r in payload.get("releases") or []}
        self._idem = dict(payload.get("idem") or {})
        self.packets = dict(payload.get("packets") or {})

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(
            self.root / "releases.json",
            {"releases": list(self.releases.values()), "idem": self._idem, "packets": self.packets},
        )

    def get(self, release_id: str) -> dict[str, Any]:
        return self.releases[release_id]

    def create(
        self,
        snap: dict[str, Any],
        *,
        tenant_id: str,
        created_by: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        raw_key = idempotency_key or f"{snap['productId']}:{snap['productVersion']}:{snap.get('engineeringHash')}"
        key = f"{tenant_id}::rel::{raw_key}"
        if key in self._idem:
            existing = self.releases[self._idem[key]]
            if existing.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: manufacturing release")
            return existing
        bound = _bound_hashes(snap)
        rec = {
            "releaseId": new_id(),
            "tenantId": tenant_id,
            "productId": snap["productId"],
            "productVersion": snap["productVersion"],
            "productFamily": snap["productFamily"],
            "kind": snap.get("kind"),
            "createdBy": created_by,
            "approvedBy": None,
            "releasedAt": None,
            "createdAt": _now(),
            "status": "DRAFT",
            "liveMachineControl": False,
            "equalsLiveCnc": False,
            "equalsLiveLaser": False,
            "note": "APPROVED_FOR_MANUAL_RELEASE is not LIVE_CNC",
            "hashes": bound,
            "engineeringHash": bound["engineeringHash"],
            "bomHash": bound["bomHash"],
            "nestingHash": bound["nestingHash"],
            "packagingHash": bound["packagingHash"],
            "materialSnapshotHash": bound["materialSnapshotHash"],
            "costPolicyHash": bound["costPolicyHash"],
            "approvalAuditHash": None,
            "frozenCost": None,
            "stale": False,
            "immutable": False,
            "snapshot": snap,
        }
        rec["releaseHash"] = self._release_hash(rec)
        self.releases[rec["releaseId"]] = rec
        self._idem[key] = rec["releaseId"]
        try:
            emit(
                self,
                "release.create",
                tenant_id=tenant_id,
                aggregate_type="ManufacturingRelease",
                aggregate_id=rec["releaseId"],
                actor=created_by,
                payload={"status": "DRAFT"},
                release_hash=rec["releaseHash"],
                semantic_key=key,
            )
        except Exception:
            if self.root:
                self.load()
            else:
                del self.releases[rec["releaseId"]]
                del self._idem[key]
            raise
        return rec

    def _release_hash(self, rec: dict[str, Any]) -> str:
        return stable_hash(
            {
                "tenantId": rec["tenantId"],
                "productId": rec["productId"],
                "productVersion": rec["productVersion"],
                "productFamily": rec["productFamily"],
                "hashes": rec["hashes"],
            }
        )

    def validate(self, release_id: str) -> dict[str, Any]:
        rec = self.releases[release_id]
        if rec["status"] in {"STALE", "CANCELLED"}:
            raise PermissionError(f"cannot validate {rec['status']}")
        snap = rec["snapshot"]
        missing = [k for k in ("engineeringHash", "bomHash") if not snap.get(k)]
        if missing:
            raise ValueError(f"missing hashes: {missing}")
        from fox3d.qc import plan_for_family, plan_hash

        plan = plan_for_family(rec.get("productFamily") or "KD_FURNITURE")
        rec["snapshot"]["qcPlan"] = plan
        rec["qcPlanHash"] = plan_hash(plan)
        rec["hashes"]["qcPlanHash"] = rec["qcPlanHash"]
        rec["snapshot"]["qcPlanHash"] = rec["qcPlanHash"]
        artifacts = self._build_packet(rec)
        self.packets[release_id] = artifacts
        rec["checksumManifest"] = self._checksums(artifacts)
        rec["status"] = "VALIDATED"
        rec["validatedAt"] = _now()
        rec["releaseHash"] = self._release_hash(rec)
        emit(
            self,
            "release.validate",
            tenant_id=rec["tenantId"],
            aggregate_type="ManufacturingRelease",
            aggregate_id=rec["releaseId"],
            actor="system",
            payload={"status": "VALIDATED"},
            release_hash=rec["releaseHash"],
            semantic_key=f"{rec['tenantId']}::rel-validate::{rec['releaseId']}",
        )
        return rec

    def submit_approval(self, release_id: str, *, actor: str) -> dict[str, Any]:
        rec = self.releases[release_id]
        if rec["status"] not in {"VALIDATED", "WAITING_APPROVAL"}:
            raise PermissionError(rec["status"])
        rec["status"] = "WAITING_APPROVAL"
        rec["submittedBy"] = actor
        rec["submittedAt"] = _now()
        emit(
            self,
            "release.submit_approval",
            tenant_id=rec["tenantId"],
            aggregate_type="ManufacturingRelease",
            aggregate_id=rec["releaseId"],
            actor=actor,
            payload={"status": "WAITING_APPROVAL"},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::rel-submit::{rec['releaseId']}",
        )
        return rec

    def approve(
        self,
        release_id: str,
        *,
        actor: str,
        audit_hash: str | None = None,
        expected_release_hash: str | None = None,
    ) -> dict[str, Any]:
        rec = self.releases[release_id]
        if rec["status"] != "WAITING_APPROVAL":
            raise PermissionError("Human Approval Gate: WAITING_APPROVAL required")
        if rec["status"] in FORBIDDEN_STATES:
            raise PermissionError("LIVE machine states forbidden")
        rec["status"] = "APPROVED_FOR_MANUAL_RELEASE"
        rec["approvedBy"] = actor
        rec["approvedAt"] = _now()
        rec["releaseHash"] = self._release_hash(rec)
        if expected_release_hash and expected_release_hash != rec["releaseHash"]:
            raise PermissionError("approval for release A cannot authorize release B")
        rec["approvedReleaseHash"] = rec["releaseHash"]
        rec["approvalAuditHash"] = audit_hash or stable_hash(
            {"actor": actor, "releaseId": release_id, "releaseHash": rec["releaseHash"], "at": rec["approvedAt"]}
        )
        rec["immutable"] = True
        rec["frozenCost"] = self._freeze_cost(rec["snapshot"])
        rec["equalsLiveCnc"] = False
        rec["liveMachineControl"] = False
        emit(
            self,
            "release.approve",
            tenant_id=rec["tenantId"],
            aggregate_type="ManufacturingRelease",
            aggregate_id=rec["releaseId"],
            actor=actor,
            payload={"status": rec["status"], "approvedReleaseHash": rec.get("approvedReleaseHash")},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::rel-approve::{rec['releaseId']}",
        )
        return rec

    def release_for_manual_execution(self, release_id: str, *, actor: str) -> dict[str, Any]:
        rec = self.releases[release_id]
        if rec["status"] != "APPROVED_FOR_MANUAL_RELEASE":
            raise PermissionError(rec["status"])
        if rec.get("stale"):
            raise PermissionError("stale release cannot execute")
        rec["status"] = "RELEASED_FOR_MANUAL_EXECUTION"
        rec["releasedAt"] = _now()
        rec["releasedBy"] = actor
        rec["liveMachineControl"] = False
        emit(
            self,
            "release.release_for_manual_execution",
            tenant_id=rec["tenantId"],
            aggregate_type="ManufacturingRelease",
            aggregate_id=rec["releaseId"],
            actor=actor,
            payload={"status": rec["status"]},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::rel-exec::{rec['releaseId']}",
        )
        return rec

    def cancel(self, release_id: str, *, actor: str) -> dict[str, Any]:
        rec = self.releases[release_id]
        rec["status"] = "CANCELLED"
        rec["cancelledBy"] = actor
        rec["cancelledAt"] = _now()
        rec["immutable"] = True
        emit(
            self,
            "release.cancel",
            tenant_id=rec["tenantId"],
            aggregate_type="ManufacturingRelease",
            aggregate_id=rec["releaseId"],
            actor=actor,
            payload={"status": "CANCELLED"},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::rel-cancel::{rec['releaseId']}",
        )
        return rec

    def refresh_stale(self, release_id: str, current: dict[str, Any]) -> dict[str, Any]:
        rec = self.releases[release_id]
        bound = rec.get("hashes") or {}
        now_hashes = _bound_hashes(current if "engineeringHash" in current else product_snapshot(current, family=rec.get("productFamily")))
        stale = False
        for key in HASH_KEYS:
            if bound.get(key) and now_hashes.get(key) and str(bound[key]) != str(now_hashes[key]):
                stale = True
        if stale:
            rec = dict(rec)
            rec["stale"] = True
            rec["status"] = "STALE"
            rec["staleReason"] = "upstream engineering/BOM/material/nesting/packaging/cost-policy hash changed"
            rec["staleAt"] = _now()
            self.releases[release_id] = rec
            emit(
                self,
                "release.stale",
                tenant_id=rec["tenantId"],
                aggregate_type="ManufacturingRelease",
                aggregate_id=rec["releaseId"],
                actor="system",
                payload={"status": "STALE"},
                release_hash=rec.get("releaseHash"),
                semantic_key=f"{rec['tenantId']}::rel-stale::{rec['releaseId']}",
            )
        return rec

    def is_stale(self, release_id: str, current: dict[str, Any]) -> bool:
        return bool(self.refresh_stale(release_id, current).get("stale"))

    def diff(self, old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
        keys = ("engineeringHash", "bomHash", "nestingHash", "packagingHash", "costPolicyHash", "qcPlanHash")
        changed = {}
        for k in keys:
            a, b = old.get(k) or (old.get("hashes") or {}).get(k), new.get(k) or (new.get("hashes") or {}).get(k)
            if str(a or "") != str(b or ""):
                changed[k] = {"from": a, "to": b}
        return {"changed": changed, "unchanged": [k for k in keys if k not in changed]}

    def supersede(self, release_id: str, new_snap: dict[str, Any], *, actor: str, tenant_id: str) -> dict[str, Any]:
        old = self.releases[release_id]
        new = self.create(new_snap, tenant_id=tenant_id, created_by=actor, idempotency_key=f"{tenant_id}:supersede:{new_id()}")
        old["status"] = "SUPERSEDED"
        old["stale"] = True
        old["supersededBy"] = new["releaseId"]
        old["supersededAt"] = _now()
        new["supersedes"] = old["releaseId"]
        new["supersedesHash"] = old.get("releaseHash")
        emit(
            self,
            "release.supersede",
            tenant_id=tenant_id,
            aggregate_type="ManufacturingRelease",
            aggregate_id=old["releaseId"],
            actor=actor,
            payload={"supersededBy": new["releaseId"]},
            release_hash=old.get("releaseHash"),
            semantic_key=f"{tenant_id}::rel-supersede::{old['releaseId']}",
        )
        return {"old": old, "new": new, "diff": self.diff(old, new)}

    def packet(self, release_id: str) -> dict[str, str]:
        if release_id not in self.packets:
            rec = self.releases[release_id]
            self.packets[release_id] = self._build_packet(rec)
            rec["checksumManifest"] = self._checksums(self.packets[release_id])
        return self.packets[release_id]

    def verify(self, release_id: str) -> dict[str, Any]:
        rec = self.releases[release_id]
        artifacts = self.packet(release_id)
        expected = rec.get("checksumManifest") or self._checksums(artifacts)
        errors: list[str] = []
        for name, text in artifacts.items():
            got = _digest(text)
            want = (expected.get("files") or {}).get(name)
            if not want:
                errors.append(f"missing_manifest:{name}")
                continue
            if got["sha256"] != want["sha256"] or got["bytes"] != want["bytes"]:
                errors.append(f"tamper:{name}")
        extra = set((expected.get("files") or {})) - set(artifacts)
        if extra:
            errors.append(f"extra_manifest:{sorted(extra)}")
        return {
            "ok": not errors,
            "errors": errors,
            "releaseHash": rec.get("releaseHash"),
            "status": rec.get("status"),
            "liveMachineControl": False,
            "label": "REAL" if not errors else "BLOCKED",
        }

    def tamper(self, release_id: str, name: str, text: str) -> None:
        """Test helper: mutate a frozen artifact after approval."""
        self.packets[release_id][name] = text

    def _freeze_cost(self, snap: dict[str, Any]) -> dict[str, Any]:
        quote = snap.get("quote") or {}
        breakdown = quote.get("breakdown") or {}
        estimated = quote.get("estimatedCost") or quote.get("unitCost") or quote.get("unitLandedCost") or 0
        frozen = {
            "estimatedCost": float(estimated or 0),
            "breakdown": dict(breakdown) if isinstance(breakdown, dict) else {},
            "currency": quote.get("currency") or "TWD",
            "frozenAt": _now(),
            "source": "RELEASE_FREEZE",
            "recomputeForbidden": True,
        }
        frozen["freezeHash"] = stable_hash(frozen)
        return frozen

    def _checksums(self, artifacts: dict[str, str]) -> dict[str, Any]:
        files = {name: _digest(text) for name, text in artifacts.items()}
        rec = {"files": files, "count": len(files)}
        rec["manifestHash"] = stable_hash(files)
        return rec

    def _build_packet(self, rec: dict[str, Any]) -> dict[str, str]:
        snap = rec["snapshot"]
        family = rec["productFamily"]
        bom = snap.get("bom") or {}
        lines = list(bom.get("lines") or [])
        nesting = dict(snap.get("nesting") or {})
        packing = snap.get("packing") or {}
        panels = [ln for ln in lines if not ln.get("hardware")]
        hardware = [ln for ln in lines if ln.get("hardware")]
        cut_rows = []
        for ln in panels:
            cut_rows.append(
                {
                    "partId": ln.get("partId") or ln.get("partName"),
                    "partName": ln.get("partName"),
                    "length": ln.get("length"),
                    "width": ln.get("width"),
                    "thickness": ln.get("thickness"),
                    "quantity": ln.get("quantity") or 1,
                    "grain": ln.get("grain") or ln.get("grainDirection") or "",
                }
            )
        edge_rows = []
        for ln in panels:
            edges = ln.get("edgeBandingEdges") or edge_banding_edges(str(ln.get("partType") or ln.get("role") or ""))
            length = float(ln.get("length") or 0)
            width = float(ln.get("width") or 0)
            mm = edge_banding_length_mm(length, width, edges)
            if mm > 0:
                edge_rows.append(
                    {
                        "partId": ln.get("partId") or ln.get("partName"),
                        "lengthMm": round(mm, 2),
                        "edges": json.dumps(edges),
                    }
                )
        hw_rows = []
        for ln in hardware:
            sku = str(ln.get("partId") or ln.get("sku") or ln.get("partName") or "")
            meta = HARDWARE_REGISTRY.get(sku) or {}
            hw_rows.append({"sku": sku, "quantity": ln.get("quantity") or 1, "category": meta.get("category") or "hardware"})
        steps = list((snap.get("instructions") or {}).get("steps") or [])
        if not steps:
            steps = [{"step": i + 1, "op": op, "machineCommand": False} for i, op in enumerate(FAMILY_STEPS.get(family, ["packaging"]))]
        carton = {
            "length": packing.get("length"),
            "width": packing.get("width"),
            "height": packing.get("height"),
            "panelCount": packing.get("panelCount") or len(panels),
            "source": packing.get("costSource") or "CONFIG_ESTIMATE",
        }
        svg = nesting.get("svg") or NestingEngine().to_svg(nesting) if nesting.get("sheetMm") else "<svg xmlns='http://www.w3.org/2000/svg'/>"
        dxf = nesting.get("dxfInterface") or (NestingEngine().to_dxf_interface(nesting) if nesting.get("sheetMm") else {"format": "DXF-lines", "liveMachineControl": False, "lines": []})
        dxf = {**dxf, "liveMachineControl": False}
        manifest = {
            "releaseId": rec["releaseId"],
            "releaseHash": rec["releaseHash"],
            "tenantId": rec["tenantId"],
            "productId": rec["productId"],
            "productVersion": rec["productVersion"],
            "productFamily": family,
            "kind": rec.get("kind"),
            "status": rec["status"],
            "hashes": rec["hashes"],
            "liveMachineControl": False,
            "equalsLiveCnc": False,
            "humanApprovalGate": True,
            "artifacts": [
                "release_manifest.json",
                "bom.csv",
                "cut_list.csv",
                "nesting.svg",
                "nesting.dxf.json",
                "edge_banding.csv",
                "hardware_pick.csv",
                "assembly_steps.json",
                "carton_packing.json",
                "checksums.json",
            ],
        }
        artifacts: dict[str, str] = {
            "release_manifest.json": json.dumps(manifest, indent=2, default=str),
            "bom.csv": _csv(lines, ["partId", "partName", "partType", "length", "width", "thickness", "quantity", "hardware", "skuId"]),
            "cut_list.csv": _csv(cut_rows, ["partId", "partName", "length", "width", "thickness", "quantity", "grain"]),
            "nesting.svg": svg,
            "nesting.dxf.json": json.dumps(dxf, indent=2, default=str),
            "edge_banding.csv": _csv(edge_rows, ["partId", "lengthMm", "edges"]),
            "hardware_pick.csv": _csv(hw_rows, ["sku", "quantity", "category"]),
            "assembly_steps.json": json.dumps({"steps": steps, "operatorInstructions": True, "machineCommands": False}, indent=2, default=str),
            "carton_packing.json": json.dumps(carton, indent=2, default=str),
        }
        if family == "RETAIL_FIXTURE":
            lighting = snap.get("lighting") or {}
            artifacts["planogram.json"] = json.dumps(snap.get("planogram") or {}, indent=2, default=str)
            artifacts["fixture_dims.json"] = json.dumps(
                {
                    "dimensions": snap.get("dimensions") or snap.get("spec"),
                    "capacity": snap.get("capacity"),
                    "loadEstimateLabel": (snap.get("capacity") or {}).get("label") or "PARTIAL",
                    "electricalCompliance": lighting.get("electricalCompliance") or "BLOCKED",
                },
                indent=2,
                default=str,
            )
            manifest["artifacts"].extend(["planogram.json", "fixture_dims.json"])
        if family == "PACKAGING_STRUCTURE":
            eng = snap.get("engineering") or {}
            dieline = eng.get("dieline") or {}
            artifacts["dieline.svg"] = _dieline_svg(dieline)
            artifacts["fold_sequence.json"] = json.dumps(
                {"fold": eng.get("fold") or dieline.get("fold") or [], "source": "ENGINEERING_ESTIMATE"},
                indent=2,
                default=str,
            )
            artifacts["board_grade.json"] = json.dumps(
                {
                    "sheet": snap.get("sheet") or eng.get("sheet"),
                    "bct": "ENGINEERING_ESTIMATE",
                    "certification": False,
                    "printPreflight": "PARTIAL",
                },
                indent=2,
                default=str,
            )
            manifest["artifacts"].extend(["dieline.svg", "fold_sequence.json", "board_grade.json"])
        if family == "ACRYLIC_SHEET":
            cut = snap.get("cutBend") or {}
            artifacts["cut_plan.json"] = json.dumps(
                {
                    "sheet": snap.get("sheet"),
                    "parts": (snap.get("bom") or {}).get("lines") or [],
                    "thickness": (snap.get("sheet") or {}).get("thickness"),
                    "finish": (snap.get("sheet") or {}).get("finish"),
                    "bend": cut.get("bends") or [],
                    "liveLaser": False,
                    "liveMachineControl": False,
                    "exportOnly": True,
                },
                indent=2,
                default=str,
            )
            artifacts["laser_export.json"] = json.dumps(
                {"format": "DXF-lines", "liveLaser": False, "liveMachineControl": False, "blocked": "LIVE_LASER", "geometry": dxf},
                indent=2,
                default=str,
            )
            manifest["artifacts"].extend(["cut_plan.json", "laser_export.json"])
        artifacts["release_manifest.json"] = json.dumps(manifest, indent=2, default=str)
        artifacts["checksums.json"] = json.dumps(self._checksums({k: v for k, v in artifacts.items() if k != "checksums.json"}), indent=2)
        return artifacts


def _dieline_svg(dieline: dict[str, Any]) -> str:
    panels = dieline.get("panels") or []
    parts = ['<svg xmlns="http://www.w3.org/2000/svg">']
    x = 0.0
    for p in panels:
        w, h = float(p.get("w") or 0), float(p.get("h") or 0)
        parts.append(f'<rect x="{x}" y="0" width="{w}" height="{h}" fill="none" stroke="#333"/>')
        x += w + 8
    parts.append("</svg>")
    return "".join(parts)
